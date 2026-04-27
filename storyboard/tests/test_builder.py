"""Tests for storyboard builder (no real ffmpeg-on-real-video, uses placeholders)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from storyboard.builder import build_storyboard, _kind_from_path
from storyboard.contracts import Storyboard


def _resolved(beat_id, hi, *, abs_path, kind, type_="video", subject="Foo",
              t_start=None, t_end=None, source="anchor_in_inventory"):
    return {
        "beat_id": beat_id, "hint_index": hi,
        "type": type_, "subject": subject, "description": "x",
        "kind": kind, "source": source, "abs_path": abs_path,
        "t_start_s": t_start, "t_end_s": t_end,
        "beat_start_s": 0.0, "beat_end_s": 5.0,
    }


def _make_image(p: Path, w: int = 1080, h: int = 1920, color="#202030"):
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), color).save(p, "JPEG", quality=80)


def test_image_resized_into_thumb(tmp_path: Path):
    img = tmp_path / "src.jpg"; _make_image(img, 1920, 1080)
    plan = {"resolved": [_resolved("b001", 0, abs_path=str(img), kind="image", type_="photo")]}
    sb = build_storyboard(plan, duration_s=10.0, out_dir=tmp_path / "out")
    assert len(sb.entries) == 1
    e = sb.entries[0]
    assert e.kind == "image"
    full = (tmp_path / "out") / e.thumb_path
    assert full.exists()
    with Image.open(full) as im:
        assert im.width <= 640


def test_screenshot_kind_kept(tmp_path: Path):
    img = tmp_path / "shot.png"; _make_image(img.with_suffix(".jpg"), 800, 1200); img.with_suffix(".jpg").rename(img)
    # Workaround Pillow saving JPEG even when extension is .png — re-save as PNG
    Image.open(img).convert("RGB").save(img, "PNG")
    plan = {"resolved": [_resolved("b001", 0, abs_path=str(img),
                                    kind="screenshot", type_="web_capture")]}
    sb = build_storyboard(plan, 10.0, tmp_path / "out")
    assert sb.entries[0].kind == "screenshot"


def test_title_with_no_path_uses_placeholder(tmp_path: Path):
    plan = {"resolved": [{
        "beat_id": "b001", "hint_index": 0,
        "type": "title", "kind": "title",
        "abs_path": None, "source": "title_fallback",
        "subject": "Hero text",
        "description": "Predict the future",
        "beat_start_s": 0.0, "beat_end_s": 5.0,
    }]}
    sb = build_storyboard(plan, 10.0, tmp_path / "out")
    e = sb.entries[0]
    assert e.kind == "title"
    full = (tmp_path / "out") / e.thumb_path
    assert full.exists()


def test_missing_asset_yields_placeholder_kind(tmp_path: Path):
    plan = {"resolved": [_resolved("b001", 0, abs_path=str(tmp_path / "nope.mp4"),
                                    kind="video")]}
    sb = build_storyboard(plan, 10.0, tmp_path / "out")
    assert sb.entries[0].kind == "missing"
    full = (tmp_path / "out") / sb.entries[0].thumb_path
    assert full.exists()


def test_kind_from_path_extension():
    assert _kind_from_path(Path("/x/v.mp4"), None) == "video"
    assert _kind_from_path(Path("/x/p.png"), "screenshot") == "screenshot"
    assert _kind_from_path(Path("/x/p.png"), "title") == "title"
    assert _kind_from_path(Path("/x/p.jpg"), None) == "image"
    assert _kind_from_path(None, "title") == "title"
    assert _kind_from_path(None, "video") == "missing"


def test_hero_text_attached_when_provided(tmp_path: Path):
    img = tmp_path / "src.jpg"; _make_image(img)
    plan = {"resolved": [_resolved("b001", 0, abs_path=str(img), kind="image",
                                    type_="photo")]}
    sb = build_storyboard(
        plan, 10.0, tmp_path / "out",
        hero_text_by_beat={"b001": "MiroFish predicts future"},
    )
    assert sb.entries[0].hero_text == "MiroFish predicts future"
