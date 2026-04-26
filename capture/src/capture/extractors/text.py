"""Extract visible text from raw HTML.

Priority tree:
  1. ``<article>`` — if any contains substantial text (``min_chars``),
     pick the longest one (covers Medium, blogs, docs, news).
  2. ``<main>`` — otherwise, the first ``<main>`` that meets the bar.
  3. ``<body>`` — final fallback (Reddit SSR, Twitter, SPAs without
     semantic HTML, or sites whose semantic tags only wrap UI chrome).

The threshold protects against false positives: some sites put empty
``<article>`` tags around recommendation widgets while the real
content lives in custom elements (e.g. Reddit's ``<shreddit-post>``).

Scripts, styles, noscript and template elements are stripped always.
Whitespace is collapsed to single spaces; paragraphs separated by a
single blank line.
"""
from __future__ import annotations

import re

_WS_RUN = re.compile(r"[ \t]+")
_BLANK_RUN = re.compile(r"\n{3,}")
_NOISE_SELECTORS = ("script", "style", "noscript", "template")

# Minimum characters of visible text for <article>/<main> to be
# considered the "main region". Tuned empirically: news/blog posts
# are comfortably above 500; nav/widget wrappers almost never reach it.
DEFAULT_MIN_CHARS = 500


def extract_text(html: str, *, min_region_chars: int = DEFAULT_MIN_CHARS) -> str:
    try:
        from selectolax.parser import HTMLParser  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "selectolax is required for extractors.text. "
            "Install capture[backends]."
        ) from e

    tree = HTMLParser(html)
    for sel in _NOISE_SELECTORS:
        for node in tree.css(sel):
            node.decompose()

    root = _pick_main_region(tree, min_chars=min_region_chars)
    if root is None:
        return ""

    raw = root.text(separator="\n", strip=False)
    lines = [_WS_RUN.sub(" ", ln).strip() for ln in raw.splitlines()]
    out = "\n".join(lines)
    out = _BLANK_RUN.sub("\n\n", out)
    return out.strip()


def _pick_main_region(tree, *, min_chars: int):
    def _visible_len(node) -> int:
        t = node.text(strip=True) or ""
        return len(t)

    articles = tree.css("article")
    if articles:
        best = max(articles, key=_visible_len)
        if _visible_len(best) >= min_chars:
            return best

    for main in tree.css("main"):
        if _visible_len(main) >= min_chars:
            return main

    return tree.body or tree.root
