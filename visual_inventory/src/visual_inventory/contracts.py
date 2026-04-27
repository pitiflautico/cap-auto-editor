"""Pydantic contracts for the visual_inventory phase."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ShotType = Literal[
    "close_up", "wide", "macro_animation", "screen_recording",
    "logo_centered", "portrait", "drone_aerial", "abstract", "other",
]
FreeZone = Literal["top", "bottom", "left", "right", "center",
                   "top_left", "top_right", "bottom_left", "bottom_right"]


EditorialFunction = Literal[
    "hook", "pain", "solution", "proof", "value", "how_to",
    "thesis", "payoff", "transition",
]


class Keyframe(BaseModel):
    """One extracted frame + its vision-LLM analysis (descriptive + editorial)."""
    model_config = ConfigDict(extra="forbid")

    t_s: float                          # timestamp in source asset
    thumb_path: str                     # relative path to .jpg

    # Descriptive layer — what is shown
    description: str                    # 1-sentence factual summary
    shot_type: ShotType | None = None
    has_baked_text: bool = False
    free_zones: list[FreeZone] = Field(default_factory=list)
    luminosity: Literal["dark", "light", "mixed"] | None = None
    quality: int = 3                    # 1-5 (1=garbage, 5=hero)
    subjects: list[str] = Field(default_factory=list)  # named entities visible

    # Editorial layer — where this frame fits in a beat structure
    best_for: list[EditorialFunction] = Field(default_factory=list)
    editorial_brief: str = ""           # "ideal for hooks introducing Gemma 4 — clean logo reveal"
    subject_match_strength: int = 0     # 0-5: how clearly the frame depicts the named subject


class Segment(BaseModel):
    """A best segment within an asset, ready for the broll planner."""
    model_config = ConfigDict(extra="forbid")

    t_start_s: float
    t_end_s: float
    shot_type: ShotType | None = None
    description: str
    quality: int = 3
    score: float = 0.5                  # composite usefulness 0-1


class AssetInventory(BaseModel):
    """Per-asset inventory: keyframes + best segments + summary."""
    model_config = ConfigDict(extra="forbid")

    slug: str                           # capture slug
    asset_path: str                     # relative path under captures/<slug>/
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None

    keyframes: list[Keyframe] = Field(default_factory=list)
    shot_types_seen: list[ShotType] = Field(default_factory=list)
    has_any_baked_text: bool = False
    overall_quality: int = 3
    summary: str = ""                   # one-line editorial brief
    best_segments: list[Segment] = Field(default_factory=list)


class VisualInventory(BaseModel):
    schema_version: str = "1.0.0"
    created_at: datetime
    capture_root: str                   # absolute path to captures/ root
    assets: list[AssetInventory] = Field(default_factory=list)
    skipped: list[dict] = Field(default_factory=list)   # {path, reason}
    errors: list[str] = Field(default_factory=list)
