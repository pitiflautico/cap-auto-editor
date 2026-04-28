"""Tests for compositor.adapter — v6 outputs → v4 visual_plan_resolved dict.

Pure data assertions; no v4 builder invoked.
"""
from __future__ import annotations

from compositor.adapter import (
    _classify_asset,
    _group_subtitle_clips,
    _punch_style_for,
    _resolved_by_beat,
    build_visual_plan,
)


# ── Fixtures ───────────────────────────────────────────────────────


def _beat(beat_id, start, end, *, ef="solution", hero=None,
          energy="medium", visual_need="required"):
    return {
        "beat_id": beat_id,
        "start_s": start, "end_s": end,
        "editorial_function": ef,
        "energy": energy,
        "text": "x",
        "hero_text_candidate": hero,
        "visual_need": visual_need,
    }


def _resolved(beat_id, *, abs_path, layout="fullscreen", kind="image",
              hint_index=0, slide_kind=None, mockup_kind=None,
              duration_s=None):
    return {
        "beat_id": beat_id, "hint_index": hint_index,
        "abs_path": abs_path, "layout": layout, "kind": kind,
        "slide_kind": slide_kind, "mockup_kind": mockup_kind,
        "duration_s": duration_s,
    }


def _analysis(beats, *, duration_s=10.0, language="en"):
    return {
        "duration_s": duration_s,
        "language": language,
        "narrative": {"beats": beats},
    }


def _subs(clips):
    return {"clips": clips}


def _clip(text, start_s, end_s):
    return {"text": text, "start_s": start_s, "end_s": end_s}


# ── _classify_asset ────────────────────────────────────────────────


def test_classify_asset_video_extensions():
    assert _classify_asset("/x/y.mp4") == "broll_video"
    assert _classify_asset("/x/y.MOV") == "broll_video"
    assert _classify_asset("/x/y.webm") == "broll_video"


def test_classify_asset_image_extensions():
    assert _classify_asset("/x/y.png") == "broll_image"
    assert _classify_asset("/x/y.JPG") == "broll_image"
    assert _classify_asset("/x/y.gif") == "broll_image"


def test_classify_asset_unknown_falls_back_to_image():
    assert _classify_asset("/x/y.bin") == "broll_image"


# ── _resolved_by_beat ──────────────────────────────────────────────


def test_resolved_by_beat_groups_and_sorts_by_hint_index():
    plan = {"resolved": [
        {"beat_id": "b001", "hint_index": 1, "abs_path": "/a"},
        {"beat_id": "b001", "hint_index": 0, "abs_path": "/b"},
        {"beat_id": "b002", "hint_index": 0, "abs_path": "/c"},
    ]}
    out = _resolved_by_beat(plan)
    assert [r["abs_path"] for r in out["b001"]] == ["/b", "/a"]
    assert [r["abs_path"] for r in out["b002"]] == ["/c"]


# ── subtitle phrase grouping ───────────────────────────────────────


def test_group_subtitle_clips_caps_at_eight_words_per_phrase():
    clips = [_clip(f"w{i}", i * 0.2, i * 0.2 + 0.18) for i in range(20)]
    phrases = _group_subtitle_clips(clips)
    # 20 words → at least 3 phrases when capped at 8
    assert len(phrases) >= 3
    for ph in phrases:
        assert len(ph["words"]) <= 8


def test_group_subtitle_clips_makes_word_offsets_relative():
    """Words inside each phrase have ms offsets relative to phrase start."""
    clips = [
        _clip("hola", 10.0, 10.4),
        _clip("mundo", 10.4, 10.9),
    ]
    phrases = _group_subtitle_clips(clips)
    p = phrases[0]
    assert p["start_s"] == 10.0
    assert p["words"][0]["start_ms"] == 0
    assert p["words"][0]["end_ms"] == 400
    assert p["words"][1]["start_ms"] == 400
    assert p["words"][1]["end_ms"] == 900


def test_group_subtitle_clips_breaks_phrase_on_long_gap():
    """A gap > 0.6s ends the phrase even if word count is low."""
    clips = [
        _clip("a", 0.0, 0.2),
        _clip("b", 0.2, 0.4),
        _clip("c", 5.0, 5.2),       # 4.6 s gap
        _clip("d", 5.2, 5.4),
    ]
    phrases = _group_subtitle_clips(clips)
    assert len(phrases) == 2
    assert [w["text"] for w in phrases[0]["words"]] == ["a", "b"]
    assert [w["text"] for w in phrases[1]["words"]] == ["c", "d"]


def test_group_subtitle_clips_skips_empty_text():
    clips = [_clip("", 0, 0.1), _clip("hola", 0.1, 0.4)]
    phrases = _group_subtitle_clips(clips)
    assert sum(len(p["words"]) for p in phrases) == 1


# ── _punch_style_for ───────────────────────────────────────────────


def test_punch_style_returns_stat_for_metric_hero():
    beat = _beat("b001", 0, 3, ef="proof", hero="$4M raised in 24h",
                  energy="high")
    assert _punch_style_for(beat, _resolved("b001", abs_path="/x.png")) == "stat"


