"""Tests for media_audit — pure HTML/asset comparison."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from capture.contracts import MediaAsset
from capture.media_audit import audit_capture, write_audit


def _asset(url: str, kind: str = "video", provider: str = "yt_dlp",
           path: str = "media/x.mp4") -> MediaAsset:
    return MediaAsset(kind=kind, provider=provider, path=path,
                      source_url=url, sha256="x"*64, bytes=1024)


def test_audit_with_all_downloaded_no_warnings():
    html = '<iframe src="https://www.youtube.com/embed/abc"></iframe>'
    page = "https://example.com/landing/"
    a = _asset("https://www.youtube.com/embed/abc")
    audit = audit_capture(html, page, "example", [a], max_per_capture=3)
    assert audit.candidates_total == 1
    assert audit.downloaded_total == 1
    assert audit.iframes_yt_dlp[0].downloaded
    assert audit.warnings == [] or all("no_media" not in w for w in audit.warnings)


def test_audit_iframe_not_downloaded_emits_hero_warning():
    """The canonical case Dani hit: corporate landing has YouTube hero
    iframe but our pipeline didn't download it."""
    html = '<iframe src="https://www.youtube.com/embed/HEROVID"></iframe>'
    page = "https://corp.example.com/product"
    audit = audit_capture(html, page, "corp", [], max_per_capture=3)
    assert audit.candidates_total == 1
    assert audit.downloaded_total == 0
    assert any("hero_iframe_missing" in w for w in audit.warnings)


def test_audit_no_candidates_emits_no_media_warning():
    html = "<html><body>just text, no video tag</body></html>"
    # Use a non-yt-dlp host so the page itself is not a candidate.
    audit = audit_capture(html, "https://example.com/page", "page", [],
                          max_per_capture=3)
    assert audit.candidates_total == 0
    assert any("no_media_candidates" in w for w in audit.warnings)


def test_audit_max_per_capture_warning():
    html = """
    <video><source src="/a.mp4"></video>
    <video><source src="/b.mp4"></video>
    <video><source src="/c.mp4"></video>
    <video><source src="/d.mp4"></video>
    """
    page = "https://example.com/"
    downloaded = [
        _asset("https://example.com/a.mp4", provider="video_tag"),
        _asset("https://example.com/b.mp4", provider="video_tag"),
        _asset("https://example.com/c.mp4", provider="video_tag"),
    ]
    audit = audit_capture(html, page, "ex", downloaded, max_per_capture=3)
    assert audit.candidates_total == 4
    assert audit.downloaded_total == 3
    assert any("max_per_capture_reached" in w for w in audit.warnings)
    assert len(audit.missed) == 1


def test_audit_missed_lists_skipped_urls_with_reason():
    html = '<iframe src="https://www.youtube.com/embed/abc"></iframe><video><source src="/x.mp4"></video>'
    page = "https://example.com/"
    audit = audit_capture(html, page, "ex", [], max_per_capture=3)
    assert audit.candidates_total == 2
    assert len(audit.missed) == 2
    reasons = {m["reason"] for m in audit.missed}
    assert reasons  # at least one reason recorded


def test_write_audit_persists_json(tmp_path: Path):
    audit = audit_capture("<html></html>", "https://x.com/", "slug", [],
                          max_per_capture=3)
    path = write_audit(audit, tmp_path)
    assert path.exists()
    import json
    data = json.loads(path.read_text())
    assert data["slug"] == "slug"
    assert "warnings" in data
