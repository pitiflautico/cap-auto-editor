"""Integration tests: phase2b_demo emits unified progress events to progress.jsonl."""
from __future__ import annotations

import json
from pathlib import Path

from progress import NullEmitter, ProgressEmitter, parse_progress


class TestPolishProgressEmitter:
    def test_truncates_on_init(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        p.write_text("old line\n", encoding="utf-8")
        ProgressEmitter(p)
        assert p.read_text(encoding="utf-8") == ""

    def test_run_start_has_phase_polish(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_run_start(phase="polish", total_steps=7)
        ev = json.loads(p.read_text().strip())
        assert ev["type"] == "run_start"
        assert ev["phase"] == "polish"
        assert ev["total_steps"] == 7

    def test_seven_steps_emitted(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_run_start(phase="polish", total_steps=7)
        step_names = ["transcribe", "normalize", "project_aliases", "entity_candidates", "silences", "cuts", "timeline"]
        for i, name in enumerate(step_names, start=1):
            e.emit_step_start(index=i, total=7, name=name, detail=f"detail {name}")
            e.emit_step_done(index=i, name=name, duration_ms=100, summary={"ok": True})
        e.emit_run_done(ok=True, summary={"edited_s": 60.0, "pct_saved": 10.0, "entity_candidates": 3})

        state = parse_progress(p)
        assert state.done is True
        assert state.phase == "polish"
        assert state.completed_steps == 7
        assert state.ok is True
        assert state.summary["pct_saved"] == 10.0

    def test_step_detail_preserved(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_run_start(phase="polish", total_steps=7)
        e.emit_step_start(index=1, total=7, name="transcribe", detail="running whisper on audio.wav")
        state = parse_progress(p)
        assert state.in_progress is True
        assert state.current_detail == "running whisper on audio.wav"
        assert state.current_name == "transcribe"

    def test_unicode_safe(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        e = ProgressEmitter(p)
        e.emit_step_start(index=1, total=7, name="normalize", detail="日本語テスト")
        ev = json.loads(p.read_text().strip())
        assert "日本語テスト" in ev["detail"]

    def test_null_emitter_noop(self):
        e = NullEmitter()
        e.emit_run_start(phase="polish", total_steps=7)
        e.emit_step_start(index=1, total=7, name="transcribe", detail="x")
        e.emit_step_done(index=1, name="transcribe", duration_ms=100, summary={})
        e.emit_run_done(ok=True, summary={})
        # must not raise
