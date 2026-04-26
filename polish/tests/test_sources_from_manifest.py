"""Unit tests for sources.load_from_capture_manifest."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from polish.sources import load_from_capture_manifest


def _write_manifest(tmp_path: Path, results: list[dict]) -> Path:
    out_dir = tmp_path / "captures_out"
    out_dir.mkdir()
    manifest = {
        "out_dir": str(out_dir),
        "results": results,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _write_text(tmp_path: Path, manifest_path: Path, slug: str, content: str) -> None:
    manifest = json.loads(manifest_path.read_text())
    out_dir = Path(manifest["out_dir"])
    capture_dir = out_dir / "captures" / slug
    capture_dir.mkdir(parents=True, exist_ok=True)
    (capture_dir / "text.txt").write_text(content, encoding="utf-8")


# ── helpers ────────────────────────────────────────────────────────────────

def _make_ok_result(url: str, slug: str, has_text: bool = True) -> dict:
    return {
        "request": {"url": url, "slug": slug},
        "status": "ok",
        "artifacts": {"text_path": "text.txt" if has_text else None},
    }


def _make_failed_result(url: str, slug: str) -> dict:
    return {
        "request": {"url": url, "slug": slug},
        "status": "error",
        "artifacts": {"text_path": None},
    }


# ── tests ──────────────────────────────────────────────────────────────────

def test_ok_url_returns_title_from_first_line(tmp_path):
    manifest_path = _write_manifest(tmp_path, [
        _make_ok_result("https://example.com/page", "example-com-page"),
    ])
    _write_text(tmp_path, manifest_path, "example-com-page",
                "My Great Title\nSome body text here.\nMore text.")
    metas = load_from_capture_manifest(manifest_path)

    assert len(metas) == 1
    m = metas[0]
    assert m.ok is True
    assert m.url == "https://example.com/page"
    assert m.title == "My Great Title"
    assert m.description is not None
    assert "Some body text" in m.description


def test_failed_urls_are_skipped(tmp_path):
    manifest_path = _write_manifest(tmp_path, [
        _make_ok_result("https://ok.com/", "ok-com"),
        _make_failed_result("https://bad.com/", "bad-com"),
    ])
    _write_text(tmp_path, manifest_path, "ok-com", "Title\nBody.")
    metas = load_from_capture_manifest(manifest_path)

    urls = [m.url for m in metas]
    assert "https://ok.com/" in urls
    assert "https://bad.com/" not in urls


def test_description_within_max_chars(tmp_path):
    long_body = "A" * 5000
    manifest_path = _write_manifest(tmp_path, [
        _make_ok_result("https://long.com/", "long-com"),
    ])
    _write_text(tmp_path, manifest_path, "long-com", f"Title Line\n{long_body}")
    metas = load_from_capture_manifest(manifest_path, max_chars_per_text=500)

    m = metas[0]
    # title + description together must not exceed max_chars_per_text
    combined = (m.title or "") + (m.description or "")
    assert len(combined) <= 500


def test_original_order_preserved(tmp_path):
    results = [
        _make_ok_result("https://first.com/", "first-com"),
        _make_ok_result("https://second.com/", "second-com", has_text=False),
        _make_ok_result("https://third.com/", "third-com"),
    ]
    manifest_path = _write_manifest(tmp_path, results)
    _write_text(tmp_path, manifest_path, "first-com", "First Title\nFirst body.")
    _write_text(tmp_path, manifest_path, "third-com", "Third Title\nThird body.")

    metas = load_from_capture_manifest(manifest_path)

    assert len(metas) == 3
    assert metas[0].url == "https://first.com/"
    assert metas[1].url == "https://second.com/"
    assert metas[2].url == "https://third.com/"


def test_image_only_result_has_null_title(tmp_path):
    manifest_path = _write_manifest(tmp_path, [
        _make_ok_result("https://img.com/pic.png", "img-com-pic-png", has_text=False),
    ])
    metas = load_from_capture_manifest(manifest_path)

    assert len(metas) == 1
    m = metas[0]
    assert m.ok is True
    assert m.title is None
    assert m.description is None
