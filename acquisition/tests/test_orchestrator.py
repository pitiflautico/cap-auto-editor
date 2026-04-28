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


def _patch_hf(monkeypatch, *, ok: bool = True, raise_exc: Exception | None = None):
    """Replace `hf.acquire` so unit tests don't hit the real LLM/CLI.

    When `ok=True` we write a fake mp4 under the slot dir and return the
    tuple shape the orchestrator expects. When `raise_exc` is provided
    the call raises (simulating designer/render failure), which the
    orchestrator must catch to fall back to text_card.
    """
    from acquisition.providers import hf

    def _fake_acquire(hint, slot_dir, *, name="card"):
        if raise_exc is not None:
            raise raise_exc
        slot_dir.mkdir(parents=True, exist_ok=True)
        mp4 = slot_dir / f"{name}.mp4"
        mp4.write_bytes(b"FAKEMP4" + b"\x00" * 4096)
        kind = "slide" if (hint.get("type") == "slide") else "mockup"
        return mp4, "video", 5.0, kind, "fullscreen"

    monkeypatch.setattr(hf, "acquire", _fake_acquire)


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


def test_title_routes_to_hf_designer_with_kicker_or_thesis(tmp_path: Path, monkeypatch):
    """`type=title` is now an animated hero card via hf_designer (mockup
    kind=kicker for ≤3 words, thesis for longer text). PIL text_card
    is reserved as a fallback when the designer fails."""
    _patch_pexels(monkeypatch)        # pexels off — must not be called
    _patch_hf(monkeypatch, ok=True)
    payload = {"pending": [_hint(type_="title", subject="Hero text overlay")]}
    report = acquire(payload, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "hf_mockup"
    assert e.kind == "video"
    # No Pexels attempts at all
    assert all(a.provider != "pexels_image" and a.provider != "pexels_video"
               for a in e.attempts)


def test_title_falls_back_to_text_card_when_hf_fails(tmp_path: Path, monkeypatch):
    """If hf_designer raises, title still degrades cleanly to PIL."""
    _patch_pexels(monkeypatch)
    _patch_hf(monkeypatch, raise_exc=RuntimeError("hyperframes timeout"))
    payload = {"pending": [_hint(type_="title", subject="MiroFish")]}
    report = acquire(payload, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "text_card"
    providers = [a.provider for a in e.attempts]
    assert "hf_mockup" in providers and "text_card" in providers


def test_report_counts(tmp_path: Path, monkeypatch):
    _patch_pexels(monkeypatch, image_ok=True, video_ok=True)
    _patch_hf(monkeypatch, ok=True)
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
    # title now flows through hf_designer (mockup kicker/thesis layout)
    assert report.provider_counts.get("hf_mockup") == 1


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


def test_motion_shot_type_prefers_video_over_image(tmp_path: Path, monkeypatch):
    """A type=pexels hint with shot_type=screen_recording lands on
    Pexels VIDEO, not an image. Source-priority spec: real footage > stock image.
    """
    _patch_pexels(monkeypatch, image_ok=True, video_ok=True)
    h = _hint(type_="pexels", subject="MiroFish",
              query="MiroFish simulation")
    h["shot_type"] = "screen_recording"
    report = acquire({"pending": [h]}, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "pexels_video", e.attempts
    assert e.kind == "video"


def test_static_shot_type_uses_image_directly(tmp_path: Path, monkeypatch):
    """logo_centered / abstract hints (type=pexels) should NOT call
    pexels_video first; a still image is the right choice.
    """
    _patch_pexels(monkeypatch, image_ok=True, video_ok=True)
    h = _hint(type_="pexels", subject="Logo")
    h["shot_type"] = "logo_centered"
    report = acquire({"pending": [h]}, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "pexels_image"
    # Confirm we didn't attempt video search at all
    assert all(a.provider != "pexels_video" for a in e.attempts)


def test_mockup_routes_to_hf_designer(tmp_path: Path, monkeypatch):
    """type=mockup goes through the hf_designer (LLM + HyperFrames)
    cascade. Never touches Pexels even if the shot_type would have
    triggered a video search.
    """
    _patch_pexels(monkeypatch, image_ok=True, video_ok=True)
    _patch_hf(monkeypatch, ok=True)
    h = _hint(type_="mockup", subject="MiroFish UI")
    h["shot_type"] = "screen_recording"
    h["mockup_kind"] = "thesis"
    report = acquire({"pending": [h]}, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "hf_mockup"
    assert e.kind == "video"
    assert e.abs_path and Path(e.abs_path).exists()
    # Only the hf attempt was logged — no Pexels touched.
    assert all(a.provider in ("hf_slide", "hf_mockup") for a in e.attempts)


def test_slide_routes_to_hf_designer(tmp_path: Path, monkeypatch):
    """type=slide → hf_designer slide kind, never Pexels."""
    _patch_pexels(monkeypatch, image_ok=True, video_ok=True)
    _patch_hf(monkeypatch, ok=True)
    h = _hint(type_="slide", subject="Highlights")
    h["slide_kind"] = "list"
    h["queries_fallback"] = ["one", "two", "three"]
    report = acquire({"pending": [h]}, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "hf_slide"
    assert e.kind == "video"


def test_designed_type_falls_back_to_text_card_on_hf_failure(tmp_path: Path, monkeypatch):
    """If the designer/render raises, the orchestrator must catch it
    and degrade to text_card so the slot is never empty.
    """
    _patch_pexels(monkeypatch, image_ok=True, video_ok=True)
    _patch_hf(monkeypatch, raise_exc=RuntimeError("hyperframes timeout"))
    h = _hint(type_="mockup", subject="Foo")
    report = acquire({"pending": [h]}, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "text_card"
    # Both attempts logged: the failed hf one and the successful text_card.
    providers = [a.provider for a in e.attempts]
    assert "hf_mockup" in providers
    assert "text_card" in providers
    # The failed hf attempt carries the error message.
    hf_attempt = next(a for a in e.attempts if a.provider == "hf_mockup")
    assert hf_attempt.success is False
    assert "timeout" in (hf_attempt.error or "")


def test_title_card_subtext_from_description(tmp_path: Path, monkeypatch):
    """A title card now lands on hf_designer (mockup layout). The
    description carries through the brief; PIL text_card stays as a
    fallback only.
    """
    _patch_pexels(monkeypatch)
    _patch_hf(monkeypatch, ok=True)
    h = _hint(type_="title", subject="MiroFish Built in 10 Days",
              description="Open-source predictive simulation engine")
    report = acquire({"pending": [h]}, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "hf_mockup"
    assert e.abs_path and Path(e.abs_path).exists()


def test_query_chain_falls_back_when_primary_returns_none(tmp_path: Path, monkeypatch):
    """If the primary query yields no Pexels match, the orchestrator must
    try queries_fallback before giving up on the API.
    """
    from acquisition.providers import pexels
    seen_queries: list[str] = []

    def fake_search_image(query, out_dir, *, name_prefix="pexels"):
        seen_queries.append(query)
        # Only the third query succeeds
        if query == "stock fallback":
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / "pexels_image_3.jpg"
            p.write_bytes(b"\xff\xd8\xff" + b"\x00" * 8192)
            return p, "https://www.pexels.com/photo/3", {
                "id": 3, "width": 1080, "height": 1920, "photographer": "x",
            }
        return None

    monkeypatch.setattr(pexels, "search_image", fake_search_image)
    monkeypatch.setattr(pexels, "search_video", lambda *a, **kw: None)

    h = _hint(type_="photo", query="too specific query")
    h["queries_fallback"] = ["another miss", "stock fallback"]
    report = acquire({"pending": [h]}, tmp_path)
    e = report.entries[0]
    assert e.final_provider == "pexels_image"
    assert seen_queries == ["too specific query", "another miss", "stock fallback"]


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
