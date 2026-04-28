"""Tests for compositor.builder — pure-data transform, no I/O."""
from __future__ import annotations

from pathlib import Path

from compositor_hf.builder import (
    _broll_window,
    _classify_asset,
    beat_windows_from_analysis,
    build_plan,
    stage_assets,
)
from compositor_hf.contracts import CompositionPlan


def _broll_plan(resolved):
    return {"resolved": resolved}


def _resolved(beat_id, *, abs_path, beat_start_s=0.0, beat_end_s=5.0,
               in_pct=0.0, out_pct=1.0, layout="fullscreen", hint_index=0):
    return {
        "beat_id": beat_id,
        "hint_index": hint_index,
        "abs_path": abs_path,
        "beat_start_s": beat_start_s,
        "beat_end_s": beat_end_s,
        "timing": {"in_pct": in_pct, "out_pct": out_pct},
        "layout": layout,
    }


def _subs(clips):
    return {"clips": clips}


def _clip(text, start_s, end_s):
    return {"text": text, "start_s": start_s, "end_s": end_s}


# ── _classify_asset ────────────────────────────────────────────────


def test_classify_asset_video_extensions():
    assert _classify_asset("/x/y.mp4") == "video"
    assert _classify_asset("/x/y.webm") == "video"
    assert _classify_asset("/x/y.MOV") == "video"


def test_classify_asset_image_extensions():
    assert _classify_asset("/x/logo.png") == "image"
    assert _classify_asset("/x/photo.JPG") == "image"


def test_classify_asset_unknown_falls_back_to_image():
    """Better to render a static image than crash on a weird extension."""
    assert _classify_asset("/x/strange.bin") == "image"


# ── _broll_window ──────────────────────────────────────────────────


def test_broll_window_default_full_beat():
    s, e = _broll_window(10.0, 14.0, 0.0, 1.0, fallback_min_dur_s=0.6)
    assert (s, e) == (10.0, 14.0)


def test_broll_window_punchline_reveal_starts_mid_beat():
    s, e = _broll_window(0.0, 10.0, 0.5, 1.0, fallback_min_dur_s=0.6)
    assert s == 5.0 and e == 10.0


def test_broll_window_zero_duration_extended_to_floor():
    """LLM occasionally emits in_pct == out_pct → window of 0s. We
    extend to fallback_min_dur_s, capped by the beat end."""
    s, e = _broll_window(0.0, 10.0, 0.5, 0.5, fallback_min_dur_s=0.8)
    assert s == 5.0 and e == 5.8


def test_broll_window_clamps_pct_outside_unit_range():
    s, e = _broll_window(0.0, 4.0, -0.5, 1.5, fallback_min_dur_s=0.6)
    assert (s, e) == (0.0, 4.0)


# ── beat_windows_from_analysis ─────────────────────────────────────


def test_beat_windows_from_analysis_extracts_each_beat():
    analysis = {"narrative": {"beats": [
        {"beat_id": "b001", "start_s": 0.0, "end_s": 3.0},
        {"beat_id": "b002", "start_s": 3.0, "end_s": 7.5},
    ]}}
    out = beat_windows_from_analysis(analysis)
    assert out["b001"] == (0.0, 3.0)
    assert out["b002"] == (3.0, 7.5)


def test_beat_windows_handles_missing_narrative():
    assert beat_windows_from_analysis({}) == {}
    assert beat_windows_from_analysis({"narrative": {}}) == {}


# ── build_plan ─────────────────────────────────────────────────────


def test_build_plan_emits_one_layer_per_resolved_broll(tmp_path: Path):
    abs_a = tmp_path / "a.mp4"; abs_a.write_bytes(b"\x00" * 16)
    abs_b = tmp_path / "b.png"; abs_b.write_bytes(b"\x89PNG")
    plan = build_plan(
        broll_plan=_broll_plan([
            _resolved("b001", abs_path=str(abs_a), beat_start_s=0, beat_end_s=3),
            _resolved("b002", abs_path=str(abs_b), beat_start_s=3, beat_end_s=6),
        ]),
        subtitle_clips=_subs([]),
        duration_s=6.0,
        beat_window_by_id={
            "b001": (0.0, 3.0),
            "b002": (3.0, 6.0),
        },
        project_root=tmp_path,
    )
    broll_layers = [l for l in plan.layers if l.kind == "broll"]
    assert len(broll_layers) == 2
    assert broll_layers[0].asset_kind == "video"
    assert broll_layers[1].asset_kind == "image"
    assert broll_layers[0].asset_rel == "a.mp4"   # relative to project_root


