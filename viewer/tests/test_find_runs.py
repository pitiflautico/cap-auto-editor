"""Regression tests for run discovery/resolution.

v1.0.1 patch: _find_run and _find_capture_run used to resolve only
`root/<name>` (first level), while _discover_* descended with rglob.
Result: runs produced under nested paths (e.g. /tmp/live_demo/capture/)
appeared in the index but detail links gave 404. These tests pin that
behaviour so it cannot regress.

v1.1 additions: unified progress parser, live_status on index cards,
missing progress.jsonl → live=False/done=False.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from progress import ProgressEmitter


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Point the viewer at an isolated root."""
    monkeypatch.setenv("VIEWER_ROOTS", str(tmp_path))
    # Force a re-import so the new env is read by _configured_roots()
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


def _minimal_capture_manifest() -> dict:
    return {
        "schema_version": "2.0.0",
        "created_at": "2026-04-24T12:00:00",
        "sources_file": None,
        "out_dir": "/tmp/whatever",
        "backend_default": "browser_sdk",
        "config_snapshot": {},
        "results": [],
    }


class TestFindRunNested:
    def test_polish_run_at_root_level(self, configured):
        app_module, root = configured
        run = root / "my_run"
        run.mkdir()
        (run / "timeline_map.json").write_text(json.dumps(_minimal_timeline_map()))

        client = TestClient(app_module.app)
        resp = client.get("/run/my_run")
        assert resp.status_code == 200

    def test_polish_run_nested_one_level(self, configured):
        """The real-world case: pipeline writes to <root>/session/polish/."""
        app_module, root = configured
        run = root / "session" / "polish"
        run.mkdir(parents=True)
        (run / "timeline_map.json").write_text(json.dumps(_minimal_timeline_map()))

        client = TestClient(app_module.app)
        resp = client.get("/run/polish")
        assert resp.status_code == 200

    def test_polish_run_nested_two_levels(self, configured):
        app_module, root = configured
        run = root / "a" / "b" / "deep_run"
        run.mkdir(parents=True)
        (run / "timeline_map.json").write_text(json.dumps(_minimal_timeline_map()))

        client = TestClient(app_module.app)
        resp = client.get("/run/deep_run")
        assert resp.status_code == 200

    def test_polish_run_missing_returns_404(self, configured):
        app_module, _ = configured
        client = TestClient(app_module.app)
        resp = client.get("/run/does_not_exist")
        assert resp.status_code == 404


class TestFindCaptureRunNested:
    def test_capture_run_at_root_level(self, configured):
        app_module, root = configured
        run = root / "my_capture"
        run.mkdir()
        (run / "capture_manifest.json").write_text(json.dumps(_minimal_capture_manifest()))

        client = TestClient(app_module.app)
        resp = client.get("/capture/my_capture")
        assert resp.status_code == 200

    def test_capture_run_nested_one_level(self, configured):
        app_module, root = configured
        run = root / "session" / "capture"
        run.mkdir(parents=True)
        (run / "capture_manifest.json").write_text(json.dumps(_minimal_capture_manifest()))

        client = TestClient(app_module.app)
        resp = client.get("/capture/capture")
        assert resp.status_code == 200

    def test_capture_run_missing_returns_404(self, configured):
        app_module, _ = configured
        client = TestClient(app_module.app)
        resp = client.get("/capture/does_not_exist")
        assert resp.status_code == 404


class TestProgressLiveStatus:
    """v1.1: unified progress integration on index cards."""

    def test_live_card_shows_detail_from_progress(self, configured):
        """A live run shows the detail string from the active step_start."""
        app_module, root = configured
        run = root / "live_run"
        run.mkdir()
        (run / "timeline_map.json").write_text(json.dumps(_minimal_timeline_map()))

        # Write an in-progress progress.jsonl
        e = ProgressEmitter(run / "progress.jsonl")
        e.emit_run_start(phase="polish", total_steps=7)
        e.emit_step_start(index=3, total=7, name="entity_candidates", detail="scanning transcript")

        client = TestClient(app_module.app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "scanning transcript" in resp.text

    def test_done_card_shows_summary_headline(self, configured):
        """A completed run shows a done summary on the index card."""
        app_module, root = configured
        run = root / "done_run"
        run.mkdir()
        (run / "timeline_map.json").write_text(json.dumps(_minimal_timeline_map()))

        e = ProgressEmitter(run / "progress.jsonl")
        e.emit_run_start(phase="polish", total_steps=7)
        e.emit_run_done(ok=True, summary={"pct_saved": 12.34, "edited_s": 80.0, "entity_candidates": 5})

        client = TestClient(app_module.app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "12.34% saved" in resp.text

    def test_missing_progress_jsonl_live_false_done_false(self, configured):
        """A run without progress.jsonl → live=False, done=False, live_status='—'."""
        app_module, root = configured
        run = root / "no_progress_run"
        run.mkdir()
        (run / "timeline_map.json").write_text(json.dumps(_minimal_timeline_map()))
        # No progress.jsonl written

        # Use _discover_runs directly
        runs = app_module._discover_runs()
        match = next((r for r in runs if r["name"] == "no_progress_run"), None)
        assert match is not None
        assert match["live"] is False
        assert match["done"] is False
        assert match["live_status"] == "—"
