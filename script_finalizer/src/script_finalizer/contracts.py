"""Pydantic contracts for the script_finalizer phase."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Industry-backed baselines (April 2026, see README sources).
class IndustryBaselines(BaseModel):
    model_config = ConfigDict(extra="forbid")

    broll_coverage_min: float = 0.35
    broll_coverage_max: float = 0.50
    real_footage_ratio_min: float = 0.50    # video + web_capture + photo
    filler_ratio_max: float = 0.30          # slide + title
    max_talking_head_s: float = 7.0
    target_beat_duration_min_s: float = 6.0
    target_beat_duration_max_s: float = 10.0


# What we did to a single hint
HintAction = Literal[
    "kept",            # nothing changed
    "anchored",        # added (slug, asset_path, t_start, t_end) from inventory
    "downgraded",      # type changed (e.g. video → photo, slide → title)
    "dropped",         # removed because no support
]
# What we did to a single beat
BeatAction = Literal[
    "kept",
    "merged_with_next",
    "merged_with_prev",
]


class HintDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    hint_index: int
    action: HintAction
    rationale: str
    # If anchored, these point at the chosen segment in visual_inventory:
    chosen_slug: str | None = None
    chosen_asset_path: str | None = None
    chosen_t_start_s: float | None = None
    chosen_t_end_s: float | None = None
    # If downgraded:
    old_type: str | None = None
    new_type: str | None = None


class BeatDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    action: BeatAction
    rationale: str
    merged_into: str | None = None   # new beat_id when merged


class FinalizerReport(BaseModel):
    """Sidecar report explaining every decision."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    created_at: datetime
    duration_s: float

    # Adaptive layer outputs
    material_score: float = 0.0
    material_strength: Literal["thin", "default", "rich"] = "default"
    broll_target_min: float = 0.35
    broll_target_max: float = 0.50

    # Before/after stats
    beats_before: int = 0
    beats_after: int = 0
    hints_before: int = 0
    hints_after: int = 0
    coverage_pct_before: float = 0.0
    coverage_pct_after: float = 0.0
    real_footage_ratio_before: float = 0.0
    real_footage_ratio_after: float = 0.0
    filler_ratio_before: float = 0.0
    filler_ratio_after: float = 0.0

    # Per-element trace
    beat_decisions: list[BeatDecision] = Field(default_factory=list)
    hint_decisions: list[HintDecision] = Field(default_factory=list)

    # Industry baselines used (echo for audit)
    baselines: IndustryBaselines = Field(default_factory=IndustryBaselines)
    notes: list[str] = Field(default_factory=list)
