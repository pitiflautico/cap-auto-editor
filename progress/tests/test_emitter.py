"""Tests for progress.emitter — mirrors capture/tests/test_progress.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from progress import NullEmitter, ProgressEmitter


class TestProgressEmitter:
    def test_truncates_on_init(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        p.write_text("old line\n", encoding="utf-8")
        ProgressEmitter(p)
        assert p.read_text(encoding="utf-8") == ""

    def test_emit_run_start_appends_line(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_run_start(phase="capture", total_steps=3)
        lines = p.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        ev = json.loads(lines[0])
        assert ev["type"] == "run_start"
        assert ev["phase"] == "capture"
        assert ev["total_steps"] == 3
        assert "ts" in ev

    def test_emit_full_sequence(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_run_start(phase="polish", total_steps=2)
        e.emit_step_start(index=1, total=2, name="transcribe", detail="running whisper")
        e.emit_step_done(index=1, name="transcribe", duration_ms=1500, summary={"segments": 42})
        e.emit_step_start(index=2, total=2, name="normalize", detail=None)
        e.emit_step_done(index=2, name="normalize", duration_ms=10, summary={"patches": 3})
        e.emit_run_done(ok=True, summary={"ok": 2, "failed": 0})
        lines = p.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 6
        types = [json.loads(l)["type"] for l in lines]
        assert types == ["run_start", "step_start", "step_done", "step_start", "step_done", "run_done"]

    def test_unicode_safe(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_step_start(index=1, total=1, name="capture_url", detail="https://qwen.ai/日本語")
        ev = json.loads(p.read_text(encoding="utf-8").strip())
        assert "日本語" in ev["detail"]

    def test_creates_parent_dirs(self, tmp_path: Path):
        p = tmp_path / "deeply" / "nested" / "progress.jsonl"
        ProgressEmitter(p)
        assert p.parent.exists()

    def test_second_init_truncates(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_run_start(phase="capture", total_steps=1)
        assert p.stat().st_size > 0
        # Second run: truncate again
        ProgressEmitter(p)
        assert p.read_text(encoding="utf-8") == ""


class TestNullEmitter:
    def test_does_not_write(self):
        e = NullEmitter()
        e.emit_run_start(phase="capture", total_steps=3)
        e.emit_step_start(index=1, total=3, name="step", detail=None)
        e.emit_step_done(index=1, name="step", duration_ms=100, summary={})
        e.emit_run_done(ok=True, summary={})
        # must not raise, no file written

    def test_null_noop_returns_none(self):
        e = NullEmitter()
        assert e.emit_run_start(phase="x", total_steps=1) is None
        assert e.emit_step_start(index=1, total=1, name="s") is None
        assert e.emit_step_done(index=1, name="s", duration_ms=0, summary={}) is None
        assert e.emit_run_done(ok=True, summary={}) is None
