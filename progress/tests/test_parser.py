"""Tests for progress.parser — parse_progress()."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from progress import parse_progress, ProgressState


def _write_lines(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n",
        encoding="utf-8",
    )


class TestParseProgressMissingFile:
    def test_missing_returns_neutral(self, tmp_path: Path):
        state = parse_progress(tmp_path / "no_such.jsonl")
        assert isinstance(state, ProgressState)
        assert state.in_progress is False
        assert state.done is False
        assert state.phase is None
        assert state.events_seen == 0


class TestParseProgressRunStartOnly:
    def test_run_start_only_in_progress(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        _write_lines(p, [{"type": "run_start", "ts": "2026-01-01T00:00:00+00:00", "phase": "polish", "total_steps": 7}])
        state = parse_progress(p)
        assert state.in_progress is True
        assert state.done is False
        assert state.phase == "polish"
        assert state.total_steps == 7
        assert state.events_seen == 1


class TestParseProgressInProgress:
    def test_step_start_sets_current(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        _write_lines(p, [
            {"type": "run_start", "ts": "T", "phase": "capture", "total_steps": 3},
            {"type": "step_start", "ts": "T", "index": 1, "total": 3, "name": "capture_url", "detail": "https://x.com"},
        ])
        state = parse_progress(p)
        assert state.in_progress is True
        assert state.current_index == 1
        assert state.current_name == "capture_url"
        assert state.current_detail == "https://x.com"
        assert state.completed_steps == 0

    def test_step_done_clears_active(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        _write_lines(p, [
            {"type": "run_start", "ts": "T", "phase": "capture", "total_steps": 2},
            {"type": "step_start", "ts": "T", "index": 1, "total": 2, "name": "step_a", "detail": None},
            {"type": "step_done", "ts": "T", "index": 1, "name": "step_a", "duration_ms": 100, "summary": {}},
            {"type": "step_start", "ts": "T", "index": 2, "total": 2, "name": "step_b", "detail": "detail_b"},
        ])
        state = parse_progress(p)
        assert state.in_progress is True
        assert state.completed_steps == 1
        assert state.current_index == 2
        assert state.current_name == "step_b"
        assert state.current_detail == "detail_b"


class TestParseProgressDone:
    def test_run_done_marks_done(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        _write_lines(p, [
            {"type": "run_start", "ts": "T", "phase": "polish", "total_steps": 7},
            {"type": "step_start", "ts": "T", "index": 1, "total": 7, "name": "transcribe", "detail": "x"},
            {"type": "step_done", "ts": "T", "index": 1, "name": "transcribe", "duration_ms": 5000, "summary": {}},
            {"type": "run_done", "ts": "T", "ok": True, "summary": {"ok": 1, "failed": 0}},
        ])
        state = parse_progress(p)
        assert state.done is True
        assert state.in_progress is False
        assert state.ok is True
        assert state.summary == {"ok": 1, "failed": 0}
        assert state.completed_steps == 1

    def test_run_done_ok_false(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        _write_lines(p, [
            {"type": "run_start", "ts": "T", "phase": "capture", "total_steps": 2},
            {"type": "run_done", "ts": "T", "ok": False, "summary": {"failed": 2}},
        ])
        state = parse_progress(p)
        assert state.done is True
        assert state.ok is False


class TestParseProgressMalformed:
    def test_malformed_lines_skipped(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        p.write_text(
            '{"type":"run_start","ts":"T","phase":"capture","total_steps":1}\n'
            'NOT JSON AT ALL\n'
            '{"type":"run_done","ts":"T","ok":true,"summary":{}}\n',
            encoding="utf-8",
        )
        state = parse_progress(p)
        assert state.done is True
        assert state.events_seen == 2  # malformed line skipped

    def test_empty_file_returns_neutral(self, tmp_path: Path):
        p = tmp_path / "progress.jsonl"
        p.write_text("", encoding="utf-8")
        state = parse_progress(p)
        assert state.in_progress is False
        assert state.done is False
        assert state.events_seen == 0
