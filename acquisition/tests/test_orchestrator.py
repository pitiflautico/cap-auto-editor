"""Tests for acquisition orchestrator (no real Pexels calls — use monkeypatched provider stubs)."""
from __future__ import annotations

from pathlib import Path
import json
import pytest

from acquisition.orchestrator import acquire, _query_for, _fallback_text


# ── Helpers ────────────────────────────────────────────────────────

def _hint(type_="video", subject="Foo", query="Foo demo",
          description="", beat_id="b001", hi=0):
    return {
        "beat_id": beat_id, "hint_index": hi, "type": type_,
        "subject": subject, "query": query,
        "queries_fallback": [], "shot_type": None,
        "duration_target_s": 4.0,
        "description": description, "editorial_function": "solution",
        "beat_start_s": 0.0, "beat_end_s": 5.0,
        "reason": "no local material",
    }


def _patch_pexels(monkeypatch, *, image_ok=False, video_ok=False):
    from acquisition.providers import pexels

    def fake_search_image(query, out_dir, *, name_prefix="pexels"):
        if not image_ok:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "pexels_image_99.jpg"
        p.write_bytes(b"\xff\xd8\xff" + b"\x00" * 8192)
        return p, "https://www.pexels.com/photo/99", {
            "id": 99, "width": 1080, "height": 1920,
            "photographer": "x",
        }

    def fake_search_video(query, out_dir, *, name_prefix="pexels",
                          min_duration_s=2, max_duration_s=30):
        if not video_ok:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "pexels_video_42.mp4"
        p.write_bytes(b"FAKEMP4" + b"\x00" * 8192)
        return p, "https://www.pexels.com/video/42", {
            "id": 42, "duration_s": 5.0, "width": 1080, "height": 1920,
        }

    monkeypatch.setattr(pexels, "search_image", fake_search_image)
    monkeypatch.setattr(pexels, "search_video", fake_search_video)


# ── Cascade behaviour ─────────────────────────────────────────────

def test_video_pexels_first(tmp_path: Path, monkeypatch):
    _patch_pexels(monkeypatch, video_ok=True)
    payload = {"pending": [_hint(type_="video")]}
    report = acquire(payload, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "pexels_video"
    assert e.kind == "video"
    assert e.abs_path and Path(e.abs_path).exists()
    # First attempt was Pexels and succeeded — no text_card fallback
    assert all(a.provider != "text_card" for a in e.attempts)


def test_video_falls_back_to_text_card_when_pexels_empty(tmp_path: Path, monkeypatch):
    _patch_pexels(monkeypatch, video_ok=False)
    payload = {"pending": [_hint(type_="video")]}
    report = acquire(payload, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "text_card"
    # text_card always returns a path (PNG or MP4)
    assert e.abs_path and Path(e.abs_path).exists()
    assert report.text_card_fallback == 1


def test_photo_uses_pexels_image_then_text_card(tmp_path: Path, monkeypatch):
    _patch_pexels(monkeypatch, image_ok=True)
    payload = {"pending": [_hint(type_="photo")]}
    report = acquire(payload, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "pexels_image"
    assert e.kind == "image"


def test_title_goes_directly_to_text_card(tmp_path: Path, monkeypatch):
    _patch_pexels(monkeypatch)        # both off — should not be called
    payload = {"pending": [_hint(type_="title", subject="Hero text")]}
    report = acquire(payload, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "text_card"
    assert e.kind in ("title", "video")
    # No pexels attempts
    assert all(a.provider == "text_card" for a in e.attempts)


def test_report_counts(tmp_path: Path, monkeypatch):
    _patch_pexels(monkeypatch, image_ok=True, video_ok=True)
    payload = {"pending": [
        _hint(type_="video", beat_id="b001", hi=0),
        _hint(type_="photo", beat_id="b002", hi=0),
        _hint(type_="title", beat_id="b003", hi=0),
    ]}
    report = acquire(payload, tmp_path)
    assert report.pending_total == 3
    assert report.acquired_count == 3
    assert report.provider_counts.get("pexels_video") == 1
    assert report.provider_counts.get("pexels_image") == 1
    assert report.provider_counts.get("text_card") == 1


def test_query_composition_priorities():
    h = _hint(query="primary", subject="ignored")
    assert _query_for(h) == "primary"
    h["query"] = ""
    assert _query_for(h) == "ignored"      # fall to subject
    h["subject"] = ""
    h["description"] = "desc"
    assert _query_for(h) == "desc"
    h["description"] = ""
    assert _query_for(h) == "abstract"


def test_fallback_text_uses_subject_first():
    h = _hint(subject="MiroFish", description="some long description text")
    assert _fallback_text(h) == "MiroFish"
    h["subject"] = ""
    assert _fallback_text(h).startswith("some long")


def test_pexels_api_error_bumps_counter(tmp_path: Path, monkeypatch):
    """When Pexels raises a non-no_match error we count it as api_errors."""
    from acquisition.providers import pexels

    def boom(*a, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(pexels, "search_video", boom)
    monkeypatch.setattr(pexels, "search_image", boom)

    payload = {"pending": [_hint(type_="video")]}
    report = acquire(payload, tmp_path)
    e = report.entries[0]
    # Pexels failed with exception → text_card fallback, but api_errors > 0
    assert e.final_provider == "text_card"
    assert report.api_errors >= 1
