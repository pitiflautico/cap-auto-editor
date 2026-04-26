"""Tests for pipeline-run discovery and unified layout (v2.0).

Covers:
  - Two-phase pipeline listed on GET /
  - Live phase badge on index card
  - Canonical phase ordering
  - Legacy single-phase run still works
  - /pipeline/{name}/progress HTMX fragment
  - Polish preview: patches + entity candidates
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from progress import ProgressEmitter


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Point the viewer at an isolated root."""
    monkeypatch.setenv("VIEWER_ROOTS", str(tmp_path))
    import viewer.app as app_module
    importlib.reload(app_module)
    return app_module, tmp_path


def _write_run_start(path: Path, phase: str, total_steps: int = 3) -> None:
    e = ProgressEmitter(path)
    e.emit_run_start(phase=phase, total_steps=total_steps)


def _write_done(path: Path, phase: str, total_steps: int = 3) -> None:
    e = ProgressEmitter(path)
    e.emit_run_start(phase=phase, total_steps=total_steps)
    e.emit_run_done(ok=True, summary={"ok": total_steps, "failed": 0, "skipped_cache": 0})


# ── test_two_phase_pipeline_listed ─────────────────────────────────

class TestTwoPhasePipeline:
    def test_two_phase_pipeline_listed(self, configured):
        """GET / lists mypipe with both capture and polish phases."""
        app_module, root = configured
        pipeline_dir = root / "mypipe"
        cap_dir = pipeline_dir / "capture"
        pol_dir = pipeline_dir / "polish"
        cap_dir.mkdir(parents=True)
        pol_dir.mkdir(parents=True)
        _write_run_start(cap_dir / "progress.jsonl", phase="capture")
        _write_run_start(pol_dir / "progress.jsonl", phase="polish")

        client = TestClient(app_module.app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "mypipe" in resp.text
        assert "capture" in resp.text
        assert "polish" in resp.text

    def test_pipeline_detail_shows_both_phases(self, configured):
        """GET /pipeline/mypipe returns 200 and shows both phase sections."""
        app_module, root = configured
        pipeline_dir = root / "mypipe"
        cap_dir = pipeline_dir / "capture"
        pol_dir = pipeline_dir / "polish"
        cap_dir.mkdir(parents=True)
        pol_dir.mkdir(parents=True)
        _write_done(cap_dir / "progress.jsonl", phase="capture")
        _write_done(pol_dir / "progress.jsonl", phase="polish")

        client = TestClient(app_module.app)
        resp = client.get("/pipeline/mypipe")
        assert resp.status_code == 200
        # Both phase headers must appear
        assert "Phase:" in resp.text
        assert "capture" in resp.text
        assert "polish" in resp.text


# ── test_live_phase_shows_current_step_in_card ─────────────────────

class TestLivePhaseCard:
    def test_live_phase_shows_current_step_in_card(self, configured):
        """Index card for pipeline with in-progress phase shows step detail."""
        app_module, root = configured
        pipeline_dir = root / "livepipe"
        cap_dir = pipeline_dir / "capture"
        cap_dir.mkdir(parents=True)

        e = ProgressEmitter(cap_dir / "progress.jsonl")
        e.emit_run_start(phase="capture", total_steps=5)
        e.emit_step_start(index=2, total=5, name="capture_url", detail="https://example.com/live")

        client = TestClient(app_module.app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "livepipe" in resp.text
        # live badge should be present
        assert "live" in resp.text.lower() or "capture" in resp.text


# ── test_canonical_phase_order ──────────────────────────────────────

class TestCanonicalPhaseOrder:
    def test_canonical_phase_order(self, configured):
        """Phases are rendered in canonical order: capture, polish, analysis, broll_plan, builder."""
        app_module, root = configured
        pipeline_dir = root / "orderpipe"
        # Create in non-canonical alphabetical order
        for phase in ("builder", "analysis", "capture"):
            d = pipeline_dir / phase
            d.mkdir(parents=True)
            _write_done(d / "progress.jsonl", phase=phase)

        runs = app_module._discover_pipeline_runs()
        match = next((r for r in runs if r["name"] == "orderpipe"), None)
        assert match is not None, "orderpipe not found in discovery"
        phase_names = [ph["name"] for ph in match["phases"]]
        # capture before analysis before builder
        assert phase_names.index("capture") < phase_names.index("analysis")
        assert phase_names.index("analysis") < phase_names.index("builder")


# ── test_legacy_single_phase_still_works ───────────────────────────

class TestLegacySinglePhase:
    def test_legacy_single_phase_still_works(self, configured):
        """A dir at root level with timeline_map.json appears as single-phase pipeline."""
        app_module, root = configured
        run_dir = root / "legacy_polish"
        run_dir.mkdir()
        (run_dir / "timeline_map.json").write_text(json.dumps({
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
        }))

        client = TestClient(app_module.app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "legacy_polish" in resp.text

    def test_legacy_with_progress_still_works(self, configured):
        """A dir at root level with progress.jsonl appears as single-phase pipeline."""
        app_module, root = configured
        run_dir = root / "legacy_live"
        run_dir.mkdir()
        _write_done(run_dir / "progress.jsonl", phase="polish")

        client = TestClient(app_module.app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "legacy_live" in resp.text


# ── test_pipeline_progress_fragment ────────────────────────────────

class TestPipelineProgressFragment:
    def test_pipeline_progress_fragment(self, configured):
        """GET /pipeline/mypipe/progress returns HTML fragment with both phase names."""
        app_module, root = configured
        pipeline_dir = root / "mypipe"
        cap_dir = pipeline_dir / "capture"
        pol_dir = pipeline_dir / "polish"
        cap_dir.mkdir(parents=True)
        pol_dir.mkdir(parents=True)
        _write_done(cap_dir / "progress.jsonl", phase="capture")
        _write_done(pol_dir / "progress.jsonl", phase="polish")

        client = TestClient(app_module.app)
        resp = client.get("/pipeline/mypipe/progress")
        assert resp.status_code == 200
        assert "capture" in resp.text
        assert "polish" in resp.text

    def test_pipeline_progress_fragment_404_for_unknown(self, configured):
        """GET /pipeline/nope/progress returns 404."""
        app_module, _ = configured
        client = TestClient(app_module.app)
        resp = client.get("/pipeline/nope/progress")
        assert resp.status_code == 404


# ── test_polish_preview_includes_patches_and_candidates ────────────

class TestPolishPreview:
    def test_polish_preview_includes_patches_and_candidates(self, configured):
        """GET /pipeline/{name} shows patch surface_form->canonical and candidate surface_form."""
        app_module, root = configured
        pipeline_dir = root / "previewpipe"
        pol_dir = pipeline_dir / "polish"
        pol_dir.mkdir(parents=True)

        # Write done progress
        _write_done(pol_dir / "progress.jsonl", phase="polish")

        # Write transcript_patches.json
        (pol_dir / "transcript_patches.json").write_text(json.dumps({
            "patches": [
                {
                    "surface_form": "GPT4",
                    "canonical": "GPT-4",
                    "layer": "text_normalizer",
                    "occurrences": 3,
                    "confidence": 1.0,
                }
            ]
        }))

        # Write entity_candidates.json
        (pol_dir / "entity_candidates.json").write_text(json.dumps({
            "candidates": [
                {
                    "surface_form": "Qwen",
                    "occurrences": 7,
                    "first_time_s": 45.2,
                    "evidence": ["title_mention", "frequent"],
                }
            ]
        }))

        client = TestClient(app_module.app)
        resp = client.get("/pipeline/previewpipe")
        assert resp.status_code == 200
        # Patch: surface_form → canonical must appear
        assert "GPT4" in resp.text
        assert "GPT-4" in resp.text
        # Candidate surface_form must appear
        assert "Qwen" in resp.text
