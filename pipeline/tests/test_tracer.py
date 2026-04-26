"""Tests for OrchestratorTracer."""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.tracer import OrchestratorTracer


class TestOrchestratorTracer:
    def test_emits_run_start(self, tmp_path):
        t = OrchestratorTracer(tmp_path)
        t.run_start("run1", "/tmp/v.webm", "/tmp/s.txt")
        events = _read_events(tmp_path)
        assert events[0]["type"] == "run_start"
        assert events[0]["run_name"] == "run1"

    def test_emits_phase_launched(self, tmp_path):
        t = OrchestratorTracer(tmp_path)
        t.phase_launched("capture", ["capture", "run"], 12345)
        events = _read_events(tmp_path)
        assert events[0]["type"] == "phase_launched"
        assert events[0]["phase"] == "capture"
        assert events[0]["pid"] == 12345

    def test_emits_phase_completed(self, tmp_path):
        t = OrchestratorTracer(tmp_path)
        t.phase_completed("capture", 5000, 0)
        events = _read_events(tmp_path)
        assert events[0]["type"] == "phase_completed"
        assert events[0]["duration_ms"] == 5000

    def test_emits_phase_failed(self, tmp_path):
        t = OrchestratorTracer(tmp_path)
        t.phase_failed("polish", 1000, "exit_code=1")
        events = _read_events(tmp_path)
        assert events[0]["type"] == "phase_failed"
        assert events[0]["error"] == "exit_code=1"

    def test_emits_run_done(self, tmp_path):
        t = OrchestratorTracer(tmp_path)
        t.run_done(ok=True, duration_ms=60000)
        events = _read_events(tmp_path)
        assert events[0]["type"] == "run_done"
        assert events[0]["ok"] is True

    def test_full_sequence(self, tmp_path):
        t = OrchestratorTracer(tmp_path)
        t.run_start("run1", "/v.webm", None)
        t.phase_launched("capture", ["capture", "run"], 1)
        t.phase_completed("capture", 3000, 0)
        t.phase_launched("polish", ["python", "script.py"], 2)
        t.phase_completed("polish", 5000, 0)
        t.run_done(ok=True, duration_ms=8000)

        events = _read_events(tmp_path)
        assert len(events) == 6
        assert [e["type"] for e in events] == [
            "run_start", "phase_launched", "phase_completed",
            "phase_launched", "phase_completed", "run_done",
        ]

    def test_append_only(self, tmp_path):
        t = OrchestratorTracer(tmp_path)
        t.run_start("r1", None, None)
        t.run_start("r2", None, None)  # second call appends
        events = _read_events(tmp_path)
        assert len(events) == 2

    def test_events_have_ts(self, tmp_path):
        t = OrchestratorTracer(tmp_path)
        t.run_start("r", None, None)
        events = _read_events(tmp_path)
        assert "ts" in events[0]


def _read_events(run_dir: Path) -> list[dict]:
    path = run_dir / "orchestrator.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
