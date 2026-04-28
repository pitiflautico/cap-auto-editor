"""Tests for hf_designer.render — no real `npx hyperframes` calls.

We monkeypatch `_run_hyperframes` so the tests stay deterministic and
fast; the public `render_to_mp4` wrapper is what we exercise.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hf_designer import render as render_mod


def _stub_run_hf(monkeypatch, *, ok: bool, write_bytes: bytes | None = None,
                  msg: str = "ok"):
    """Patch `_run_hyperframes` to (optionally) write fake mp4 bytes.

    Returns the patched function so tests can inspect call args.
    """
    captured = {"calls": []}

    def _fake(*, html_content, out_mp4, fps, quality, timeout_s):
        captured["calls"].append({
            "html_content": html_content, "out_mp4": out_mp4,
            "fps": fps, "quality": quality, "timeout_s": timeout_s,
        })
        if write_bytes is not None:
            out_mp4.parent.mkdir(parents=True, exist_ok=True)
            out_mp4.write_bytes(write_bytes)
        return ok, msg

    monkeypatch.setattr(render_mod, "_run_hyperframes", _fake)
    return captured


def _stub_probe_duration(monkeypatch, value: float | None):
    monkeypatch.setattr(render_mod, "_probe_duration", lambda p: value)


def test_render_returns_ok_when_renderer_succeeds(tmp_path: Path, monkeypatch):
    out = tmp_path / "card.mp4"
    captured = _stub_run_hf(monkeypatch, ok=True,
                              write_bytes=b"FAKEMP4" * 256)
    _stub_probe_duration(monkeypatch, 5.5)

    res = render_mod.render_to_mp4(
        "<!doctype html><html></html>", out,
        duration_s=6.0, fps=24, quality="draft",
    )
    assert res["status"] == "ok"
    assert res["asset_path"] == str(out)
    assert res["duration_s"] == 5.5
    assert len(res["sha256"]) == 64
    # CLI args propagated correctly
    call = captured["calls"][0]
    assert call["fps"] == 24
    assert call["quality"] == "draft"


def test_render_falls_back_to_declared_duration_when_ffprobe_unavailable(
    tmp_path: Path, monkeypatch,
):
    out = tmp_path / "card.mp4"
    _stub_run_hf(monkeypatch, ok=True, write_bytes=b"x" * 4096)
    _stub_probe_duration(monkeypatch, None)
    res = render_mod.render_to_mp4("<!doctype html><html></html>", out,
                                     duration_s=3.5)
    assert res["status"] == "ok"
    assert res["duration_s"] == 3.5


def test_render_returns_failed_when_renderer_errors(tmp_path: Path, monkeypatch):
    out = tmp_path / "card.mp4"
    _stub_run_hf(monkeypatch, ok=False, msg="hyperframes exit=1: boom")
    res = render_mod.render_to_mp4("<!doctype html><html></html>", out)
    assert res["status"] == "failed"
    assert "boom" in res["message"]


def test_render_creates_parent_dir(tmp_path: Path, monkeypatch):
    out = tmp_path / "deep" / "nested" / "card.mp4"
    _stub_run_hf(monkeypatch, ok=True, write_bytes=b"x" * 4096)
    _stub_probe_duration(monkeypatch, 4.0)
    render_mod.render_to_mp4("<!doctype html><html></html>", out)
    assert out.parent.exists()


def test_sha256_of_matches_known_input(tmp_path: Path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    # sha256("abc") = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
    assert render_mod._sha256_of(p) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
