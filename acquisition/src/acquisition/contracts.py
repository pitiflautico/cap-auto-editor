"""Pydantic contracts for the acquisition phase."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ProviderName = Literal[
    "pexels_video", "pexels_image",
    "yt_dlp_official",          # future
    "ken_burns",                # future
    "text_card",                # always-works fallback
]


class AcquisitionAttempt(BaseModel):
    """Trace of one provider call for one pending hint."""
    model_config = ConfigDict(extra="forbid")

    provider: ProviderName
    success: bool
    duration_ms: int = 0
    error: str | None = None
    chosen_url: str | None = None    # source URL when applicable (Pexels link)
    chosen_id: str | None = None     # provider asset id


class AcquisitionEntry(BaseModel):
    """A pending hint after acquisition — either resolved or still missing."""
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    hint_index: int
    type_: str = Field(alias="type")
    subject: str | None = None
    abs_path: str | None = None      # the asset on disk (None if all providers failed)
    kind: Literal["video", "image", "title"] | None = None
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    final_provider: ProviderName | None = None
    attempts: list[AcquisitionAttempt] = Field(default_factory=list)


class AcquisitionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    created_at: datetime
    pending_total: int = 0
    acquired_count: int = 0
    text_card_fallback: int = 0
    api_errors: int = 0
    provider_counts: dict[str, int] = Field(default_factory=dict)
    entries: list[AcquisitionEntry] = Field(default_factory=list)
