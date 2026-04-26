"""Tests for pipeline contracts (Pydantic)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from pipeline.contracts import (
    ManifestPhase,
    PhaseDescriptor,
    PhaseResult,
    PipelineManifest,
    RenderArtifact,
    RunResult,
)


class TestRenderArtifact:
    def test_valid_type(self):
        a = RenderArtifact(type="transcript", title="T", path="x.json")
        assert a.type == "transcript"

    def test_all_valid_types(self):
        for t in ("transcript", "json_table", "image_gallery", "text_preview", "key_value", "iframe"):
            a = RenderArtifact(type=t, title="T")
            assert a.type == t

    def test_invalid_type_rejected(self):
        with pytest.raises(Exception):
            RenderArtifact(type="unknown_type", title="T")

    def test_roundtrip(self):
        a = RenderArtifact(type="json_table", title="URLs", path="x.json", options={"columns": []})
        data = a.model_dump()
        a2 = RenderArtifact(**data)
        assert a2.title == "URLs"
        assert a2.options["columns"] == []


class TestPipelineManifest:
    def _make_phase(self, name: str, order: int) -> ManifestPhase:
        return ManifestPhase(
            name=name,
            display_name=name.capitalize(),
            order=order,
            out_subdir=name,
            depends_on=[],
            render_artifacts=[],
        )

    def test_roundtrip(self):
        m = PipelineManifest(
            run_name="run_test",
            created_at=datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc),
            video_input="/tmp/video.webm",
            sources_input="/tmp/sources.txt",
            phases=[self._make_phase("capture", 1), self._make_phase("polish", 2)],
        )
        data = json.loads(m.model_dump_json())
        assert data["schema_version"] == "1.0.0"
        assert data["run_name"] == "run_test"
        assert len(data["phases"]) == 2

    def test_optional_sources(self):
        m = PipelineManifest(
            run_name="r",
            created_at=datetime.now(tz=timezone.utc),
            video_input="/tmp/v.webm",
            phases=[],
        )
        assert m.sources_input is None


class TestRunResult:
    def test_ok_result(self):
        r = RunResult(
            run_name="r",
            ok=True,
            phases=[PhaseResult(name="capture", ok=True, exit_code=0, duration_ms=1000)],
            duration_ms=1000,
        )
        assert r.ok

    def test_failed_result(self):
        r = RunResult(
            run_name="r",
            ok=False,
            phases=[PhaseResult(name="capture", ok=False, error="exit_code=1")],
        )
        assert not r.ok
        assert r.phases[0].error == "exit_code=1"
