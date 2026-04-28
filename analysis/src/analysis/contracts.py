"""contracts.py — Pydantic models for analysis.json.

Schema version 1.1.0. Use ConfigDict(extra="forbid") to catch LLM drift early.

v1.1 adds: BrollTiming, BrollHint, Beat.broll_hints, ArcAct.topic_focus.
Backward-compat: both new fields default to [].
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BrollTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")

    in_pct: float = Field(0.0, ge=0.0, le=1.0)
    out_pct: float = Field(1.0, ge=0.0, le=1.0)


class BrollHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # v1.2 taxonomy aligned with the renderer (HyperFrames / Remotion):
    #   video       — pre-recorded clip (official launch trailer, demo, b-roll footage)
    #   slide       — slide-style composition (title + bullets / data over flat bg)
    #   web_capture — screenshot of a URL (preferentially from capture/<slug>/screenshot.png)
    #   photo       — still photo (person, event, physical context)
    #   pexels      — generic stock photo or video clip (Pexels API or similar)
    #   mockup      — product mockup (laptop with UI, phone with app)
    #   title       — animated text overlay (hero text, kinetic typography, big claim)
    type: Literal[
        "video", "slide", "web_capture", "photo",
        "pexels", "mockup", "title",
    ]
    description: str
    timing: BrollTiming = Field(default_factory=BrollTiming)
    capcut_effect: Literal[
        "zoom_in_punch", "glitch_rgb", "logo_reveal",
        "velocity_edit", "mask_reveal", "split_screen",
        "slow_motion", "flicker"
    ] | None = None
    energy_match: Literal["high", "medium", "low"]
    source_ref: str | None = None
    # v1.5 — structured search hints consumed by broll_resolver. All optional
    # (None defaults), so older analyses round-trip without changes. The LLM
    # fills these to guide the source cascade (X / Reddit / Pexels / YouTube
    # via neobrowser); empty/None means "fall back to free-text description".
    query: str | None = None
    queries_fallback: list[str] = Field(default_factory=list)
    subject: str | None = None
    # Camera/composition hint. The renderer/resolver maps these to provider-
    # specific filters: "logo_centered" → Google Images "logo png"; "screen_recording"
    # → product UI demo; "portrait" → Pexels orientation=portrait; etc.
    shot_type: Literal[
        "close_up", "wide", "macro_animation", "screen_recording",
        "logo_centered", "portrait", "drone_aerial", "abstract",
    ] | None = None
    duration_target_s: float | None = None
    # v1.7 — designer-aware kinds. Only meaningful for the corresponding
    # `type`; `acquisition.providers.hf` reads them to pick the right
    # HyperFrames system prompt + layout. All optional so older analyses
    # round-trip; the prompt template (capabilities catalog injection)
    # promotes their use when emitting type=slide / mockup.
    slide_kind: Literal[
        "stat", "comparison", "list", "ranking", "progress",
    ] | None = None
    mockup_kind: Literal[
        "quote", "thesis", "manifesto", "kicker",
    ] | None = None
    layout: Literal["fullscreen", "split_top", "split_bottom"] | None = None
    palette: dict[str, str] | None = None


class ArcAct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str           # "Hook", "Problem", "Solution", ...
    start_s: float
    end_s: float
    purpose: str        # one descriptive sentence, not a bare keyword
    topic_focus: list[str] = Field(default_factory=list)


class Beat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str        # "b001", "b002", ...
    start_s: float
    end_s: float        # HARD CAP: end_s - start_s <= 12.0
    text: str           # literal transcript fragment
    editorial_function: Literal[
        "hook", "pain", "solution", "proof",
        "value", "how_to", "thesis", "payoff", "transition"
    ]
    hero_text_candidate: str | None     # 2-9 words, Sentence case, or null
    energy: Literal["high", "medium", "low"]
    references_topic_ids: list[str]

    # v2.0 — visual_need is now the only signal the analysis pass emits
    # for b-roll. The dedicated `broll_planner` phase reads (beats +
    # entities + sources + visual_inventory) and fills `broll_hints` in
    # a second LLM pass. The director should NOT emit broll_hints here;
    # the field stays as a list with default = [] so older analysis
    # files keep round-tripping, and the planner appends to it.
    visual_need: Literal["none", "optional", "required"] = "none"
    visual_anchor_type: Literal[
        "entity", "metric", "comparison", "quote",
        "platform", "feature", "mood",
    ] | None = None
    visual_subject: str | None = None       # canonical entity / number / phrase

    broll_hints: list[BrollHint] = Field(default_factory=list)

    # Editorial flags for content the prose field cannot carry without
    # corrupting the literal transcript text. Drop the legacy practice
    # of writing "(speaker retakes)" into `text` — keep `text` faithful,
    # surface the meta-info here.
    flags: list[
        Literal["speaker_retake", "asr_garbage", "silence", "music_only"]
    ] = Field(default_factory=list)


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_id: str       # lowercase_snake_case
    label: str          # short label as it appears in the video
    description: str    # 1-2 sentences
    role: Literal["main", "supporting"]
    kind: Literal["product", "company", "person", "concept", "platform", "sector", "event"]
    mentioned_in_beats: list[str]


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical: str
    surface_forms: list[str]
    kind: Literal["product", "company", "person", "platform", "sector", "concept"]
    mentioned_in_beats: list[str]
    official_urls: list[str] = []
    # v1.6 — populated by entity_enricher (post-analysis phase). Keys are
    # platform names ("x", "reddit", "youtube", "instagram", "github"); values
    # are lists of verified handles ("@googleai", "r/Bard", "@google").
    # Empty when entity is not enrichable or no platform yielded a result.
    # The analysis phase ALWAYS leaves this empty — the LLM never invents
    # handles. Lookup is deterministic (sources URLs + browser search).
    official_handles: dict[str, list[str]] = Field(default_factory=dict)


class Narrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_summary: str
    narrative_thesis: str
    audience: str
    tone: str
    arc_acts: list[ArcAct]
    beats: list[Beat]
    topics: list[Topic]
    entities: list[Entity]


class NumericConflict(BaseModel):
    """A magnitude mismatch between two text values referring to the same context."""
    model_config = ConfigDict(extra="forbid")

    field_a: str                       # e.g. "beats[5].text" / "narrative.video_summary"
    value_a: str                       # raw text fragment
    normalized_a: float | None = None  # e.g. 27_000_000 if "27 millones"
    field_b: str
    value_b: str
    normalized_b: float | None = None
    unit: str | None = None            # "param" | "tps" | "percent" | None
    entity_or_topic: str | None = None # canonical or topic_id linking both
    severity: Literal["block", "warn"] = "block"


class InvalidSourceRef(BaseModel):
    """A broll_hints[].source_ref that does not exist in the capture manifest."""
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    hint_index: int                    # position in the beat's broll_hints list
    old_source_ref: str
    reason: str                        # "not_found_in_capture_manifest" | "result_failed" | "manifest_missing"


class BeatIssue(BaseModel):
    """Non-fatal beat-level issue flagged during sanity validation."""
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    issue: Literal["asr_repetition", "too_short", "duration_mismatch"]
    detail: str                        # short explanation
    token: str | None = None           # offending token (for asr_repetition)
    count: int | None = None           # repetition run length (for asr_repetition)


class EntityPatch(BaseModel):
    """A surface_form → canonical replacement applied to a beat's text."""
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    from_: str = Field(alias="from")   # surface form replaced
    to: str                            # canonical replacement


