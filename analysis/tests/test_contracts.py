"""test_contracts.py — Unit tests for Pydantic contracts."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from analysis.contracts import (
    ArcAct, Beat, BrollHint, BrollTiming, Entity, Narrative, AnalysisResult, Topic,
)


VALID_BEAT = dict(
    beat_id="b001",
    start_s=0.0,
    end_s=5.0,
    text="Hola, bienvenidos al canal.",
    editorial_function="hook",
    hero_text_candidate="Bienvenidos al canal",
    energy="high",
    references_topic_ids=[],
)

VALID_TOPIC = dict(
    topic_id="qwen_3_6",
    label="Qwen 3.6 27B",
    description="Modelo open-source de Alibaba.",
    role="main",
    kind="product",
    mentioned_in_beats=["b001"],
)

VALID_ENTITY = dict(
    canonical="Qwen 3.6",
    surface_forms=["Qwen 3 punto 6", "Qwen"],
    kind="product",
    mentioned_in_beats=["b001"],
    official_urls=[],
)

VALID_NARRATIVE = dict(
    video_summary="Resumen del video.",
    narrative_thesis="Tesis principal.",
    audience="Desarrolladores de IA.",
    tone="Directo y entusiasta.",
    arc_acts=[dict(name="Hook", start_s=0.0, end_s=10.0, purpose="Engancha al espectador.")],
    beats=[VALID_BEAT],
    topics=[VALID_TOPIC],
    entities=[VALID_ENTITY],
)


def test_beat_roundtrip():
    b = Beat(**VALID_BEAT)
    assert b.beat_id == "b001"
    assert b.editorial_function == "hook"
    assert b.energy == "high"


def test_beat_bad_editorial_function():
    with pytest.raises(ValidationError):
        Beat(**{**VALID_BEAT, "editorial_function": "nonsense"})


def test_beat_bad_energy():
    with pytest.raises(ValidationError):
        Beat(**{**VALID_BEAT, "energy": "ultra"})


def test_topic_bad_role():
    with pytest.raises(ValidationError):
        Topic(**{**VALID_TOPIC, "role": "primary"})


def test_topic_bad_kind():
    with pytest.raises(ValidationError):
        Topic(**{**VALID_TOPIC, "kind": "animal"})


def test_entity_bad_kind():
    with pytest.raises(ValidationError):
        Entity(**{**VALID_ENTITY, "kind": "thing"})


def test_beat_extra_field_rejected():
    """ConfigDict(extra='forbid') should reject unknown fields."""
    with pytest.raises(ValidationError):
        Beat(**{**VALID_BEAT, "unknown_field": "oops"})


def test_narrative_roundtrip():
    n = Narrative(**VALID_NARRATIVE)
    assert len(n.arc_acts) == 1
    assert len(n.beats) == 1
    assert n.beats[0].beat_id == "b001"


def test_analysis_result_roundtrip():
    result = AnalysisResult(
        schema_version="1.0.0",
        created_at=datetime.now(timezone.utc),
        transcript_ref="/tmp/transcript_polished.json",
        capture_manifest_ref=None,
        language="es",
        duration_s=120.0,
        llm_provider="claude_pool",
        llm_model="sonnet",
        narrative=Narrative(**VALID_NARRATIVE),
    )
    dumped = result.model_dump_json()
    import json
    d = json.loads(dumped)
    assert d["schema_version"] == "1.0.0"
    assert d["language"] == "es"


def test_tile_helper():
    """Verify consecutive beats cover audio without gaps."""
    beats = [
        Beat(**{**VALID_BEAT, "beat_id": "b001", "start_s": 0.0, "end_s": 5.0}),
        Beat(**{**VALID_BEAT, "beat_id": "b002", "start_s": 5.0, "end_s": 10.0}),
        Beat(**{**VALID_BEAT, "beat_id": "b003", "start_s": 10.0, "end_s": 15.0}),
    ]
    for i in range(len(beats) - 1):
        assert beats[i].end_s == beats[i + 1].start_s, \
            f"Gap between {beats[i].beat_id} and {beats[i+1].beat_id}"


# ── v1.1 schema tests ───────────────────────────────────────────────

VALID_BROLL_HINT = dict(
    type="web_capture",
    description="Official product landing page with hero image and CTA button",
    timing={"in_pct": 0.0, "out_pct": 1.0},
    capcut_effect="zoom_in_punch",
    energy_match="high",
    source_ref="fooproduct-homepage",
)


def test_broll_hint_roundtrip_all_fields():
    h = BrollHint(**VALID_BROLL_HINT)
    assert h.type == "web_capture"
    assert h.description == "Official product landing page with hero image and CTA button"
    assert h.timing.in_pct == 0.0
    assert h.timing.out_pct == 1.0
    assert h.capcut_effect == "zoom_in_punch"
    assert h.energy_match == "high"
    assert h.source_ref == "fooproduct-homepage"
    # v1.5 fields default to None / [] when not provided — older analyses round-trip
    assert h.query is None
    assert h.queries_fallback == []
    assert h.subject is None
    assert h.shot_type is None
    assert h.duration_target_s is None


def test_broll_hint_with_v1_5_search_hints():
    h = BrollHint(
        **VALID_BROLL_HINT,
        query="MiroFish demo simulation",
        queries_fallback=["MiroFish predictive AI", "swarm intelligence demo"],
        subject="MiroFish",
        shot_type="screen_recording",
        duration_target_s=3.5,
    )
    assert h.query == "MiroFish demo simulation"
    assert len(h.queries_fallback) == 2
    assert h.subject == "MiroFish"
    assert h.shot_type == "screen_recording"
    assert h.duration_target_s == 3.5


def test_broll_hint_rejects_invalid_shot_type():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BrollHint(**VALID_BROLL_HINT, shot_type="ultra_wide_4k")


def test_broll_timing_defaults():
    timing = BrollTiming()
    assert timing.in_pct == 0.0
    assert timing.out_pct == 1.0


def test_broll_hint_capcut_effect_none():
    h = BrollHint(**{**VALID_BROLL_HINT, "capcut_effect": None})
    assert h.capcut_effect is None


def test_broll_hint_rejects_invalid_type():
    with pytest.raises(ValidationError):
        BrollHint(**{**VALID_BROLL_HINT, "type": "gif"})


def test_broll_hint_rejects_in_pct_out_of_range():
    with pytest.raises(ValidationError):
        BrollHint(**{**VALID_BROLL_HINT, "timing": {"in_pct": 1.5, "out_pct": 1.0}})


def test_beat_broll_hints_default_empty():
    b = Beat(**VALID_BEAT)
    assert b.broll_hints == []


def test_beat_with_three_broll_hints():
    hints = [
        {**VALID_BROLL_HINT, "type": "web_capture", "energy_match": "high"},
        {**VALID_BROLL_HINT, "type": "title", "capcut_effect": "logo_reveal", "energy_match": "medium"},
        {**VALID_BROLL_HINT, "type": "slide", "capcut_effect": None, "energy_match": "low"},
    ]
    b = Beat(**{**VALID_BEAT, "broll_hints": hints})
    assert len(b.broll_hints) == 3
    assert b.broll_hints[0].type == "web_capture"
    assert b.broll_hints[1].type == "title"
    assert b.broll_hints[2].type == "slide"


def test_arc_act_topic_focus_default_empty():
    act = ArcAct(name="Hook", start_s=0.0, end_s=10.0, purpose="Hooks the viewer with a bold claim.")
    assert act.topic_focus == []


def test_arc_act_topic_focus_with_values():
    act = ArcAct(
        name="Value",
        start_s=10.0,
        end_s=30.0,
        purpose="Demonstrates the core value proposition to the viewer.",
        topic_focus=["foo_product", "bar_company"],
    )
    assert act.topic_focus == ["foo_product", "bar_company"]


def test_analysis_result_schema_version_default_1_6_0():
    import json
    result = AnalysisResult(
        created_at=datetime.now(timezone.utc),
        transcript_ref="/tmp/transcript_polished.json",
        capture_manifest_ref=None,
        language="es",
        duration_s=120.0,
        llm_provider="claude_pool",
        llm_model="sonnet",
        narrative=Narrative(**VALID_NARRATIVE),
    )
    d = json.loads(result.model_dump_json())
    assert d["schema_version"] == "1.6.0"
