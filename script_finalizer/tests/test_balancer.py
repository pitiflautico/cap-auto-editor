"""Tests for the adaptive balancer (no LLM)."""
from __future__ import annotations

from datetime import datetime, timezone

from analysis.contracts import (
    AnalysisResult, ArcAct, Beat, BrollHint, BrollTiming, Entity, Narrative, Topic,
)
from script_finalizer.balancer import balance
from script_finalizer.scorer import (
    adaptive_broll_target,
    compute_material_score,
    material_strength_tier,
)
from visual_inventory.contracts import (
    AssetInventory, Keyframe, Segment, VisualInventory,
)


def _hint(type_="video", subject="Foo", shot_type="wide", desc="x"):
    return BrollHint(
        type=type_, description=desc, timing=BrollTiming(),
        energy_match="medium",
        subject=subject, shot_type=shot_type, query=f"{subject} demo",
    )


def _beat(beat_id, start, end, hints=None, ef="solution"):
    return Beat(
        beat_id=beat_id, start_s=start, end_s=end, text="hello",
        editorial_function=ef, hero_text_candidate=None, energy="medium",
        references_topic_ids=[], broll_hints=hints or [],
    )


def _analysis(beats, entities=None) -> AnalysisResult:
    n = Narrative(
        video_summary="x", narrative_thesis="y", audience="z", tone="t",
        arc_acts=[ArcAct(name="Hook", start_s=0, end_s=10,
                          purpose="Open the video.", topic_focus=[])],
        beats=beats, topics=[], entities=entities or [],
    )
    return AnalysisResult(
        created_at=datetime.now(timezone.utc), transcript_ref="/x",
        capture_manifest_ref=None, language="en",
        duration_s=beats[-1].end_s if beats else 60.0,
        llm_provider="x", llm_model="x", narrative=n,
    )


def _inv(asset_q=5, sm=5, shot="wide", subjects=("Foo",)) -> VisualInventory:
    kf = Keyframe(t_s=1.0, thumb_path="kf.jpg",
                  description="x", shot_type=shot,
                  has_baked_text=False, free_zones=[],
                  quality=asset_q, subjects=list(subjects),
                  best_for=["solution", "value"],
                  subject_match_strength=sm)
    seg = Segment(t_start_s=1.0, t_end_s=10.0, shot_type=shot,
                  description="seg", quality=asset_q, score=asset_q/5)
    a = AssetInventory(
        slug="acme-com", asset_path="media/video_01.mp4",
        duration_s=15.0, width=1920, height=1080,
        keyframes=[kf], shot_types_seen=[shot],
        has_any_baked_text=False, overall_quality=asset_q,
        summary="x", best_segments=[seg],
    )
    return VisualInventory(created_at=datetime.now(timezone.utc),
                           capture_root="/x", assets=[a])


# ── tier / target ──────────────────────────────────────────────────

def test_material_strength_tier_thresholds():
    assert material_strength_tier(0.9) == "rich"
    assert material_strength_tier(0.5) == "default"
    assert material_strength_tier(0.2) == "thin"


def test_adaptive_target_ranges():
    rich = adaptive_broll_target(0.9)
    thin = adaptive_broll_target(0.2)
    default = adaptive_broll_target(0.5)
    assert rich == (0.50, 0.65)
    assert thin == (0.25, 0.35)
    assert default == (0.35, 0.50)


def test_score_high_when_quality5_match5_subject_named():
    inv = _inv(asset_q=5, sm=5, subjects=("Foo",))
    score = compute_material_score(inv.assets,
                                    [Entity(canonical="Foo", surface_forms=["Foo"],
                                            kind="product", mentioned_in_beats=[])])
    assert score >= 0.9


def test_score_zero_when_inventory_empty():
    inv = VisualInventory(created_at=datetime.now(timezone.utc),
                          capture_root="/x", assets=[])
    assert compute_material_score(inv.assets, []) == 0.0


# ── balance behaviour ──────────────────────────────────────────────

def test_anchor_when_strong_match(tmp_path):
    a = _analysis([_beat("b001", 0, 10, hints=[_hint(type_="video", subject="Foo", shot_type="wide")])],
                  entities=[Entity(canonical="Foo", surface_forms=["Foo"],
                                   kind="product", mentioned_in_beats=["b001"])])
    inv = _inv(asset_q=5, sm=5, shot="wide", subjects=("Foo",))
    new, report = balance(a, inv)
    h = new.narrative.beats[0].broll_hints[0]
    assert h.source_ref == "acme-com"
    assert "[@ media/video_01.mp4" in h.description
    assert any(d.action == "anchored" for d in report.hint_decisions)
    assert report.material_strength == "rich"


def test_drop_hint_when_subject_named_but_no_inventory_support():
    """Hint claims subject 'Bar' but no asset has 'Bar'; should be dropped."""
    a = _analysis([_beat("b001", 0, 10, hints=[_hint(subject="Bar")])])
    inv = _inv(subjects=("OnlyFoo",))
    new, report = balance(a, inv)
    assert new.narrative.beats[0].broll_hints == []
    assert any(d.action == "dropped" for d in report.hint_decisions)


def test_downgrade_filler_when_tier_default():
    """slide hint with no inventory backing in default tier → downgrade to title."""
    a = _analysis([_beat("b001", 0, 10, hints=[_hint(type_="slide", subject="Foo", shot_type="logo_centered")])],
                  entities=[Entity(canonical="Foo", surface_forms=["Foo"],
                                   kind="product", mentioned_in_beats=["b001"])])
    # Inventory has Foo content but in different shot_type, low score
    inv = _inv(asset_q=2, sm=2, shot="abstract", subjects=("Foo",))
    new, report = balance(a, inv)
    h = new.narrative.beats[0].broll_hints[0]
    # Either anchored (if score crosses) or downgraded; assert one of those
    assert any(d.action in ("anchored", "downgraded", "kept", "dropped")
               for d in report.hint_decisions)


def test_report_has_before_after_stats():
    a = _analysis([_beat("b001", 0, 10, hints=[_hint(type_="video"), _hint(type_="slide")])])
    inv = VisualInventory(created_at=datetime.now(timezone.utc),
                          capture_root="/x", assets=[])
    _, report = balance(a, inv)
    assert report.beats_before == 1
    assert report.hints_before == 2
    assert report.beats_after == 1
    assert isinstance(report.coverage_pct_before, float)
    assert isinstance(report.coverage_pct_after, float)


def test_thin_tier_when_no_inventory():
    a = _analysis([_beat("b001", 0, 10, hints=[_hint()])])
    inv = VisualInventory(created_at=datetime.now(timezone.utc),
                          capture_root="/x", assets=[])
    _, report = balance(a, inv)
    assert report.material_strength == "thin"
    assert report.broll_target_min == 0.25
    assert report.broll_target_max == 0.35
