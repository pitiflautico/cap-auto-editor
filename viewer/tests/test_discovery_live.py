"""Regression tests: progress.jsonl as primary discovery marker.

v1.1: runs appear in the index as soon as progress.jsonl exists,
even before timeline_map.json or capture_manifest.json are written.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from progress import ProgressEmitter


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Point the viewer at an isolated root."""
    monkeypatch.setenv("VIEWER_ROOTS", str(tmp_path))
    import importlib
    import viewer.app as app_module
    importlib.reload(app_module)
    return app_module, tmp_path


def _minimal_timeline_map() -> dict:
    return {
        "schema_version": "1.0.0",
        "created_at": "2026-04-24T12:00:00",
        "source_video_path": "/tmp/x.wav",
        "edited_video_path": None,
        "transcript_original_ref": "",
        "sources_used": [],
        "detector_versions": {},
        "cut_regions": [],
        "keep_segments": [],
        "total_original_duration_s": 100.0,
        "total_edited_duration_s": 100.0,
        "join_strategy": "hard_cut",
        "join_compensation_s": 0.0,
    }


class TestLiveDiscovery:
    def test_polish_run_visible_before_timeline_map(self, configured):
        """GET / lists the run the moment progress.jsonl exists (no timeline_map.json yet)."""
        app_module, root = configured
        run = root / "live_polish"
        run.mkdir()

        e = ProgressEmitter(run / "progress.jsonl")
        e.emit_run_start(phase="polish", total_steps=7)
        e.emit_step_start(index=1, total=7, name="transcribe", detail="running whisper on audio.wav")
        # Deliberately NOT writing timeline_map.json

        client = TestClient(app_module.app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "live_polish" in resp.text

    def test_polish_run_detail_accessible_before_timeline_map(self, configured):
        """GET /run/<name> returns 200 as soon as progress.jsonl exists."""
        app_module, root = configured
        run = root / "live_polish2"
        run.mkdir()

        e = ProgressEmitter(run / "progress.jsonl")
        e.emit_run_start(phase="polish", total_steps=7)
        e.emit_step_start(index=2, total=7, name="normalize", detail="applying universal normalizer")

        client = TestClient(app_module.app)
        resp = client.get("/run/live_polish2")
        assert resp.status_code == 200

    def test_capture_run_visible_before_manifest(self, configured):
        """GET /capture lists the run as soon as progress.jsonl exists (no capture_manifest.json)."""
        app_module, root = configured
        run = root / "live_capture"
        run.mkdir()

        e = ProgressEmitter(run / "progress.jsonl")
        e.emit_run_start(phase="capture", total_steps=3)
        e.emit_step_start(index=1, total=3, name="capture_url", detail="https://reddit.com/r/python")
        # Deliberately NOT writing capture_manifest.json

        client = TestClient(app_module.app)
        resp = client.get("/capture")
        assert resp.status_code == 200
        assert "live_capture" in resp.text

    def test_capture_run_detail_accessible_before_manifest(self, configured):
        """GET /capture/<name> returns 200 as soon as progress.jsonl exists."""
        app_module, root = configured
        run = root / "live_capture2"
        run.mkdir()

        e = ProgressEmitter(run / "progress.jsonl")
        e.emit_run_start(phase="capture", total_steps=2)
        e.emit_step_start(index=1, total=2, name="capture_url", detail="https://x.com")

        client = TestClient(app_module.app)
        resp = client.get("/capture/live_capture2")
        assert resp.status_code == 200

    def test_legacy_timeline_map_only_still_visible(self, configured):
        """A dir with only timeline_map.json (no progress.jsonl) still appears on /."""
        app_module, root = configured
        run = root / "legacy_run"
        run.mkdir()
        (run / "timeline_map.json").write_text(json.dumps(_minimal_timeline_map()))
        # No progress.jsonl

        client = TestClient(app_module.app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "legacy_run" in resp.text
