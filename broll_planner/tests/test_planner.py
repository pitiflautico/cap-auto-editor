"""Tests for the broll_planner — block builders, JSON extraction,
sanitisation, and the merge step. No real LLM calls.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from analysis.contracts import (
    AnalysisResult, ArcAct, Beat, BrollTiming, Entity, Narrative,
)
from broll_planner.contracts import BeatPlan
from broll_planner.planner import (
    build_beats_block,
    build_entities_block,
    build_inventory_block,
    build_sources_block,
    extract_json,
    merge_plans_into_analysis,
    sanitize_hint_dict,
    _valid_slugs,
)
from broll_planner.prompts import BROLL_PLANNER_PROMPT, build_planner_prompt


# ── Fixtures ──────────────────────────────────────────────────────


def _beat(beat_id, start, end, *, ef="solution", text="x", energy="medium",
          hero=None, vn="required", vat="entity", vs=None):
    return Beat(
        beat_id=beat_id, start_s=start, end_s=end, text=text,
        editorial_function=ef, hero_text_candidate=hero, energy=energy,
        references_topic_ids=[], visual_need=vn,
        visual_anchor_type=vat, visual_subject=vs,
    )


def _analysis(beats, *, entities=None, language="en", duration=10.0):
    n = Narrative(
        video_summary="x", narrative_thesis="y", audience="z", tone="t",
        arc_acts=[ArcAct(name="Hook", start_s=0, end_s=duration,
                          purpose="Open the video.", topic_focus=[])],
        beats=beats, topics=[], entities=entities or [],
    )
    return AnalysisResult(
        created_at=datetime.now(timezone.utc), transcript_ref="/x",
        capture_manifest_ref=None, language=language, duration_s=duration,
        llm_provider="x", llm_model="x", narrative=n,
    )


def _capture_manifest(slugs: list[str]):
    return {
        "results": [
            {
                "request": {"slug": s, "url": f"https://{s}.example/"},
                "status": "ok",
                "title": f"{s} title",
                "text_preview": f"preview of {s}",
                "artifacts": {"assets": [
                    {"kind": "og_image", "path": f"media/{s}.jpg",
                     "width": 1200, "height": 630},
                ]},
            }
            for s in slugs
        ],
    }


# ── Prompt template smoke checks ──────────────────────────────────


def test_planner_prompt_lists_source_priority():
    """Hierarchy REAL > CAPTURED > DESIGNED must be in the prompt body."""
    assert "REAL > CAPTURED > DESIGNED" in BROLL_PLANNER_PROMPT
    assert "Source priority" in BROLL_PLANNER_PROMPT


def test_planner_prompt_lists_slide_kinds_and_mockup_kinds():
    for k in ("stat", "comparison", "list", "ranking", "progress"):
        assert k in BROLL_PLANNER_PROMPT
    for k in ("quote", "thesis", "manifesto", "kicker"):
        assert k in BROLL_PLANNER_PROMPT


def test_planner_prompt_requires_byte_exact_source_ref():
    assert "byte-for-byte" in BROLL_PLANNER_PROMPT


def test_planner_prompt_forbids_fake_mockup():
    assert "Never fabricate a UI clone" in BROLL_PLANNER_PROMPT


def test_planner_prompt_brand_appears_at_least_once():
    assert "brand must appear at least once" in BROLL_PLANNER_PROMPT


def test_build_planner_prompt_substitutes_lang_and_duration():
    out = build_planner_prompt(
        duration_s=51.0, language="es",
        beats_block="b1", entities_block="e1", sources_block="s1",
    )
    assert "Language: es" in out
    assert "51.0s" in out
    assert "<beats>\nb1" in out
    assert "<sources>\ns1" in out


# ── Block builders ────────────────────────────────────────────────


def test_build_beats_block_emits_visual_fields():
    a = _analysis([
        _beat("b001", 0, 3, vn="required", vat="entity", vs="MiroFish",
              ef="hook", energy="high", hero="20-year-old built AI"),
        _beat("b002", 3, 5, vn="none", vat=None, vs=None,
              ef="transition", energy="low", text="and"),
    ])
    block = build_beats_block(a)
    assert "b001" in block and "MiroFish" in block
    assert '"visual_need": "required"' in block
    assert '"visual_need": "none"' in block


def test_build_entities_block_includes_official_urls():
    a = _analysis([_beat("b001", 0, 3)],
                  entities=[Entity(canonical="MiroFish",
                                    surface_forms=["MiroFish"],
                                    kind="product",
                                    mentioned_in_beats=["b001"],
                                    official_urls=["https://mirofish.my/"])])
    block = build_entities_block(a)
    assert "MiroFish" in block
    assert "https://mirofish.my/" in block


def test_build_sources_block_only_includes_ok_captures():
    cm = {"results": [
        {"request": {"slug": "ok-page", "url": "https://x"},
         "status": "ok", "title": "T", "text_preview": "p",
         "artifacts": {"assets": []}},
        {"request": {"slug": "failed", "url": "https://y"},
         "status": "failed", "artifacts": {}},
    ]}
    block = build_sources_block(cm)
    assert "ok-page" in block
    assert "failed" not in block


def test_build_inventory_block_returns_none_when_empty():
    assert build_inventory_block(None) is None
    assert build_inventory_block({"assets": []}) is None


def test_build_inventory_block_includes_subjects_and_best_for():
    inv = {"assets": [{
        "slug": "github-com-mirofish",
        "asset_path": "media/image_01.jpg",
        "shot_types_seen": ["logo_centered"],
        "overall_quality": 5,
        "keyframes": [{
            "subjects": ["mirofish"],
            "best_for": ["hook", "payoff", "thesis"],
        }],
    }]}
    block = build_inventory_block(inv)
    assert "mirofish" in block and "logo_centered" in block
    assert '"best_for"' in block


# ── JSON extraction ───────────────────────────────────────────────


def test_extract_json_handles_fenced_response():
    raw = 'Sure, here:\n```json\n{"plans": []}\n```\n'
    assert extract_json(raw) == {"plans": []}


def test_extract_json_handles_bare_brace_block():
    raw = 'No fences, just JSON: {"plans": [{"beat_id": "b001"}]}'
    out = extract_json(raw)
    assert out == {"plans": [{"beat_id": "b001"}]}


def test_extract_json_raises_when_absent():
    with pytest.raises(ValueError):
        extract_json("absolutely no json here")


# ── Sanitisation ──────────────────────────────────────────────────


def test_sanitize_drops_invalid_source_ref():
    notes: list[str] = []
    out = sanitize_hint_dict(
        {"type": "web_capture", "source_ref": "ghost-slug"},
        valid_slugs={"real-slug"}, notes=notes, beat_id="b001",
    )
    assert out["source_ref"] is None
    assert any("ghost-slug" in n for n in notes)


def test_sanitize_keeps_valid_source_ref():
    notes: list[str] = []
    out = sanitize_hint_dict(
        {"type": "web_capture", "source_ref": "real-slug"},
        valid_slugs={"real-slug"}, notes=notes, beat_id="b001",
    )
    assert out["source_ref"] == "real-slug"
    assert notes == []


def test_sanitize_strips_source_ref_for_designed_types():
    notes: list[str] = []
    out = sanitize_hint_dict(
        {"type": "title", "source_ref": "real-slug"},
        valid_slugs={"real-slug"}, notes=notes, beat_id="b001",
    )
    assert out["source_ref"] is None


# ── Merge step ────────────────────────────────────────────────────


def test_valid_slugs_extracts_from_capture_manifest():
    cm = _capture_manifest(["a", "b", "c"])
    assert _valid_slugs(cm) == {"a", "b", "c"}


def test_merge_attaches_hints_to_correct_beats_and_drops_invalid_source_ref():
    a = _analysis([
        _beat("b001", 0, 3, vn="required", vat="entity", vs="MiroFish"),
        _beat("b002", 3, 5, vn="none"),
    ])
    plans = [
        BeatPlan(beat_id="b001", rationale="anchor", hints=[
            {"type": "web_capture", "description": "logo",
             "timing": {"in_pct": 0.0, "out_pct": 1.0},
             "energy_match": "medium",
             "source_ref": "mirofish-my"},
            {"type": "web_capture", "description": "phantom",
             "timing": {"in_pct": 0.0, "out_pct": 1.0},
             "energy_match": "low",
             "source_ref": "ghost-slug"},     # gets nullified
        ]),
        BeatPlan(beat_id="b002", rationale="connector", hints=[]),
    ]
    new_a, report = merge_plans_into_analysis(
        a, plans, valid_slugs={"mirofish-my"},
    )
    b001 = next(b for b in new_a.narrative.beats if b.beat_id == "b001")
    assert len(b001.broll_hints) == 2
    refs = [h.source_ref for h in b001.broll_hints]
    assert "mirofish-my" in refs
    assert None in refs
    b002 = next(b for b in new_a.narrative.beats if b.beat_id == "b002")
    assert b002.broll_hints == []
    # Report
    assert report.hints_emitted == 2
    assert report.beats_planned == 1
    assert report.source_ref_anchors == 1
    assert report.beats_required == 1
    assert report.type_counts.get("web_capture") == 2
    assert any("ghost-slug" in n for n in report.notes)


def test_merge_skips_unmatched_beat_ids_silently():
    """A plan referencing a beat_id that doesn't exist in the analysis
    should NOT crash — it just doesn't apply anywhere."""
    a = _analysis([_beat("b001", 0, 3, vn="required")])
    plans = [
        BeatPlan(beat_id="bXXX", rationale="ghost beat", hints=[
            {"type": "title", "description": "x",
             "timing": {"in_pct": 0.0, "out_pct": 1.0},
             "energy_match": "low"},
        ]),
    ]
    new_a, report = merge_plans_into_analysis(
        a, plans, valid_slugs=set(),
    )
    assert new_a.narrative.beats[0].broll_hints == []
    assert report.hints_emitted == 0


def test_merge_drops_hint_that_fails_validation():
    a = _analysis([_beat("b001", 0, 3, vn="required")])
    plans = [
        BeatPlan(beat_id="b001", rationale="bad", hints=[
            {"type": "WHAT", "description": "garbage",
             "timing": {"in_pct": 0.0, "out_pct": 1.0},
             "energy_match": "medium"},
        ]),
    ]
    _, report = merge_plans_into_analysis(
        a, plans, valid_slugs=set(),
    )
    assert report.hints_emitted == 0
    assert any("dropped invalid hint" in n for n in report.notes)


def test_merge_counts_required_and_optional_beats():
    a = _analysis([
        _beat("b001", 0, 2, vn="required"),
        _beat("b002", 2, 4, vn="optional"),
        _beat("b003", 4, 6, vn="none"),
        _beat("b004", 6, 10, vn="required"),
    ])
    _, report = merge_plans_into_analysis(a, [], valid_slugs=set())
    assert report.beats_total == 4
    assert report.beats_required == 2
    assert report.beats_optional == 1
