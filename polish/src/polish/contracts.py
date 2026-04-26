"""Pydantic contracts for v6/polish/.

Source of truth: INTERFACE.md (v1.0 FROZEN).
Any change here requires updating INTERFACE.md first and bumping
schema_version on TimelineMap.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Transcript ─────────────────────────────────────────────────────

class Word(BaseModel):
    text: str
    start_s: float
    end_s: float
    probability: float | None = None


class Segment(BaseModel):
    start_s: float
    end_s: float
    text: str
    words: list[Word] = Field(default_factory=list)
    no_speech_prob: float | None = None


class Transcript(BaseModel):
    schema_version: str = "1.0.0"
    language: str = "es"
    duration_s: float
    segments: list[Segment]
    model: str | None = None


# ── Cuts ───────────────────────────────────────────────────────────

CutReason = Literal[
    "silence",
    "filler",
    "noisy_pause",
    "retake",
    "false_start",
    "manual",
]

CutAction = Literal["cut", "compress", "keep"]

JoinStrategy = Literal["hard_cut", "micro_fade", "crossfade"]


class CutRegion(BaseModel):
    id: str
    start_s: float
    end_s: float
    reason: CutReason
    detector: str                       # e.g. "ffmpeg_silencedetect"
    detector_version: str
    confidence: float = Field(ge=0.0, le=1.0)
    action: CutAction
    padding_before_s: float = 0.12
    padding_after_s: float = 0.12
    affected_words: list[int] = Field(default_factory=list)
    notes: str | None = None


class KeepSegment(BaseModel):
    original_start_s: float
    original_end_s: float
    edited_start_s: float
    edited_end_s: float
    source_cut_ids_before: list[str] = Field(default_factory=list)


# ── Entity resolution ──────────────────────────────────────────────

ConfirmationSource = Literal[
    "llm",
    "human",
    "briefing",
    "auto_accept",
    "unresolved",
]


class EntityResolution(BaseModel):
    canonical: str                      # e.g. "Gemma 4"
    surface_forms: list[str]            # e.g. ["Genma", "genma"]
    confidence: float = Field(ge=0.0, le=1.0)
    source_url: str | None = None
    confirmed_by: ConfirmationSource


class EntityResolutionSet(BaseModel):
    schema_version: str = "1.0.0"
    entities: list[EntityResolution] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── Speech signals ─────────────────────────────────────────────────

SignalType = Literal[
    "claim_detected",
    "numeric_fact",
    "entity_mentioned",
    "discourse_marker",
]


class SpeechSignal(BaseModel):
    signal_type: SignalType
    start_s: float
    end_s: float
    text: str
    evidence_spans: list[tuple[int, int]] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class SpeechSignals(BaseModel):
    schema_version: str = "1.0.0"
    source: str = "transcript_polished"
    claims_detected: list[SpeechSignal] = Field(default_factory=list)
    numeric_facts: list[SpeechSignal] = Field(default_factory=list)
    entities_mentioned: list[SpeechSignal] = Field(default_factory=list)
    discourse_markers: list[SpeechSignal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── Timeline Map (master document) ─────────────────────────────────

class TimelineMap(BaseModel):
    """Master edit document. The single source of truth for what was
    cut from the source video.

    `keep_segments` and `cut_map.json` are derived views regenerated
    from this document — do not edit them by hand.
    """
    model_config = ConfigDict(validate_assignment=True)

    schema_version: str = "1.0.0"
    created_at: datetime
    source_video_path: str
    edited_video_path: str | None = None
    transcript_original_ref: str       # path or sha256
    sources_used: list[str] = Field(default_factory=list)
    detector_versions: dict[str, str] = Field(default_factory=dict)
    cut_regions: list[CutRegion]
    keep_segments: list[KeepSegment]
    total_original_duration_s: float
    total_edited_duration_s: float
    join_strategy: JoinStrategy = "hard_cut"
    join_compensation_s: float = 0.0
    warnings: list[str] = Field(default_factory=list)