class IDRemap(BaseModel):
    """A beat_id rename produced by the resequencer."""
    model_config = ConfigDict(extra="forbid")

    old: str
    new: str


class ValidationOverride(BaseModel):
    """Human-provided resolution for a validator finding.

    Generic across validators:
      - `kind` selects the finding type (numeric_conflict, asr_repetition, ...)
      - `match` is a partial dict whose keys must match equally on the finding
      - `resolution` carries the type-specific payload (e.g. canonical_value
        and canonical_raw for numeric_conflict)
      - `rationale` is a human-readable justification (mandatory — audit trail).

    No domain knowledge is hardcoded. New validators can introduce new
    `kind` values without touching this schema.
    """
    model_config = ConfigDict(extra="forbid")

    kind: Literal["numeric_conflict", "asr_repetition", "invalid_source_ref"]
    match: dict[str, str | int | float | None] = Field(default_factory=dict)
    resolution: dict[str, str | int | float | None] = Field(default_factory=dict)
    rationale: str


class ValidationReport(BaseModel):
    """Result of the deterministic post-LLM validation phase."""
    model_config = ConfigDict(extra="forbid")

    numeric_conflicts: list[NumericConflict] = Field(default_factory=list)
    invalid_source_refs: list[InvalidSourceRef] = Field(default_factory=list)
    flagged_beats: list[BeatIssue] = Field(default_factory=list)
    entity_patches: list[EntityPatch] = Field(default_factory=list)
    id_remaps: list[IDRemap] = Field(default_factory=list)
    applied_overrides: list[ValidationOverride] = Field(default_factory=list)
    entity_normalizations_applied: int = 0
    blocked: bool = False
    blocking_reasons: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.6.0"
    created_at: datetime
    transcript_ref: str             # path to transcript_polished.json
    capture_manifest_ref: str | None
    language: str
    duration_s: float
    llm_provider: str
    llm_model: str
    narrative: Narrative
    validation: ValidationReport = Field(default_factory=ValidationReport)
