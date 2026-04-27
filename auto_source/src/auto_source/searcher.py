"""Find the canonical official URL of a topic via neobrowser Google search.

Pure orchestration: takes a `search_fn` (so tests inject a fake) and returns
the best non-social, non-noise URL or None. The browser-side implementation
is the same one that lives in entity_enricher.browser_lookup.neobrowser_search,
re-imported here so we don't fork the integration code.
"""
from __future__ import annotations

import logging
from typing import Callable
from urllib.parse import urlparse


log = logging.getLogger("auto_source.searcher")

SearchFn = Callable[[str, int], list[str]]
"""(query, max_results) -> list of URLs."""


# Hosts we filter out: social platforms (handled by entity_enricher),
# encyclopedias (third-party), code hubs (profile-only, not site).
_NON_OFFICIAL_HOSTS = {
    "wikipedia.org", "en.wikipedia.org", "es.wikipedia.org",
    "twitter.com", "x.com", "mobile.twitter.com",
    "facebook.com", "linkedin.com",
    "instagram.com", "tiktok.com",
    "youtube.com", "m.youtube.com", "youtu.be",
    "reddit.com", "old.reddit.com", "new.reddit.com",
    "github.com", "gist.github.com",
    "medium.com",
    "ycombinator.com", "news.ycombinator.com",
    "google.com",
}


def _is_canonical_candidate(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    # Strip leading "www."
    if host.startswith("www."):
        host = host[4:]
    if host in _NON_OFFICIAL_HOSTS:
        return False
    # Filter Google ad redirects and search/translate paths
    path = (urlparse(url).path or "").lower()
    if "/url" in path or "/aclk" in path or "/translate" in path:
        return False
    return True


def find_official_url(
    topic_label: str,
    *,
    search_fn: SearchFn,
    max_results: int = 8,
) -> tuple[str | None, list[str]]:
    """Return (chosen_url, all_result_urls).

    chosen_url: first URL whose host is non-social and not Wikipedia/etc.
    all_result_urls: the raw list returned by neobrowser, kept for audit.
    """
    query = f'"{topic_label}" official'
    try:
        urls = search_fn(query, max_results)
    except Exception as exc:
        log.warning("search failed for %r: %s", topic_label, exc)
        return None, []
    if not urls:
        return None, []
    for u in urls:
        if _is_canonical_candidate(u):
            return u, urls
    return None, urls