def test_punch_style_returns_impacto_for_hook_with_high_energy():
    beat = _beat("b001", 0, 3, ef="hook", hero="The Future",
                  energy="high")
    assert _punch_style_for(beat, _resolved("b001", abs_path="/x.png")) == "impacto"


def test_punch_style_returns_cinematic_for_designed_kicker_or_thesis():
    beat = _beat("b001", 0, 3, ef="value", hero="Build it once",
                  energy="medium")
    r = _resolved("b001", abs_path="/x.png", mockup_kind="kicker")
    assert _punch_style_for(beat, r) == "cinematic"


def test_punch_style_default_is_contexto():
    beat = _beat("b001", 0, 3, ef="value", hero="A short claim")
    assert _punch_style_for(beat, _resolved("b001", abs_path="/x.png")) == "contexto"


# ── build_visual_plan ──────────────────────────────────────────────


def test_visual_plan_emits_presenter_for_beats_without_broll():
    a = _analysis([
        _beat("b001", 0, 3, visual_need="none"),
        _beat("b002", 3, 6, visual_need="required"),
    ])
    plan = build_visual_plan(
        analysis=a, broll_plan={"resolved": [
            {"beat_id": "b002", "hint_index": 0, "abs_path": "/x.png"},
        ]},
        subtitle_clips=_subs([]),
        presenter_video_path="/path/to/presenter.mp4",
        background_path="/path/to/black.png",
    )
    types = [b["type"] for b in plan["beats"]]
    assert types == ["presenter", "broll_image"]
    assert plan["video_path_h264"] == "/path/to/presenter.mp4"


def test_visual_plan_emits_video_beats_with_duration():
    a = _analysis([_beat("b001", 0, 4)])
    plan = build_visual_plan(
        analysis=a, broll_plan={"resolved": [
            {"beat_id": "b001", "hint_index": 0,
             "abs_path": "/x.mp4", "kind": "video",
             "duration_s": 5.0},
        ]},
        subtitle_clips=_subs([]),
        presenter_video_path="/p.mp4", background_path="/bg.png",
    )
    b = plan["beats"][0]
    assert b["type"] == "broll_video"
    assert b["asset_duration_us"] == 5_000_000


def test_visual_plan_promotes_hero_text_to_punch_on_first_hint():
    a = _analysis([
        _beat("b001", 0, 3, ef="hook", hero="20-yr-old built AI",
              energy="high"),
    ])
    plan = build_visual_plan(
        analysis=a, broll_plan={"resolved": [
            {"beat_id": "b001", "hint_index": 0, "abs_path": "/x.png"},
            {"beat_id": "b001", "hint_index": 1, "abs_path": "/y.png"},
        ]},
        subtitle_clips=_subs([]),
        presenter_video_path="/p.mp4", background_path="/bg.png",
    )
    # Both b-roll beats emitted (same window)
    assert sum(1 for b in plan["beats"] if b["type"] == "broll_image") == 2
    # Punch only rides on the first hint to avoid duplicating overlay
    punches = [b.get("punch_text") for b in plan["beats"]]
    assert punches == ["20-yr-old built AI", None]
    # Punch style was inferred from beat metadata (impacto for hook+high)
    first = next(b for b in plan["beats"] if b.get("punch_text"))
    assert first["punch_style"] == "impacto"


def test_visual_plan_includes_music_when_path_provided():
    a = _analysis([_beat("b001", 0, 3, visual_need="none")])
    plan = build_visual_plan(
        analysis=a, broll_plan={"resolved": []},
        subtitle_clips=_subs([]),
        presenter_video_path="/p.mp4", background_path="/bg.png",
        music_path="/music/track.mp3",
    )
    assert plan["music_cue"]["path"] == "/music/track.mp3"
    assert 0.0 <= plan["music_cue"]["volume"] <= 1.0


def test_visual_plan_omits_music_cue_when_no_path():
    a = _analysis([_beat("b001", 0, 3, visual_need="none")])
    plan = build_visual_plan(
        analysis=a, broll_plan={"resolved": []},
        subtitle_clips=_subs([]),
        presenter_video_path="/p.mp4", background_path="/bg.png",
    )
    assert "music_cue" not in plan


def test_visual_plan_subtitle_cues_at_top_level():
    a = _analysis([_beat("b001", 0, 1, visual_need="none")])
    plan = build_visual_plan(
        analysis=a, broll_plan={"resolved": []},
        subtitle_clips=_subs([
            _clip("hola", 0.0, 0.4),
            _clip("mundo", 0.4, 0.9),
        ]),
        presenter_video_path="/p.mp4", background_path="/bg.png",
    )
    assert "subtitle_cues" in plan
    assert plan["subtitle_cues"][0]["words"][0]["text"] == "hola"


def test_visual_plan_passes_through_layout_split():
    a = _analysis([_beat("b001", 0, 3)])
    plan = build_visual_plan(
        analysis=a, broll_plan={"resolved": [
            {"beat_id": "b001", "hint_index": 0,
             "abs_path": "/x.png", "layout": "split_bottom"},
        ]},
        subtitle_clips=_subs([]),
        presenter_video_path="/p.mp4", background_path="/bg.png",
    )
    assert plan["beats"][0]["layout"] == "split_bottom"
