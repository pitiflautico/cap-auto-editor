"""Pydantic contracts for the broll_resolver phase (MVP)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ResolutionKind = Literal[
    "video", "image", "screenshot",  # actual asset on disk
    "title",                          # text-only overlay (no media file yet)
]
ResolutionSource = Literal[
    "anchor_in_inventory",
    "source_ref_first_video",
    "source_ref_screenshot",
    "title_fallback",
    # MVP placeholders — providers added later:
    "pexels_api",
    "yt_dlp_search",
    "ken_burns",
    "text_card",
]


class ResolvedAsset(BaseModel):
    """Concrete asset on disk ready for the renderer."""
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    hint_index: int
    kind: ResolutionKind
    source: ResolutionSource
    abs_path: str | None = None       # None when kind=title (no media file)
    slug: str | None = None           # capture slug if applicable
    # Sub-segment within the asset (only for video kind)
    t_start_s: float | None = None
    t_end_s: float | None = None
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    # Original hint fields preserved for downstream consumers
    type_: str = Field(alias="type")
    subject: str | None = None
    description: str = ""
    beat_start_s: float = 0.0
    beat_end_s: float = 0.0


class PendingHint(BaseModel):
    """A hint we couldn't resolve from local material — needs acquisition."""
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    hint_index: int
    type_: str = Field(alias="type")
    subject: str | None = None
    query: str | None = None
    queries_fallback: list[str] = Field(default_factory=list)
    shot_type: str | None = None
    duration_target_s: float | None = None
    description: str = ""
    editorial_function: str = ""
    beat_start_s: float = 0.0
    beat_end_s: float = 0.0
    reason: str = "no local material"
    # Designer-aware fields (preserved from analysis BrollHint so the
    # acquisition.providers.hf bridge can pick the right hf_designer
    # template + layout instead of falling back to defaults).
    slide_kind: str | None = None
    mockup_kind: str | None = None
    layout: str | None = None
    palette: dict[str, str] | None = None
    prefer_asset_kind: str | None = None


class BrollPlan(BaseModel):
    schema_version: str = "1.0.0"
    created_at: datetime
    resolved: list[ResolvedAsset] = Field(default_factory=list)


class PendingAcquisitions(BaseModel):
    schema_version: str = "1.0.0"
    created_at: datetime
    pending: list[PendingHint] = Field(default_factory=list)


class ResolverReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0.0"
    created_at: datetime
    total_hints: int = 0
    resolved_count: int = 0
    pending_count: int = 0
    resolved_by_source: dict[str, int] = Field(default_factory=dict)
    pending_by_type: dict[str, int] = Field(default_factory=dict)