def test_build_plan_emits_one_layer_per_subtitle(tmp_path: Path):
    plan = build_plan(
        broll_plan=_broll_plan([]),
        subtitle_clips=_subs([
            _clip("hola", 0.0, 0.4),
            _clip("mundo", 0.4, 0.9),
        ]),
        duration_s=1.0,
        beat_window_by_id={},
        project_root=tmp_path,
    )
    sub_layers = [l for l in plan.layers if l.kind == "subtitle"]
    assert [l.text for l in sub_layers] == ["hola", "mundo"]
    assert sub_layers[0].start_s == 0.0
    assert sub_layers[0].end_s == 0.4


def test_build_plan_skips_broll_without_abs_path(tmp_path: Path):
    plan = build_plan(
        broll_plan=_broll_plan([
            {"beat_id": "b001", "abs_path": None, "beat_start_s": 0,
             "beat_end_s": 3, "timing": {"in_pct": 0.0, "out_pct": 1.0}},
        ]),
        subtitle_clips=_subs([]),
        duration_s=3.0,
        beat_window_by_id={"b001": (0.0, 3.0)},
        project_root=tmp_path,
    )
    assert [l for l in plan.layers if l.kind == "broll"] == []
    assert any("no abs_path" in n for n in plan.notes)


def test_build_plan_picks_up_audio_wav_in_project_root(tmp_path: Path):
    (tmp_path / "audio.wav").write_bytes(b"RIFF")
    plan = build_plan(
        broll_plan=_broll_plan([]), subtitle_clips=_subs([]),
        duration_s=5.0, beat_window_by_id={}, project_root=tmp_path,
    )
    assert plan.audio_rel == "audio.wav"
    assert "no audio.wav" not in " ".join(plan.notes)


def test_build_plan_notes_missing_audio(tmp_path: Path):
    plan = build_plan(
        broll_plan=_broll_plan([]), subtitle_clips=_subs([]),
        duration_s=5.0, beat_window_by_id={}, project_root=tmp_path,
    )
    assert plan.audio_rel is None
    assert any("no audio.wav" in n for n in plan.notes)


def test_build_plan_uses_explicit_audio_path_inside_project_root(tmp_path: Path):
    """An explicit audio path inside project_root resolves relative."""
    extra = tmp_path / "elsewhere"; extra.mkdir()
    audio = extra / "voice.wav"; audio.write_bytes(b"RIFF")
    plan = build_plan(
        broll_plan=_broll_plan([]), subtitle_clips=_subs([]),
        duration_s=5.0, beat_window_by_id={}, project_root=tmp_path,
        audio_abs_path=audio,
    )
    assert plan.audio_rel == "elsewhere/voice.wav"


def test_build_plan_uses_explicit_audio_path_outside_project_root(tmp_path: Path):
    """An explicit audio path OUTSIDE project_root falls back to file:// URL."""
    other = tmp_path.parent / "outside_root"; other.mkdir(exist_ok=True)
    audio = other / "voice.wav"; audio.write_bytes(b"RIFF")
    plan = build_plan(
        broll_plan=_broll_plan([]), subtitle_clips=_subs([]),
        duration_s=5.0, beat_window_by_id={}, project_root=tmp_path,
        audio_abs_path=audio,
    )
    assert plan.audio_rel and plan.audio_rel.startswith("file://")


