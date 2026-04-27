"""Tests for URL → handle extractor (pure, no I/O)."""
from __future__ import annotations

import pytest

from entity_enricher.url_extractor import (
    extract_from_url,
    extract_handles_from_sources,
)


# ── X / Twitter ────────────────────────────────────────────────────

@pytest.mark.parametrize("url,handle", [
    ("https://x.com/googleai", "@googleai"),
    ("https://twitter.com/openai", "@openai"),
    ("https://www.x.com/user/status/123", "@user"),
    ("https://mobile.twitter.com/foo", "@foo"),
])
def test_x_handles(url, handle):
    r = extract_from_url(url)
    assert r is not None
    assert r[0] == "x"
    assert r[1] == handle


@pytest.mark.parametrize("url", [
    "https://x.com/home",
    "https://x.com/i/lists/123",
    "https://x.com/search?q=foo",
    "https://x.com/",
    "https://x.com/hashtag/AI",
])
def test_x_reserved_paths_rejected(url):
    assert extract_from_url(url) is None


# ── Reddit ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("https://reddit.com/r/Bard", ("reddit", "r/Bard")),
    ("https://www.reddit.com/r/LocalLLaMA/top/", ("reddit", "r/LocalLLaMA")),
    ("https://reddit.com/u/spez", ("reddit", "u/spez")),
    ("https://reddit.com/user/balajibal", ("reddit", "u/balajibal")),
])
def test_reddit_handles(url, expected):
    r = extract_from_url(url)
    assert r is not None
    assert r[0] == expected[0]
    assert r[1] == expected[1]


def test_reddit_rejects_search():
    assert extract_from_url("https://reddit.com/search?q=foo") is None


# ── YouTube ────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,handle", [
    ("https://youtube.com/@google", "@google"),
    ("https://www.youtube.com/@GoogleDeepMind/videos", "@GoogleDeepMind"),
    ("https://youtube.com/c/Google", "@Google"),
    ("https://youtube.com/channel/UCxK_pLNXt9N", "UCxK_pLNXt9N"),
])
def test_youtube_handles(url, handle):
    r = extract_from_url(url)
    assert r is not None
    assert r[0] == "youtube"
    assert r[1] == handle


@pytest.mark.parametrize("url", [
    "https://youtube.com/watch?v=abc",
    "https://youtube.com/playlist?list=PL",
    "https://youtube.com/results?search_query=foo",
])
def test_youtube_video_paths_rejected(url):
    assert extract_from_url(url) is None


# ── Instagram / TikTok / GitHub ────────────────────────────────────

def test_instagram_handle():
    r = extract_from_url("https://instagram.com/google")
    assert r and r[0] == "instagram" and r[1] == "@google"


def test_tiktok_handle():
    r = extract_from_url("https://tiktok.com/@google")
    assert r and r[0] == "tiktok" and r[1] == "@google"


def test_github_org():
    r = extract_from_url("https://github.com/google-deepmind")
    assert r and r[0] == "github" and r[1] == "@google-deepmind"


def test_github_org_repo_collapses_to_org():
    r = extract_from_url("https://github.com/openai/whisper")
    assert r and r[1] == "@openai"


def test_github_reserved_path_rejected():
    assert extract_from_url("https://github.com/marketplace") is None


# ── Non-platform URLs ──────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://medium.com/article",
    "https://example.com/foo/bar",
    "https://mirofish.my/",
    "not-a-url",
    "",
])
def test_non_platform_returns_none(url):
    assert extract_from_url(url) is None


# ── Bulk extractor + dedupe ────────────────────────────────────────

def test_extract_handles_from_sources_dedupe():
    urls = [
        "https://x.com/googleai",
        "https://x.com/googleai/status/123",   # same handle
        "https://x.com/GoogleAI",              # case-insensitive dedup
        "https://reddit.com/r/Bard",
        "https://example.com/random",
        "https://youtube.com/@google",
    ]
    handles = extract_handles_from_sources(urls)
    keys = {(p, h.lower()) for p, h, _ in handles}
    assert ("x", "@googleai") in keys
    assert ("reddit", "r/bard") in keys
    assert ("youtube", "@google") in keys
    assert len(keys) == 3   # duplicates collapsed


def test_extract_returns_normalized_url():
    r = extract_from_url("https://www.twitter.com/openai/status/9?lang=es")
    assert r and r[2] == "https://x.com/openai"


def test_extract_handles_empty_list():
    assert extract_handles_from_sources([]) == []
