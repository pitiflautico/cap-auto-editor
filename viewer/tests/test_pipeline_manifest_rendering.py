"""Tests for v3.0 generic artifact rendering from pipeline_manifest.json."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from progress import ProgressEmitter


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv("VIEWER_ROOTS", str(tmp_path))
    import viewer.app as app_module
    importlib.reload(app_module)
    return app_module, tmp_path


def _write_done(path: Path, phase: str, total_steps: int = 2) -> None:
    e = ProgressEmitter(path)
    e.emit_run_start(phase=phase, total_steps=total_steps)
    e.emit_run_done(ok=True, summary={"ok": total_steps, "failed": 0})


def _make_pipeline_manifest(run_dir: Path, phases: list[dict]) -> None:
    manifest = {
        "schema_version": "1.0.0",
        "run_name": run_dir.name,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "video_input": "/tmp/v.webm",
        "sources_input": None,
        "phases": phases,
    }
    (run_dir / "pipeline_manifest.json").write_text(json.dumps(manifest))


class TestPipelineManifestRendering:
    def test_get_pipeline_with_manifest_returns_200(self, configured):
        """GET /pipeline/<name> returns 200 when pipeline_manifest.json exists."""
        app_module, root = configured
        run_dir = root / "testpipe"
        cap_dir = run_dir / "capture"
        cap_dir.mkdir(parents=True)
        _write_done(cap_dir / "progress.jsonl", phase="capture")

        # Write minimal manifest
        _make_pipeline_manifest(run_dir, [
            {
                "name": "capture",
                "display_name": "Capture",
                "order": 1,
                "out_subdir": "capture",
                "depends_on": [],
                "render_artifacts": [
                    {
                        "type": "json_table",
                        "title": "URLs",
                        "path": "capture_manifest.json",
                        "path_pattern": None,
                        "options": {
                            "root_key": "results",
                            "columns": [
                                {"field": "request.slug", "label": "slug", "mono": True},
                                {"field": "status", "label": "status", "badge": True},
                            ],
                        },
                    }
                ],
            }
        ])

        client = TestClient(app_module.app)
        resp = client.get("/pipeline/testpipe")
        assert resp.status_code == 200

    def test_json_table_renders_columns(self, configured):
        """json_table artifact with data renders column headers."""
        app_module, root = configured
        run_dir = root / "testpipe2"
        cap_dir = run_dir / "capture"
        cap_dir.mkdir(parents=True)
        _write_done(cap_dir / "progress.jsonl", phase="capture")

        # Write a capture_manifest.json with data
        capture_manifest = {
            "results": [
                {"request": {"slug": "slug1", "url": "https://example.com"}, "status": "ok"},
                {"request": {"slug": "slug2", "url": "https://example2.com"}, "status": "failed"},
            ]
        }
        (cap_dir / "capture_manifest.json").write_text(json.dumps(capture_manifest))

        _make_pipeline_manifest(run_dir, [
            {
                "name": "capture",
                "display_name": "Capture",
                "order": 1,
                "out_subdir": "capture",
                "depends_on": [],
                "render_artifacts": [
                    {
                        "type": "json_table",
                        "title": "My URLs Table",
                        "path": "capture_manifest.json",
                        "path_pattern": None,
                        "options": {
                            "root_key": "results",
                            "columns": [
                                {"field": "request.slug", "label": "slug", "mono": True},
                                {"field": "status", "label": "status", "badge": True},
                            ],
                        },
                    }
                ],
            }
        ])

        client = TestClient(app_module.app)
        resp = client.get("/pipeline/testpipe2")
        assert resp.status_code == 200
        assert "My URLs Table" in resp.text
        assert "slug" in resp.text

    def test_missing_artifact_path_shows_not_available(self, configured):
        """Missing artifact path → shows '(not available yet)', no 500."""
        app_module, root = configured
        run_dir = root / "testpipe3"
        cap_dir = run_dir / "capture"
        cap_dir.mkdir(parents=True)
        _write_done(cap_dir / "progress.jsonl", phase="capture")

        # Manifest references a file that doesn't exist
        _make_pipeline_manifest(run_dir, [
            {
                "name": "capture",
                "display_name": "Capture",
                "order": 1,
                "out_subdir": "capture",
                "depends_on": [],
                "render_artifacts": [
                    {
                        "type": "json_table",
                        "title": "Missing File Table",
                        "path": "nonexistent_file.json",
                        "path_pattern": None,
                        "options": {"columns": [{"field": "x", "label": "X"}]},
                    }
                ],
            }
        ])

        client = TestClient(app_module.app)
        resp = client.get("/pipeline/testpipe3")
        assert resp.status_code == 200
        assert "not available" in resp.text.lower()

    def test_transcript_artifact_renders(self, configured):
        """transcript artifact renders segment text."""
        app_module, root = configured
        run_dir = root / "testpipe4"
        pol_dir = run_dir / "polish"
        pol_dir.mkdir(parents=True)
        _write_done(pol_dir / "progress.jsonl", phase="polish")

        transcript_data = {
            "segments": [
                {"start_s": 0.0, "end_s": 2.0, "text": "Hello world from transcript"},
                {"start_s": 2.0, "end_s": 4.0, "text": "Second segment here"},
            ]
        }
        (pol_dir / "transcript_polished.json").write_text(json.dumps(transcript_data))

        _make_pipeline_manifest(run_dir, [
            {
                "name": "polish",
                "display_name": "Polish",
                "order": 2,
                "out_subdir": "polish",
                "depends_on": [],
                "render_artifacts": [
                    {
                        "type": "transcript",
                        "title": "Polished Transcript",
                        "path": "transcript_polished.json",
                        "path_pattern": None,
                        "options": {},
                    }
                ],
            }
        ])

        client = TestClient(app_module.app)
        resp = client.get("/pipeline/testpipe4")
        assert resp.status_code == 200
        assert "Hello world from transcript" in resp.text

    def test_legacy_run_no_manifest_still_works(self, configured):
        """Legacy run (no pipeline_manifest.json) still appears on / and detail works."""
        app_module, root = configured
        run_dir = root / "legacy_run"
        cap_dir = run_dir / "capture"
        pol_dir = run_dir / "polish"
        cap_dir.mkdir(parents=True)
        pol_dir.mkdir(parents=True)
        _write_done(cap_dir / "progress.jsonl", phase="capture")
        _write_done(pol_dir / "progress.jsonl", phase="polish")
        # No pipeline_manifest.json written

        client = TestClient(app_module.app)
        # Index should list it
        resp = client.get("/")
        assert resp.status_code == 200
        assert "legacy_run" in resp.text

        # Detail should render without 500
        resp2 = client.get("/pipeline/legacy_run")
        assert resp2.status_code == 200
        assert "capture" in resp2.text

    def test_key_value_artifact_renders(self, configured):
        """key_value artifact renders field labels and values."""
        app_module, root = configured
        run_dir = root / "testpipe5"
        pol_dir = run_dir / "polish"
        pol_dir.mkdir(parents=True)
        _write_done(pol_dir / "progress.jsonl", phase="polish")

        summary_data = {"pct_saved": 12.5, "active_cuts": 3, "entity_candidates": 5}
        (pol_dir / "summary.json").write_text(json.dumps(summary_data))

        _make_pipeline_manifest(run_dir, [
            {
                "name": "polish",
                "display_name": "Polish",
                "order": 2,
                "out_subdir": "polish",
                "depends_on": [],
                "render_artifacts": [
                    {
                        "type": "key_value",
                        "title": "Run Summary",
                        "path": "summary.json",
                        "path_pattern": None,
                        "options": {
                            "fields": [
                                {"key": "pct_saved", "label": "% saved"},
                                {"key": "active_cuts", "label": "active cuts"},
                            ]
                        },
                    }
                ],
            }
        ])

        client = TestClient(app_module.app)
        resp = client.get("/pipeline/testpipe5")
        assert resp.status_code == 200
        assert "Run Summary" in resp.text
        assert "% saved" in resp.text
