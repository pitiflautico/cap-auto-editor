"""Pydantic contracts for broll_matcher."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CandidateRow(BaseModel):
    """A single (asset, segment) candidate considered for a beat."""
    model_config = ConfigDict(extra="forbid")

    slug: str
    asset_path: str
    t_start_s: float
    t_end_s: float
    description: str
    deterministic_score: float
    chosen: bool = False         # the LLM picked this one


class BeatDecision(BaseModel):
    """Per-beat trace of the matcher's decision."""
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    hint_index: int
    beat_text: str
    editorial_function: str
    n_candidates: int
    chosen_idx: int | None = None    # index into candidates (0-based)
    rationale: str = ""
    fallback_used: bool = False      # True if LLM failed → kept deterministic
    candidates: list[CandidateRow] = Field(default_factory=list)


class MatcherReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    created_at: datetime
    total_beats_with_anchor: int = 0
    re_anchored_count: int = 0       # LLM picked a different segment than determinist
    kept_deterministic: int = 0
    fallback_count: int = 0
    decisions: list[BeatDecision] = Field(default_factory=list)
