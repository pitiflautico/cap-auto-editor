"""Append-only JSONL tracer for orchestrator events."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class OrchestratorTracer:
    """Emits events to <run_dir>/orchestrator.jsonl."""

    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "orchestrator.jsonl"

    def _emit(self, event: dict) -> None:
        event.setdefault("ts", _now())
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    def run_start(self, run_name: str, video: str | None, sources: str | None) -> None:
        self._emit({
            "type": "run_start",
            "run_name": run_name,
            "video": video,
            "sources": sources,
        })

    def phase_launched(self, phase: str, cmd: list[str], pid: int | None) -> None:
        self._emit({
            "type": "phase_launched",
            "phase": phase,
            "cmd": cmd,
            "pid": pid,
        })

    def phase_completed(self, phase: str, duration_ms: int, exit_code: int) -> None:
        self._emit({
            "type": "phase_completed",
            "phase": phase,
            "duration_ms": duration_ms,
            "exit_code": exit_code,
        })

    def phase_failed(self, phase: str, duration_ms: int, error: str) -> None:
        self._emit({
            "type": "phase_failed",
            "phase": phase,
            "duration_ms": duration_ms,
            "error": error,
        })

    def run_done(self, ok: bool, duration_ms: int) -> None:
        self._emit({
            "type": "run_done",
            "ok": ok,
            "duration_ms": duration_ms,
        })
