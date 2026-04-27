"""Pydantic contracts for the storyboard phase."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PreviewKind = Literal["video", "image", "screenshot", "title", "missing"]


class StoryboardEntry(BaseModel):
    """One preview slot — usually one per beat (multiple if beat has multi hints)."""
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    hint_index: int
    beat_start_s: float
    beat_end_s: float

    type_: str = Field(alias="type")     # original BrollHint type
    subject: str | None = None
    hero_text: str | None = None         # if the beat has hero_text_candidate
    description: str = ""

    kind: PreviewKind                    # what kind of asset feeds this preview
    thumb_path: str                      # relative to storyboard out_dir
    source_abs_path: str | None = None   # absolute path of the underlying asset
    asset_provider: str | None = None    # text_card / pexels_image / anchor_in_inventory / ...
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None      # for video previews


class Storyboard(BaseModel):
    schema_version: str = "1.0.0"
    created_at: datetime
    duration_s: float
    entries: list[StoryboardEntry] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
