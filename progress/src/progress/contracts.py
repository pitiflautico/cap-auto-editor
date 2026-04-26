"""Pydantic models for the unified progress protocol events and parser output."""
from __future__ import annotations

from pydantic import BaseModel


class ProgressState(BaseModel):
    """Output of parse_progress(path). Always returned; degrades gracefully."""

    phase: str | None = None
    total_steps: int | None = None
    current_index: int | None = None
    current_name: str | None = None
    current_detail: str | None = None
    completed_steps: int = 0
    in_progress: bool = False
    done: bool = False
    ok: bool | None = None
    summary: dict = {}
    events_seen: int = 0
