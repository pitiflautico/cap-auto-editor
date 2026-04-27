"""Tests for vision_analyzer with a fake vision_fn (no Claude calls)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from visual_inventory.vision_analyzer import analyze_frame


class _FakeResp:
    def __init__(self, text: str): self.text = text


def _factory(payload: dict | str):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    def fake(image_path, prompt, **kwargs):
        return _FakeResp(text)
    return fake


def test_full_payload_parsed(tmp_path: Path):
    img = tmp_path / "x.jpg"; img.write_text("fake")
    fake = _factory({
        "description": "Logo reveal on dark gradient",
        "shot_type": "logo_centered",
        "has_baked_text": True,
        "free_zones": ["bottom", "top_right"],
        "luminosity": "dark",
        "quality": 5,
        "subjects": ["Gemma 4"],
    })
    k = analyze_frame(img, t_s=12.5, vision_fn=fake)
    assert k.t_s == 12.5
    assert k.shot_type == "logo_centered"
    assert k.has_baked_text is True
    assert k.free_zones == ["bottom", "top_right"]
    assert k.quality == 5
    assert "Gemma 4" in k.subjects


def test_invalid_shot_type_coerced_to_none(tmp_path: Path):
    img = tmp_path / "x.jpg"; img.write_text("fake")
    fake = _factory({"description": "x", "shot_type": "fish-eye", "quality": 3})
    k = analyze_frame(img, t_s=0, vision_fn=fake)
    assert k.shot_type is None


def test_malformed_json_returns_fallback(tmp_path: Path):
    img = tmp_path / "x.jpg"; img.write_text("fake")
    fake = _factory("not json at all")
    k = analyze_frame(img, t_s=0, vision_fn=fake)
    assert k.description == "(vision unavailable)"
    assert k.quality == 3


def test_json_inside_markdown_fence_extracted(tmp_path: Path):
    img = tmp_path / "x.jpg"; img.write_text("fake")
    payload = '```json\n{"description":"a wide shot","shot_type":"wide","quality":4}\n```'
    fake = _factory(payload)
    k = analyze_frame(img, t_s=0, vision_fn=fake)
    assert k.shot_type == "wide"
    assert k.quality == 4


def test_quality_out_of_range_clamped(tmp_path: Path):
    img = tmp_path / "x.jpg"; img.write_text("fake")
    fake = _factory({"description": "x", "shot_type": "wide", "quality": 99})
    k = analyze_frame(img, t_s=0, vision_fn=fake)
    assert 1 <= k.quality <= 5


def test_vision_call_exception_returns_fallback(tmp_path: Path):
    img = tmp_path / "x.jpg"; img.write_text("fake")
    def boom(*a, **kw): raise RuntimeError("LLM down")
    k = analyze_frame(img, t_s=5.0, vision_fn=boom)
    assert k.description == "(vision unavailable)"
    assert k.t_s == 5.0
