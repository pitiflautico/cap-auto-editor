"""Browser-based lookup of platform handles for an entity.

For each entity that did not get a handle from --sources URLs, run a
Google search via neobrowser ("<canonical> twitter"), inspect the first
results, and verify the URL points to a profile page (then reuse the
URL extractor to derive the canonical handle).

This module is intentionally thin: the heavy lifting (Chrome session
management, search query, anti-bot heuristics) lives in neobrowser. Here
we just glue (canonical, platform) → URL → handle.

Lazy import of neobrowser: keeps the module import cheap and the tests
fast. Pass a ``search_fn`` to inject a fake in tests.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Sequence

from .contracts import HandleEntry, Platform
from .url_extractor import extract_from_url

log = logging.getLogger("entity_enricher.browser")


SearchFn = Callable[[str, int], list[str]]
"""Signature: search(query, max_results) -> list of result URLs."""


# Per-platform Google search query template. We bias toward the official
# profile, not third-party mentions.
_QUERY_TEMPLATES: dict[Platform, str] = {
    "x":         '"{name}" site:x.com OR site:twitter.com',
    "reddit":    '"{name}" site:reddit.com',
    "youtube":   '"{name}" official channel site:youtube.com',
    "instagram": '"{name}" site:instagram.com',
    "github":    '"{name}" site:github.com',
    "tiktok":    '"{name}" site:tiktok.com',
}

# Hosts we consider "non-official" / noise when picking the canonical site
_NON_OFFICIAL_HOSTS = {
    "wikipedia.org", "en.wikipedia.org", "es.wikipedia.org",
    "twitter.com", "x.com", "facebook.com", "linkedin.com",
    "instagram.com", "tiktok.com", "youtube.com", "reddit.com",
    "github.com",  # github is official only as profile, not as homepage
    "medium.com",  # mostly third-party blog posts
}


def lookup_handles(
    canonical: str,
    platforms: Sequence[Platform],
    *,
    search_fn: SearchFn,
    max_results_per_platform: int = 5,
) -> list[HandleEntry]:
    """For each requested platform, run a Google search and pick the first
    result that resolves to a profile-page URL via the URL extractor.

    Returns at most one HandleEntry per (canonical, platform). Platforms
    where no result matched are silently absent — caller decides what to
    do (fall back to "no handle for that platform" in HandleCache).
    """
    out: list[HandleEntry] = []
    now = datetime.now(timezone.utc)

    for platform in platforms:
        template = _QUERY_TEMPLATES.get(platform)
        if not template:
            continue
        query = template.format(name=canonical)
        try:
            urls = search_fn(query, max_results_per_platform)
        except Exception as exc:
            log.warning("search failed for %r on %s: %s", canonical, platform, exc)
            continue
        for u in urls:
            extracted = extract_from_url(u)
            if extracted is None:
                continue
            ext_platform, handle, profile_url = extracted
            if ext_platform != platform:
                continue
            out.append(HandleEntry(
                platform=platform,
                handle=handle,
                url=profile_url,
                origin="browser_search",
                verified_at=now,
                confidence=0.75,
            ))
            break  # first matching result wins for this platform

    return out


_NEO_V4_DEFAULT = "/Volumes/DiscoExterno2/mac_offload/Projects/meta-agente/lab/neorender-v2"


def neobrowser_search(query: str, max_results: int = 5) -> list[str]:
    """Real implementation that invokes neobrowser to do a Google search.

    Lazy import so unit tests can run without neobrowser. We reuse the same
    `MYAVATAR_NEO_V4_PATH` env var that capture/backends/browser_sdk.py
    uses, so a single env config covers both modules.
    """
    import os
    import sys
    from pathlib import Path

    neo_path = os.environ.get("MYAVATAR_NEO_V4_PATH", _NEO_V4_DEFAULT)
    if not Path(neo_path).exists():
        raise RuntimeError(
            f"neobrowser path not found at {neo_path!r}. "
            "Set MYAVATAR_NEO_V4_PATH or install neorender-v2."
        )
    if neo_path not in sys.path:
        sys.path.insert(0, neo_path)

    try:
        # Same module path used by capture/backends/browser_sdk.py
        from tools.v4.browser import Browser  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            f"could not import neobrowser from {neo_path!r}: {exc}"
        ) from exc

    # DuckDuckGo: Google routinely serves a CAPTCHA ("/sorry/index") for
    # automated searches even from the same profile. DDG returns clean
    # result links and is friendly to scraping for moderate volumes.
    search_url = "https://duckduckgo.com/?q=" + query.replace(" ", "+")
    with Browser(profile="default", pool_size=1, visible=False) as b:
        tab = b.open(search_url, wait_s=4.0)
        hrefs = tab.js("""
            JSON.stringify(
                Array.from(document.querySelectorAll('a[href]'))
                     .map(a => a.href)
                     .filter(h => h.startsWith('http')
                                  && !h.includes('duckduckgo.com')
                                  && !h.includes('javascript:'))
                     .slice(0, 30)
            )
        """)
        if isinstance(hrefs, str):
            import json as _json
            try:
                hrefs = _json.loads(hrefs)
            except Exception:
                hrefs = []
        if not isinstance(hrefs, list):
            hrefs = []

    # Dedupe preserving order
    seen, out = set(), []
    for u in hrefs:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:max_results]
