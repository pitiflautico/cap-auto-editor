"""ProgressEmitter — writes unified progress JSONL.

Each run truncates the file on construction, then appends one JSON line
per event. Atomic append via open+write (not seek) — safe for poll readers.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ProgressEmitter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate at run_start — each run owns its own log.
        self.path.write_text("", encoding="utf-8")

    def _emit(self, event_type: str, **fields: Any) -> None:
        payload = {
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        line = json.dumps(payload, default=str, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def emit_run_start(self, *, phase: str, total_steps: int) -> None:
        self._emit("run_start", phase=phase, total_steps=total_steps)

    def emit_step_start(
        self,
        *,
        index: int,
        total: int,
        name: str,
        detail: str | None = None,
    ) -> None:
        self._emit("step_start", index=index, total=total, name=name, detail=detail)

    def emit_step_done(
        self,
        *,
        index: int,
        name: str,
        duration_ms: int,
        summary: dict,
    ) -> None:
        self._emit("step_done", index=index, name=name, duration_ms=duration_ms, summary=summary)

    def emit_run_done(self, *, ok: bool, summary: dict) -> None:
        self._emit("run_done", ok=ok, summary=summary)


class NullEmitter:
    """No-op emitter for tests / programmatic use without a log file."""

    def emit_run_start(self, *, phase: str, total_steps: int) -> None:
        return None

    def emit_step_start(
        self,
        *,
        index: int,
        total: int,
        name: str,
        detail: str | None = None,
    ) -> None:
        return None

    def emit_step_done(
        self,
        *,
        index: int,
        name: str,
        duration_ms: int,
        summary: dict,
    ) -> None:
        return None

    def emit_run_done(self, *, ok: bool, summary: dict) -> None:
        return None
