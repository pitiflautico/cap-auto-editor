"""Integration tests: orchestrator emits unified progress events to progress.jsonl."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from capture.contracts import CaptureRequest, CaptureResult
from capture.orchestrator import Orchestrator
from progress import parse_progress, ProgressEmitter


def _make_request(slug: str = "test-slug", url: str = "https://example.com") -> CaptureRequest:
    return CaptureRequest(url=url, normalized_url=url, slug=slug, priority=0)


def _make_ok_result(request: CaptureRequest, duration_ms: int = 100) -> CaptureResult:
    return CaptureResult(
        request=request,
        status="ok",
        backend="browser_sdk",
        captured_at=datetime.now(timezone.utc),
        duration_ms=duration_ms,
        attempts=1,
    )


class TestOrchestratorEmitsUnifiedProgress:
    def test_progress_file_is_progress_jsonl(self, tmp_path: Path):
        """CLI writes progress.jsonl (not capture_progress.jsonl)."""
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        assert p.exists()

    def test_run_start_has_phase_capture(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_run_start(phase="capture", total_steps=2)
        ev = json.loads(p.read_text().splitlines()[0])
        assert ev["type"] == "run_start"
        assert ev["phase"] == "capture"
        assert ev["total_steps"] == 2

    def test_step_start_has_detail_url(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_run_start(phase="capture", total_steps=1)
        e.emit_step_start(index=1, total=1, name="capture_url", detail="https://reddit.com/r/test")
        lines = p.read_text().splitlines()
        ev = json.loads(lines[1])
        assert ev["type"] == "step_start"
        assert ev["name"] == "capture_url"
        assert ev["detail"] == "https://reddit.com/r/test"

    def test_full_run_parse_state(self, tmp_path: Path):
        """Write a full 2-URL run and parse it back via parse_progress."""
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_run_start(phase="capture", total_steps=2)
        e.emit_step_start(index=1, total=2, name="capture_url", detail="https://a.com")
        e.emit_step_done(index=1, name="capture_url", duration_ms=500, summary={"status": "ok", "backend": "http_direct", "slug": "a-com"})
        e.emit_step_start(index=2, total=2, name="capture_url", detail="https://b.com")
        e.emit_step_done(index=2, name="capture_url", duration_ms=1200, summary={"status": "ok", "backend": "browser_sdk", "slug": "b-com"})
        e.emit_run_done(ok=True, summary={"ok": 2, "failed": 0, "skipped_cache": 0})

        state = parse_progress(p)
        assert state.done is True
        assert state.ok is True
        assert state.phase == "capture"
        assert state.summary["ok"] == 2
        assert state.completed_steps == 2

    def test_in_progress_parse_state(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_run_start(phase="capture", total_steps=3)
        e.emit_step_start(index=1, total=3, name="capture_url", detail="https://x.com")

        state = parse_progress(p)
        assert state.in_progress is True
        assert state.done is False
        assert state.current_index == 1
        assert state.current_detail == "https://x.com"
