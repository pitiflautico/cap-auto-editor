"""Pydantic contracts for auto_source phase."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DiscoveryStatus = Literal["found", "no_official", "skipped", "capture_failed"]


class TopicSourceDiscovery(BaseModel):
    """Per-topic record of the auto-source attempt."""
    model_config = ConfigDict(extra="forbid")

    topic_id: str
    topic_label: str
    query: str                       # e.g. '"Gemma 4" official'
    candidate_urls: list[str] = Field(default_factory=list)  # full Google result list
    chosen_url: str | None = None
    chosen_slug: str | None = None   # slug of the resulting capture
    status: DiscoveryStatus
    duration_ms: int = 0
    error: str | None = None


class AutoSourceReport(BaseModel):
    """Sidecar report for the run."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    created_at: datetime
    topics_total: int = 0
    topics_eligible: int = 0
    topics_resolved: int = 0
    new_captures: int = 0
    discoveries: list[TopicSourceDiscovery] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
