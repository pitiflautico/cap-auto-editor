"""Tests for searcher.find_official_url (pure, no neobrowser)."""
from __future__ import annotations

from auto_source.searcher import find_official_url


def _fake(per_query: dict[str, list[str]]):
    def fake(query: str, max_results: int = 5):
        for tag, urls in per_query.items():
            if tag in query:
                return urls[:max_results]
        return []
    return fake


def test_picks_first_canonical_skipping_wikipedia():
    fake = _fake({
        "Gemma 4": [
            "https://en.wikipedia.org/wiki/Gemma_(LLM)",
            "https://deepmind.google/models/gemma/gemma-4/",
            "https://reddit.com/r/LocalLLaMA/...",
        ],
    })
    chosen, all_urls = find_official_url("Gemma 4", search_fn=fake)
    assert chosen == "https://deepmind.google/models/gemma/gemma-4/"
    assert len(all_urls) == 3


def test_returns_none_when_only_social_results():
    fake = _fake({
        "Foo": [
            "https://reddit.com/r/Foo",
            "https://x.com/Foo",
            "https://github.com/foo/foo",
        ],
    })
    chosen, urls = find_official_url("Foo", search_fn=fake)
    assert chosen is None
    assert len(urls) == 3


def test_skips_google_redirects():
    fake = _fake({
        "Bar": [
            "https://www.google.com/url?q=foo",
            "https://example.com/bar",
        ],
    })
    chosen, _ = find_official_url("Bar", search_fn=fake)
    assert chosen == "https://example.com/bar"


def test_query_format_includes_quotes_and_official():
    captured = []
    def fake(query, max_results=5):
        captured.append(query)
        return []
    find_official_url("Apple Silicon", search_fn=fake)
    assert any('"Apple Silicon"' in q and "official" in q for q in captured)


def test_search_failure_returns_none_pair():
    def fake(query, max_results=5):
        raise RuntimeError("nope")
    chosen, urls = find_official_url("X", search_fn=fake)
    assert chosen is None
    assert urls == []
