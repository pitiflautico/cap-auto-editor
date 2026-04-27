"""Tests for capture/extractors/media.detect_media — pure HTML parsing."""
from __future__ import annotations

from capture.extractors.media import detect_media


def test_youtube_page_yields_yt_dlp_candidate():
    html = "<html><head><title>x</title></head><body></body></html>"
    cands = detect_media(html, "https://www.youtube.com/watch?v=abc123")
    assert len(cands) == 1
    assert cands[0].provider == "yt_dlp"
    assert cands[0].kind == "video"
    assert cands[0].url == "https://www.youtube.com/watch?v=abc123"


def test_x_status_url_yields_yt_dlp_candidate():
    cands = detect_media("<html></html>", "https://x.com/user/status/12345")
    assert any(c.provider == "yt_dlp" for c in cands)


def test_og_video_meta_detected():
    html = """
    <html><head>
      <meta property="og:video:secure_url" content="https://cdn.example.com/clip.mp4">
    </head><body></body></html>
    """
    cands = detect_media(html, "https://example.com/article")
    assert any(c.provider == "og_video" and c.url.endswith(".mp4") for c in cands)


def test_video_tag_with_source_detected():
    html = """
    <html><body>
      <video poster="poster.jpg">
        <source src="/static/clip.webm" type="video/webm">
        <source src="/static/clip.mp4" type="video/mp4">
      </video>
    </body></html>
    """
    cands = detect_media(html, "https://example.com/page")
    urls = {c.url for c in cands if c.provider == "video_tag"}
    assert "https://example.com/static/clip.mp4" in urls
    assert "https://example.com/static/clip.webm" in urls


def test_og_image_emitted_when_size_unknown():
    html = """<meta property="og:image" content="https://cdn.example.com/cover.jpg">"""
    cands = detect_media(html, "https://example.com/")
    assert any(c.kind == "og_image" for c in cands)


def test_og_image_skipped_when_too_small():
    html = """
    <meta property="og:image" content="https://cdn.example.com/thumb.jpg">
    <meta property="og:image:width" content="200">
    <meta property="og:image:height" content="200">
    """
    cands = detect_media(html, "https://example.com/")
    assert all(c.kind != "og_image" for c in cands)


def test_og_image_kept_when_large():
    html = """
    <meta property="og:image" content="https://cdn.example.com/hero.jpg">
    <meta property="og:image:width" content="1920">
    <meta property="og:image:height" content="1080">
    """
    cands = detect_media(html, "https://example.com/")
    og = [c for c in cands if c.kind == "og_image"]
    assert len(og) == 1
    assert og[0].width == 1920 and og[0].height == 1080


def test_dedupe_same_url():
    html = """
    <meta property="og:video" content="https://cdn.example.com/clip.mp4">
    <video><source src="https://cdn.example.com/clip.mp4" type="video/mp4"></video>
    """
    cands = detect_media(html, "https://example.com/")
    urls = [c.url for c in cands if c.url.endswith("clip.mp4")]
    assert len(urls) == 1, f"expected dedup, got {urls!r}"


def test_no_media_yields_empty_list():
    html = "<html><head><title>nothing</title></head><body><p>just text</p></body></html>"
    cands = detect_media(html, "https://example.com/")
    assert cands == []


def test_priority_order_og_before_tag_on_non_ytdlp_host():
    html = """
    <video><source src="/clip.mp4" type="video/mp4"></video>
    <meta property="og:video" content="https://cdn.example.com/og.mp4">
    """
    cands = detect_media(html, "https://example.com/article")
    providers = [c.provider for c in cands]
    assert "og_video" in providers
    assert "video_tag" in providers
    assert providers.index("og_video") < providers.index("video_tag")


def test_youtube_iframe_embed_extracted_as_yt_dlp():
    """Corporate landings put the hero video in a YouTube iframe.
    Detector must lift the embed URL and mark it for yt-dlp download."""
    html = """
    <html><body>
      <iframe allow="autoplay" src="https://www.youtube.com/embed/jZVBoFOJK-Q?enablejsapi=1&amp;rel=0"></iframe>
    </body></html>
    """
    cands = detect_media(html, "https://deepmind.google/models/gemma/gemma-4/")
    yt = [c for c in cands if c.provider == "yt_dlp"]
    assert len(yt) == 1
    # Query string is stripped — yt-dlp gets a clean canonical URL
    assert yt[0].url == "https://www.youtube.com/embed/jZVBoFOJK-Q"


def test_iframe_to_non_ytdlp_host_ignored():
    """Iframes to random hosts (analytics, ads) are not media."""
    html = '<iframe src="https://analytics.example.com/track"></iframe>'
    cands = detect_media(html, "https://example.com/")
    assert all(c.provider != "yt_dlp" for c in cands)


def test_og_video_pointing_to_youtube_becomes_yt_dlp():
    html = """<meta property="og:video" content="https://www.youtube.com/embed/abc">"""
    cands = detect_media(html, "https://example.com/article")
    assert len(cands) == 1
    assert cands[0].provider == "yt_dlp"


def test_relative_urls_resolved_against_base():
    html = '<meta property="og:video" content="/static/clip.mp4">'
    cands = detect_media(html, "https://example.com/articles/foo/")
    assert any(c.url == "https://example.com/static/clip.mp4" for c in cands)
