"""Pydantic contracts for the compositor phase."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CompositionLayer(BaseModel):
    """One element on the timeline. Either a b-roll asset (image/video)
    or a subtitle word. The HTML builder emits both kinds as positioned
    divs whose visibility is GSAP-orchestrated.
    """
    model_config = ConfigDict(extra="forbid")

    kind: Literal["broll", "subtitle"]
    start_s: float
    end_s: float
    asset_rel: str | None = None             # broll: asset path relative to project
    asset_kind: Literal["image", "video", "screenshot", "title"] | None = None
    text: str | None = None                  # subtitle word
    layout: Literal["fullscreen", "split_top", "split_bottom"] = "fullscreen"
    beat_id: str | None = None               # provenance


class CompositionPlan(BaseModel):
    """Full plan handed to the HTML builder."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    created_at: datetime
    duration_s: float
    width: int = 1080
    height: int = 1920
    fps: int = 30
    audio_rel: str | None = None             # path to audio.wav, relative to project
    layers: list[CompositionLayer] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CompositionResult(BaseModel):
    """Status payload the CLI persists alongside final.mp4."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    created_at: datetime
    status: Literal["ok", "failed"]
    out_mp4: str | None = None
    duration_s: float | None = None
    sha256: str | None = None
    layer_counts: dict[str, int] = Field(default_factory=dict)
    message: str | None = None
