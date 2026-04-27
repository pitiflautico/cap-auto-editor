"""Tests for media_downloader. yt-dlp paths are skipped if binary missing."""
from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest

from capture.extractors.media import MediaCandidate
from capture.media_downloader import (
    DownloadContext,
    download_candidates,
)


class _FakeResp:
    def __init__(self, status_code: int, payload: bytes):
        self.status_code = status_code
        self._payload = payload
    def iter_bytes(self, chunk_size: int = 65536):
        for i in range(0, len(self._payload), chunk_size):
            yield self._payload[i:i+chunk_size]
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _patch_httpx_stream(monkeypatch, payloads: dict[str, bytes]):
    import httpx
    def fake_stream(method, url, **kw):
        if url not in payloads:
            return _FakeResp(404, b"")
        return _FakeResp(200, payloads[url])
    monkeypatch.setattr(httpx, "stream", fake_stream)


def test_http_direct_video_persisted_with_sha256(tmp_path: Path, monkeypatch):
    body = b"FAKE_MP4_HEADER" + b"\x00" * 4096
    _patch_httpx_stream(monkeypatch, {"https://cdn.example.com/clip.mp4": body})
    cand = MediaCandidate(url="https://cdn.example.com/clip.mp4",
                          kind="video", provider="og_video")
    assets = download_candidates([cand], DownloadContext(out_dir=tmp_path))
    assert len(assets) == 1
    a = assets[0]
    assert a.kind == "video"
    assert a.provider == "og_video"
    assert a.path.endswith(".mp4")
    full = tmp_path / a.path
    assert full.exists() and full.stat().st_size == len(body)
    assert a.sha256 and len(a.sha256) == 64
    assert a.bytes == len(body)


def test_too_small_response_rejected(tmp_path: Path, monkeypatch):
    _patch_httpx_stream(monkeypatch,
                        {"https://cdn.example.com/tiny.mp4": b"abc"})
    cand = MediaCandidate(url="https://cdn.example.com/tiny.mp4",
                          kind="video", provider="og_video")
    assets = download_candidates([cand], DownloadContext(out_dir=tmp_path))
    assert assets == []


def test_404_returns_no_asset(tmp_path: Path, monkeypatch):
    _patch_httpx_stream(monkeypatch, {})  # nothing matches → 404
    cand = MediaCandidate(url="https://cdn.example.com/missing.mp4",
                          kind="video", provider="og_video")
    assets = download_candidates([cand], DownloadContext(out_dir=tmp_path))
    assert assets == []


def test_max_per_capture_caps_downloads(tmp_path: Path, monkeypatch):
    payloads = {
        f"https://cdn.example.com/c{i}.mp4": b"X" * 4096
        for i in range(5)
    }
    _patch_httpx_stream(monkeypatch, payloads)
    cands = [
        MediaCandidate(url=u, kind="video", provider="og_video")
        for u in payloads
    ]
    assets = download_candidates(cands, DownloadContext(out_dir=tmp_path),
                                 max_per_capture=2)
    assert len(assets) == 2


def test_yt_dlp_provider_skipped_if_binary_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    cand = MediaCandidate(url="https://www.youtube.com/watch?v=zz",
                          kind="video", provider="yt_dlp")
    assets = download_candidates([cand], DownloadContext(out_dir=tmp_path))
    assert assets == []


def test_og_image_extension_inferred(tmp_path: Path, monkeypatch):
    body = b"\xff\xd8\xff" + b"\x00" * 8192   # JPEG SOI
    _patch_httpx_stream(monkeypatch,
                        {"https://cdn.example.com/cover": body})
    cand = MediaCandidate(url="https://cdn.example.com/cover",
                          kind="og_image", provider="og_image")
    assets = download_candidates([cand], DownloadContext(out_dir=tmp_path))
    assert len(assets) == 1
    a = assets[0]
    assert a.kind == "og_image"
    assert a.path.endswith(".jpg")  # default for og_image when no ext
