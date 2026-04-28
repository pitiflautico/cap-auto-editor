"""Pydantic contracts for the broll_planner phase."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BeatPlan(BaseModel):
    """LLM-emitted plan for one beat. The planner LLM returns a list
    of these; the downstream merge step appends each plan's hints to
    the matching `analysis.narrative.beats[*].broll_hints`."""
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    rationale: str       # 1 sentence why these hint(s) for this beat
    # Each entry must conform to analysis.contracts.BrollHint — but
    # the planner emits dicts so the analysis BrollHint model can
    # validate them on merge.
    hints: list[dict] = Field(default_factory=list)


class PlannerReport(BaseModel):
    """Per-run trace persisted alongside analysis_with_broll.json."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    created_at: datetime
    beats_total: int
    beats_required: int       # beats with visual_need=required
    beats_optional: int
    beats_planned: int        # beats that ended up with at least 1 hint
    hints_emitted: int
    type_counts: dict[str, int] = Field(default_factory=dict)
    source_ref_anchors: int   # hints with non-null source_ref
    notes: list[str] = Field(default_factory=list)
    plans: list[BeatPlan] = Field(default_factory=list)


PlannerSourceKind = Literal["entity", "metric", "comparison", "quote",
                              "platform", "feature", "mood"]
