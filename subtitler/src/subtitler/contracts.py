"""Pydantic contracts for the subtitler phase."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SubtitleClip(BaseModel):
    """One subtitle event — almost always one word, occasionally a tiny merged pair."""
    model_config = ConfigDict(extra="forbid")

    index: int                      # 1-based, sequential
    start_s: float
    end_s: float
    text: str
    segment_index: int               # which transcript segment this came from


class SubtitleStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    font: str = "Montserrat"
    font_size: int = 64              # ASS units, render at 1080×1920
    bold: bool = True
    primary_color: str = "&H00FFFFFF"   # white (ASS BGR with alpha)
    pill_color: str = "&HBF000000"      # black, alpha 0.75 (BF in hex)
    pill_padding_px: int = 18
    border_radius_px: int = 28
    y_anchor_norm: float = 0.78        # bottom third (0=top, 1=bottom)
    fade_in_ms: int = 40
    fade_out_ms: int = 40


class SubtitleClips(BaseModel):
    schema_version: str = "1.0.0"
    created_at: datetime
    language: str
    duration_s: float
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    clips: list[SubtitleClip] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
