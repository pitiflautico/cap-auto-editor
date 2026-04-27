"""Tests for browser_lookup with a fake search_fn (no neobrowser)."""
from __future__ import annotations

from entity_enricher.browser_lookup import lookup_handles


def _fake_search_factory(per_query: dict[str, list[str]]):
    def fake_search(query: str, max_results: int = 5) -> list[str]:
        # Match by which platform tag is in the query
        for tag, urls in per_query.items():
            if tag in query:
                return urls[:max_results]
        return []
    return fake_search


def test_picks_first_valid_x_profile():
    fake = _fake_search_factory({
        "x.com": [
            "https://google.com/about",        # rejected (not a platform)
            "https://x.com/googleai",          # winner
            "https://x.com/someoneelse",       # would lose
        ],
    })
    out = lookup_handles("Gemma 4", ["x"], search_fn=fake)
    assert len(out) == 1
    assert out[0].platform == "x"
    assert out[0].handle == "@googleai"
    assert out[0].origin == "browser_search"
    assert out[0].url == "https://x.com/googleai"


def test_skips_platform_with_no_match():
    fake = _fake_search_factory({
        "reddit": ["https://example.com/no", "https://other.com/foo"],
    })
    out = lookup_handles("Foo", ["reddit"], search_fn=fake)
    assert out == []


def test_search_failure_does_not_crash_for_other_platforms():
    def fake(query, max_results=5):
        if "youtube" in query:
            raise RuntimeError("network down")
        return ["https://x.com/openai"]
    out = lookup_handles("OpenAI", ["x", "youtube"], search_fn=fake)
    handles = {(h.platform, h.handle) for h in out}
    assert ("x", "@openai") in handles
    # youtube failed silently, no entry for it
    assert all(p != "youtube" for p, _ in handles)


def test_only_one_handle_per_platform_returned():
    fake = _fake_search_factory({
        "x.com": [
            "https://x.com/a",
            "https://x.com/b",
            "https://x.com/c",
        ],
    })
    out = lookup_handles("Foo", ["x"], search_fn=fake)
    assert len(out) == 1
    assert out[0].handle == "@a"   # first valid wins


def test_query_template_reaches_search_fn():
    captured: list[str] = []
    def fake(query, max_results=5):
        captured.append(query)
        return ["https://x.com/openai"]
    lookup_handles("OpenAI", ["x"], search_fn=fake)
    assert any("OpenAI" in q for q in captured)
    assert any("site:x.com" in q for q in captured)