def test_build_plan_clamps_window_to_min_floor(tmp_path: Path):
    """A hint with in_pct == out_pct = 0.5 used to produce zero-duration
    layers that GSAP can't reveal cleanly. Builder enforces a floor."""
    abs_a = tmp_path / "a.png"; abs_a.write_bytes(b"\x89PNG")
    plan = build_plan(
        broll_plan=_broll_plan([
            _resolved("b001", abs_path=str(abs_a),
                       beat_start_s=0, beat_end_s=10,
                       in_pct=0.5, out_pct=0.5),
        ]),
        subtitle_clips=_subs([]),
        duration_s=10.0,
        beat_window_by_id={"b001": (0.0, 10.0)},
        project_root=tmp_path,
        min_broll_window_s=0.7,
    )
    layer = next(l for l in plan.layers if l.kind == "broll")
    assert (layer.end_s - layer.start_s) >= 0.7


# ── stage_assets ───────────────────────────────────────────────────


def test_stage_assets_creates_symlinks_under_project_assets(tmp_path: Path):
    """Each resolved abs_path becomes a symlink at <project>/assets/<beat>_<idx>.<ext>
    so HyperFrames sees it as a same-origin file. The plan returned has
    abs_path rewritten to the staged location."""
    src_dir = tmp_path.parent / "external_src"; src_dir.mkdir(exist_ok=True)
    src_a = src_dir / "x.mp4"; src_a.write_bytes(b"FAKE_MP4")
    src_b = src_dir / "logo.png"; src_b.write_bytes(b"\x89PNG")
    proj = tmp_path / "compositor"; proj.mkdir()

    plan = {"resolved": [
        {"beat_id": "b001", "hint_index": 0, "abs_path": str(src_a)},
        {"beat_id": "b002", "hint_index": 1, "abs_path": str(src_b)},
    ]}
    new_plan, audio = stage_assets(broll_plan=plan, audio_abs_path=None,
                                     project_root=proj)
    assets = proj / "assets"
    assert (assets / "b001_0.mp4").exists()
    assert (assets / "b002_1.png").exists()
    assert new_plan["resolved"][0]["abs_path"].endswith("/assets/b001_0.mp4")
    assert new_plan["resolved"][1]["abs_path"].endswith("/assets/b002_1.png")
    assert audio is None


def test_stage_assets_dedups_when_same_beat_hint_index_collides(tmp_path: Path):
    """Two resolved entries with identical (beat_id, hint_index) must
    not overwrite each other's symlink."""
    src_dir = tmp_path.parent / "ext2"; src_dir.mkdir(exist_ok=True)
    a = src_dir / "x.mp4"; a.write_bytes(b"a")
    b = src_dir / "y.mp4"; b.write_bytes(b"b")
    proj = tmp_path / "compositor"; proj.mkdir()
    plan = {"resolved": [
        {"beat_id": "b001", "hint_index": 0, "abs_path": str(a)},
        {"beat_id": "b001", "hint_index": 0, "abs_path": str(b)},
    ]}
    new_plan, _ = stage_assets(broll_plan=plan, audio_abs_path=None,
                                 project_root=proj)
    p0 = Path(new_plan["resolved"][0]["abs_path"]).name
    p1 = Path(new_plan["resolved"][1]["abs_path"]).name
    assert p0 != p1


def test_stage_assets_stages_audio_too(tmp_path: Path):
    src_dir = tmp_path.parent / "ext3"; src_dir.mkdir(exist_ok=True)
    audio = src_dir / "voice.wav"; audio.write_bytes(b"RIFF")
    proj = tmp_path / "compositor"; proj.mkdir()
    _, staged = stage_assets(broll_plan={"resolved": []},
                              audio_abs_path=audio, project_root=proj)
    assert staged is not None
    assert staged.name == "audio.wav"
    assert staged.parent == proj / "assets"


def test_stage_assets_skips_missing_source(tmp_path: Path):
    """If abs_path doesn't exist, leave the entry untouched — the
    builder will emit a `no abs_path` note further on rather than
    crash inside stage_assets."""
    proj = tmp_path / "compositor"; proj.mkdir()
    plan = {"resolved": [
        {"beat_id": "b001", "hint_index": 0,
         "abs_path": "/nonexistent/path.mp4"},
    ]}
    new_plan, _ = stage_assets(broll_plan=plan, audio_abs_path=None,
                                 project_root=proj)
    assert new_plan["resolved"][0]["abs_path"] == "/nonexistent/path.mp4"
