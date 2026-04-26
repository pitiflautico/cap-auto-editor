"""Sanity checks for the Pydantic contracts.

Per INTERFACE.md v1.0, these schemas are the inter-phase wire format.
Breaking changes require bumping schema_version on TimelineMap AND
updating INTERFACE.md.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from polish.contracts import (
    CutRegion,
    EntityResolution,
    EntityResolutionSet,
    KeepSegment,
    Segment,
    SpeechSignal,
    SpeechSignals,
    TimelineMap,
    Transcript,
    Word,
)


# ── Transcript ─────────────────────────────────────────────────────

def test_word_basic():
    w = Word(text="hola", start_s=1.0, end_s=1.4)
    assert w.text == "hola"
    assert w.probability is None


def test_segment_words_default_empty():
    s = Segment(start_s=0, end_s=1, text="hola")
    assert s.words == []
    assert s.no_speech_prob is None


def test_transcript_empty():
    t = Transcript(duration_s=10.0, segments=[])
    assert t.language == "es"
    assert t.segments == []
    assert t.schema_version == "1.0.0"


# ── CutRegion ──────────────────────────────────────────────────────

def _valid_cut(**overrides):
    base = dict(
        id="c1",
        start_s=12.4,
        end_s=13.2,
        reason="silence",
        detector="ffmpeg_silencedetect",
        detector_version="1.0.0",
        confidence=0.92,
        action="cut",
    )
    base.update(overrides)
    return CutRegion(**base)


def test_cut_region_valid():
    c = _valid_cut(affected_words=[34, 35])
    assert c.action == "cut"
    assert c.padding_before_s == 0.12


def test_cut_region_confidence_out_of_range():
    with pytest.raises(ValidationError):
        _valid_cut(confidence=1.5)
    with pytest.raises(ValidationError):
        _valid_cut(confidence=-0.1)


def test_cut_region_invalid_reason():
    with pytest.raises(ValidationError):
        _valid_cut(reason="random_blabla")


def test_cut_region_invalid_action():
    with pytest.raises(ValidationError):
        _valid_cut(action="maybe")


# ── KeepSegment ────────────────────────────────────────────────────

def test_keep_segment_basic():
    k = KeepSegment(
        original_start_s=0.0,
        original_end_s=5.0,
        edited_start_s=0.0,
        edited_end_s=5.0,
    )
    assert k.source_cut_ids_before == []


# ── EntityResolution ───────────────────────────────────────────────

def test_entity_resolution_valid():
    e = EntityResolution(
        canonical="Gemma 4",
        surface_forms=["Genma", "genma"],
        confidence=0.95,
        source_url="https://blog.google/example",
        confirmed_by="llm",
    )
    assert e.canonical == "Gemma 4"


def test_entity_resolution_invalid_confirmed_by():
    with pytest.raises(ValidationError):
        EntityResolution(
            canonical="X",
            surface_forms=[],
            confidence=1.0,
            confirmed_by="magic",
        )


def test_entity_resolution_set_defaults():
    s = EntityResolutionSet()
    assert s.entities == []
    assert s.warnings == []


# ── SpeechSignal / SpeechSignals ───────────────────────────────────

def test_speech_signal_valid_types():
    for t in [
        "claim_detected",
        "numeric_fact",
        "entity_mentioned",
        "discourse_marker",
    ]:
        s = SpeechSignal(
            signal_type=t,
            start_s=0.0,
            end_s=1.0,
            text="whatever",
            confidence=0.8,
        )
        assert s.signal_type == t


def test_speech_signal_invalid_type():
    with pytest.raises(ValidationError):
        SpeechSignal(
            signal_type="highlight",
            start_s=0,
            end_s=1,
            text="x",
            confidence=0.5,
        )


def test_speech_signals_container_defaults():
    ss = SpeechSignals()
    assert ss.claims_detected == []
    assert ss.numeric_facts == []
    assert ss.entities_mentioned == []
    assert ss.discourse_markers == []
    assert ss.source == "transcript_polished"


# ── TimelineMap ────────────────────────────────────────────────────

def test_timeline_map_minimum():
    tm = TimelineMap(
        created_at=datetime.now(),
        source_video_path="/tmp/video.mp4",
        transcript_original_ref="sha256:abcdef",
        cut_regions=[],
        keep_segments=[],
        total_original_duration_s=60.0,
        total_edited_duration_s=60.0,
    )
    assert tm.schema_version == "1.0.0"
    assert tm.join_strategy == "hard_cut"
    assert tm.sources_used == []
    assert tm.detector_versions == {}


def test_timeline_map_with_cuts_and_keeps():
    c = _valid_cut(id="c1", start_s=10.0, end_s=10.5)
    k1 = KeepSegment(
        original_start_s=0,
        original_end_s=10,
        edited_start_s=0,
        edited_end_s=10,
    )
    k2 = KeepSegment(
        original_start_s=10.5,
        original_end_s=60,
        edited_start_s=10,
        edited_end_s=59.5,
        source_cut_ids_before=["c1"],
    )
    tm = TimelineMap(
        created_at=datetime.now(),
        source_video_path="/tmp/v.mp4",
        transcript_original_ref="t.json",
        sources_used=["https://example.com"],
        detector_versions={"ffmpeg_silencedetect": "1.0.0"},
        cut_regions=[c],
        keep_segments=[k1, k2],
        total_original_duration_s=60.0,
        total_edited_duration_s=59.5,
    )
    assert len(tm.cut_regions) == 1
    assert tm.keep_segments[1].source_cut_ids_before == ["c1"]
    assert tm.detector_versions["ffmpeg_silencedetect"] == "1.0.0"


def test_timeline_map_invalid_join_strategy():
    with pytest.raises(ValidationError):
        TimelineMap(
            created_at=datetime.now(),
            source_video_path="/tmp/v.mp4",
            transcript_original_ref="t.json",
            cut_regions=[],
            keep_segments=[],
            total_original_duration_s=10.0,
            total_edited_duration_s=10.0,
            join_strategy="blur",
        )


# ── JSON round-trip ────────────────────────────────────────────────

def test_timeline_map_json_roundtrip():
    tm = TimelineMap(
        created_at=datetime(2026, 4, 24, 12, 0, 0),
        source_video_path="/tmp/v.mp4",
        transcript_original_ref="t.json",
        cut_regions=[_valid_cut()],
        keep_segments=[],
        total_original_duration_s=10.0,
        total_edited_duration_s=9.2,
    )
    payload = tm.model_dump_json()
    tm2 = TimelineMap.model_validate_json(payload)
    assert tm2.cut_regions[0].id == "c1"
    assert tm2.created_at == tm.created_at
