"""Tests for broll_matcher (no real LLM — fake run_fn)."""
from __future__ import annotations

from datetime import datetime, timezone
import json

from analysis.contracts import (
    AnalysisResult, ArcAct, Beat, BrollHint, BrollTiming, Entity, Narrative, Topic,
)
from broll_matcher.matcher import match, _parse_anchor, _replace_anchor
from visual_inventory.contracts import (
    AssetInventory, Keyframe, Segment, VisualInventory,
)


def _hint(desc, *, type_="video", subject="Foo", shot_type="wide"):
    return BrollHint(type=type_, description=desc, timing=BrollTiming(),
                     energy_match="medium", subject=subject, shot_type=shot_type)


def _beat(beat_id, start, end, hints, *, ef="solution", text="hello"):
    return Beat(beat_id=beat_id, start_s=start, end_s=end, text=text,
                editorial_function=ef, hero_text_candidate=None,
                energy="medium", references_topic_ids=[], broll_hints=hints)


def _analysis(beats):
    n = Narrative(
        video_summary="x", narrative_thesis="y", audience="z", tone="t",
        arc_acts=[ArcAct(name="Hook", start_s=0, end_s=10,
                         purpose="Open the video.", topic_focus=[])],
        beats=beats, topics=[],
        entities=[Entity(canonical="Foo", surface_forms=["Foo"], kind="product",
                          mentioned_in_beats=["b001"])],
    )
    return AnalysisResult(
        created_at=datetime.now(timezone.utc), transcript_ref="/x",
        capture_manifest_ref=None, language="en",
        duration_s=beats[-1].end_s, llm_provider="x", llm_model="x", narrative=n,
    )


def _make_asset(slug, t1, t2, *, shot="wide", subjects=("Foo",), q=5,
                description="x", best_for=("solution",), asset_path="media/v.mp4"):
    kf = Keyframe(t_s=t1, thumb_path="kf.jpg", description=description,
                  shot_type=shot, has_baked_text=False,
                  free_zones=[], quality=q,
                  subjects=list(subjects), best_for=list(best_for),
                  subject_match_strength=5)
    seg = Segment(t_start_s=t1, t_end_s=t2, shot_type=shot,
                  description=description, quality=q, score=q/5)
    return AssetInventory(
        slug=slug, asset_path=asset_path, duration_s=t2 + 5,
        width=1920, height=1080,
        keyframes=[kf], shot_types_seen=[shot],
        has_any_baked_text=False, overall_quality=q,
        summary=description, best_segments=[seg],
    )


# ── anchor parsing helpers ────────────────────────────────────────

def test_parse_anchor_extracts_path_and_times():
    p = "Hero shot  [@ media/v.mp4 1.0-5.5s]"
    assert _parse_anchor(p) == ("media/v.mp4", 1.0, 5.5)


def test_parse_anchor_returns_none_when_absent():
    assert _parse_anchor("no anchor here") is None


def test_replace_anchor_rewrites_existing():
    out = _replace_anchor(
        "Hero shot  [@ media/old.mp4 0.0-3.0s]",
        "media/new.webm", 5.0, 9.5,
    )
    assert "[@ media/new.webm 5.0-9.5s]" in out
    assert "old.mp4" not in out


def test_replace_anchor_appends_when_missing():
    out = _replace_anchor("plain description", "media/v.mp4", 1.0, 4.0)
    assert "[@ media/v.mp4 1.0-4.0s]" in out
    assert out.startswith("plain description")


# ── match orchestration ───────────────────────────────────────────

def test_single_candidate_kept_deterministic_no_llm_call():
    """Only one candidate above threshold → no LLM call needed."""
    a = _analysis([_beat("b001", 0, 5, [
        _hint("[@ media/v.mp4 1.0-5.0s]")
    ])])
    inv = VisualInventory(
        created_at=datetime.now(timezone.utc), capture_root="/x",
        assets=[_make_asset("acme", 1.0, 5.0)],
    )
    called = {"n": 0}
    def fake_run(prompt, **kw):
        called["n"] += 1
        class R: output = '{"chosen_idx": 0, "rationale": "x"}'
        return R()
    new, report = match(a, inv, run_fn=fake_run)
    assert called["n"] == 0
    assert report.kept_deterministic == 1
    assert report.re_anchored_count == 0


def test_llm_picks_alternate_segment_rewrites_anchor():
    """LLM picks index 1 (not 0) → anchor rewritten."""
    a = _analysis([_beat("b001", 0, 5, [
        _hint("[@ media/A.mp4 1.0-5.0s]")
    ])])
    inv = VisualInventory(
        created_at=datetime.now(timezone.utc), capture_root="/x",
        assets=[
            _make_asset("acme", 1.0, 5.0,
                         description="generic logo", asset_path="media/A.mp4"),
            _make_asset("acme2", 7.0, 11.0,
                         description="data chart 31 billion params",
                         asset_path="media/B.mp4"),
        ],
    )
    def fake_run(prompt, **kw):
        class R: output = '{"chosen_idx": 1, "rationale": "stat fits beat better"}'
        return R()
    new, report = match(a, inv, run_fn=fake_run)
    assert report.re_anchored_count == 1
    new_desc = new.narrative.beats[0].broll_hints[0].description
    assert "[@ media/B.mp4 7.0-11.0s]" in new_desc


def test_llm_keeps_top_pick_no_re_anchor():
    a = _analysis([_beat("b001", 0, 5, [
        _hint("[@ media/A.mp4 1.0-5.0s]")
    ])])
    inv = VisualInventory(
        created_at=datetime.now(timezone.utc), capture_root="/x",
        assets=[
            _make_asset("a1", 1.0, 5.0, asset_path="media/A.mp4",
                         description="top match"),
            _make_asset("a2", 7.0, 11.0, asset_path="media/B.mp4",
                         description="alternative"),
        ],
    )
    def fake_run(prompt, **kw):
        class R: output = '{"chosen_idx": 0, "rationale": "top wins"}'
        return R()
    new, report = match(a, inv, run_fn=fake_run)
    assert report.kept_deterministic == 1
    assert report.re_anchored_count == 0


def test_llm_failure_falls_back_to_deterministic():
    a = _analysis([_beat("b001", 0, 5, [
        _hint("[@ media/A.mp4 1.0-5.0s]")
    ])])
    inv = VisualInventory(
        created_at=datetime.now(timezone.utc), capture_root="/x",
        assets=[
            _make_asset("a1", 1.0, 5.0, asset_path="media/A.mp4"),
            _make_asset("a2", 7.0, 11.0, asset_path="media/B.mp4"),
        ],
    )
    def fake_run(prompt, **kw):
        raise RuntimeError("LLM down")
    _, report = match(a, inv, run_fn=fake_run)
    assert report.fallback_count == 1
    # Top-deterministic was kept → no re-anchor counted
    assert report.re_anchored_count == 0


def test_unanchored_hint_skipped():
    """Hint without [@ ...] anchor is not processed."""
    a = _analysis([_beat("b001", 0, 5, [_hint("plain description, no anchor")])])
    inv = VisualInventory(
        created_at=datetime.now(timezone.utc), capture_root="/x",
        assets=[_make_asset("a", 1.0, 5.0)],
    )
    called = {"n": 0}
    def fake_run(prompt, **kw):
        called["n"] += 1
        class R: output = '{}'
        return R()
    new, report = match(a, inv, run_fn=fake_run)
    assert called["n"] == 0
    assert report.total_beats_with_anchor == 0
