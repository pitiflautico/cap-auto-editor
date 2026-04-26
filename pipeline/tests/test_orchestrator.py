"""Tests for the orchestrator — dry-run with mocked subprocess."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext
from pipeline.orchestrator import _topo_sort, _write_manifest, run
from pipeline.registry import PIPELINE_PHASES


# ── helpers ─────────────────────────────────────────────────────────

def _make_descriptor(name: str, order: int, depends_on: list[str] = None, on_failure: str = "abort") -> PhaseDescriptor:
    return PhaseDescriptor(
        name=name,
        display_name=name.capitalize(),
        order=order,
        out_subdir=name,
        cli_command=["echo", name],
        cli_args=lambda ctx, phase_dir: [],
        depends_on=depends_on or [],
        on_failure=on_failure,
        render_artifacts=[],
    )


class TestTopoSort:
    def test_linear_chain(self):
        a = _make_descriptor("a", 1)
        b = _make_descriptor("b", 2, depends_on=["a"])
        result = _topo_sort([b, a])
        assert [d.name for d in result] == ["a", "b"]

    def test_no_deps(self):
        a = _make_descriptor("a", 1)
        b = _make_descriptor("b", 2)
        result = _topo_sort([a, b])
        assert [d.name for d in result] == ["a", "b"]

    def test_cycle_raises(self):
        a = _make_descriptor("a", 1, depends_on=["b"])
        b = _make_descriptor("b", 2, depends_on=["a"])
        with pytest.raises(ValueError, match="Cycle"):
            _topo_sort([a, b])


class TestWriteManifest:
    def test_writes_manifest(self, tmp_path):
        phases = [_make_descriptor("capture", 1), _make_descriptor("polish", 2, depends_on=["capture"])]
        _write_manifest(tmp_path, "test_run", Path("/tmp/v.webm"), Path("/tmp/s.txt"), phases)
        mf = tmp_path / "pipeline_manifest.json"
        assert mf.exists()
        data = json.loads(mf.read_text())
        assert data["run_name"] == "test_run"
        assert len(data["phases"]) == 2
        assert data["phases"][0]["name"] == "capture"


class TestOrchestratorRun:
    def _mock_popen(self, returncode=0):
        """Return a context-manager-safe Popen mock."""
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.returncode = returncode
        mock_proc.wait.return_value = returncode
        mock_proc.__enter__ = MagicMock(return_value=mock_proc)
        mock_proc.__exit__ = MagicMock(return_value=False)
        return mock_proc

    @patch("pipeline.orchestrator.PIPELINE_PHASES")
    @patch("pipeline.orchestrator.subprocess.Popen")
    def test_successful_run_creates_artifacts(self, mock_popen, mock_phases, tmp_path):
        """Successful run writes manifest and orchestrator.jsonl."""
        mock_proc = self._mock_popen(returncode=0)
        mock_popen.return_value = mock_proc

        phases = [_make_descriptor("capture", 1)]
        mock_phases.__iter__ = lambda self: iter(phases)
        mock_phases.__len__ = lambda self: 1

        # Directly call with a small phase list
        import pipeline.orchestrator as orch_mod
        orig_phases = orch_mod.PIPELINE_PHASES
        orch_mod.PIPELINE_PHASES = phases
        try:
            result = run(
                run_dir=tmp_path / "run1",
                run_name="run1",
                video=None,
                sources=None,
            )
        finally:
            orch_mod.PIPELINE_PHASES = orig_phases

        run_dir = tmp_path / "run1"
        assert (run_dir / "pipeline_manifest.json").exists()
        assert (run_dir / "orchestrator.jsonl").exists()

        events = [json.loads(l) for l in (run_dir / "orchestrator.jsonl").read_text().splitlines() if l.strip()]
        types = [e["type"] for e in events]
        assert "run_start" in types
        assert "run_done" in types

    @patch("pipeline.orchestrator.subprocess.Popen")
    def test_abort_on_failure_stops_pipeline(self, mock_popen, tmp_path):
        """If first phase fails with on_failure=abort, second phase is NOT launched."""
        fail_proc = self._mock_popen(returncode=1)
        mock_popen.return_value = fail_proc

        a = _make_descriptor("a", 1, on_failure="abort")
        b = _make_descriptor("b", 2, depends_on=["a"], on_failure="abort")

        import pipeline.orchestrator as orch_mod
        orig = orch_mod.PIPELINE_PHASES
        orch_mod.PIPELINE_PHASES = [a, b]
        try:
            result = run(
                run_dir=tmp_path / "run_abort",
                run_name="run_abort",
                video=None,
                sources=None,
            )
        finally:
            orch_mod.PIPELINE_PHASES = orig

        assert not result.ok
        # Popen called only once (phase a), not for phase b (b depends on a which failed)
        assert mock_popen.call_count == 1

    @patch("pipeline.orchestrator.subprocess.Popen")
    def test_run_result_has_phase_results(self, mock_popen, tmp_path):
        """RunResult contains PhaseResult per launched phase."""
        mock_popen.return_value = self._mock_popen(returncode=0)

        a = _make_descriptor("a", 1)
        import pipeline.orchestrator as orch_mod
        orig = orch_mod.PIPELINE_PHASES
        orch_mod.PIPELINE_PHASES = [a]
        try:
            result = run(
                run_dir=tmp_path / "run_result",
                run_name="run_result",
                video=None,
                sources=None,
            )
        finally:
            orch_mod.PIPELINE_PHASES = orig

        assert result.ok
        assert len(result.phases) == 1
        assert result.phases[0].name == "a"
