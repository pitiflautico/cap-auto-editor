"""Fetch lightweight metadata from user-provided URLs.

Used to enrich Whisper's `initial_prompt` with entity hints the system
could not know otherwise. Timeout is short by design — if a URL is
slow or blocked, skip it silently. Never fail the pipeline because a
source URL is down.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser


DEFAULT_TIMEOUT_S = 3.0
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)


@dataclass
class SourceMeta:
    url: str
    title: str | None = None
    description: str | None = None
    ok: bool = False
    error: str | None = None


# ── Fetch ──────────────────────────────────────────────────────────

def _fetch_one(url: str, timeout_s: float) -> SourceMeta:
    try:
        with httpx.Client(
            timeout=timeout_s,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_UA, "Accept-Language": "es,en"},
        ) as client:
            r = client.get(url)
            r.raise_for_status()
    except Exception as exc:
        return SourceMeta(url=url, ok=False, error=str(exc))

    ctype = r.headers.get("content-type", "")
    if "html" not in ctype and "xml" not in ctype:
        # Non-HTML (image, pdf, ...) — nothing to parse, still counts as "ok"
        return SourceMeta(url=url, ok=True, title=None, description=None)

    try:
        tree = HTMLParser(r.text)
    except Exception as exc:
        return SourceMeta(url=url, ok=False, error=f"parse: {exc}")

    title_node = tree.css_first("title")
    title = title_node.text(strip=True) if title_node else None

    desc_node = (
        tree.css_first('meta[name="description"]')
        or tree.css_first('meta[property="og:description"]')
    )
    description = desc_node.attributes.get("content") if desc_node else None

    return SourceMeta(url=url, title=title, description=description, ok=True)


def fetch_all(
    urls: list[str],
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_workers: int = 8,
) -> list[SourceMeta]:
    """Fetch metadata for a list of URLs in parallel."""
    if not urls:
        return []
    results: list[SourceMeta] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_fetch_one, u, timeout_s): u for u in urls}
        for fut in as_completed(futs):
            results.append(fut.result())
    # Preserve original order for stability
    order = {u: i for i, u in enumerate(urls)}
    results.sort(key=lambda m: order.get(m.url, 10**6))
    return results


def load_from_capture_manifest(
    manifest_path: Path,
    max_chars_per_text: int = 1800,
) -> list[SourceMeta]:
    """Load SourceMeta from a capture manifest produced by v6/capture/.

    For each result with status=="ok" and artifacts.text_path set, reads
    the captured text file and extracts title (first non-empty line) and
    description (remaining chars up to max_chars_per_text). Image-only
    results (no text_path) return SourceMeta(url=..., ok=True) with nulls.
    Failed results are skipped. Original URL order is preserved.
    """
    import json

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    out_dir = Path(data["out_dir"])
    results = []

    for entry in data["results"]:
        if entry.get("status") != "ok":
            continue
        url = entry["request"]["url"]
        slug = entry["request"]["slug"]
        text_path = (entry.get("artifacts") or {}).get("text_path")

        if not text_path:
            # Image-only — no text to extract
            results.append(SourceMeta(url=url, ok=True))
            continue

        full_path = out_dir / "captures" / slug / "text.txt"
        try:
            raw = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            results.append(SourceMeta(url=url, ok=True))
            continue

        # Trim to budget first, then split into title + description
        chunk = raw[:max_chars_per_text]
        lines = chunk.splitlines()
        title: str | None = None
        for line in lines:
            stripped = line.strip()
            if stripped:
                title = stripped
                break

        # description = everything after the title line, still within budget
        if title is not None:
            title_end = chunk.find(title) + len(title)
            description = chunk[title_end:].strip() or None
        else:
            description = None

        results.append(SourceMeta(url=url, title=title, description=description, ok=True))

    return results


def load_sources_txt(path: Path | str) -> list[str]:
    """Read a sources.txt (one URL per line, '#' comments)."""
    p = Path(path)
    if not p.exists():
        return []
    urls: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        urls.append(s)
    return urls


# ── Entity extraction from metadata ────────────────────────────────

_RE_ACRONYM = re.compile(r"\b[A-Z]{2,8}\b")
_RE_VERSION = re.compile(r"\b[A-Z][A-Za-z0-9\-]*[ \-]?\d+(?:\.\d+)*[A-Za-z]?\b")
_RE_CAMEL = re.compile(r"\b(?:[A-Z][a-z]+){2,}\b|\b[A-Z][a-z]+[A-Z][A-Za-z]+\b")
_RE_TITLECASE_MULTI = re.compile(r"\b(?:[A-Z][a-z]+(?: [A-Z][a-z]+)+)\b")

_COMMON_WORDS = {
    "The", "This", "That", "These", "Those", "With", "From", "Into",
    "How", "Why", "What", "When", "Where", "Who", "Which",
    "OK", "NEW", "OLD", "BIG", "TOP", "GOOD", "BEST",
    "AI", "OS",  # too generic on their own, keep anyway — useful bias
}


def extract_entity_hints(metas: list[SourceMeta], max_hints: int = 30) -> list[str]:
    """Pull likely entity names out of titles/descriptions.

    Deterministic regex. No LLM. Output is a deduped, ordered list of
    terms to feed Whisper as bias. Common English stopwords are filtered.
    """
    seen: dict[str, None] = {}  # ordered set

    def _add(term: str):
        term = term.strip().strip(",.;:!?¡¿\"'()[]{}")
        if len(term) < 2:
            return
        if term in _COMMON_WORDS:
            return
        seen.setdefault(term, None)

    for m in metas:
        if not m.ok:
            continue
        for src in (m.title, m.description):
            if not src:
                continue
            for pat in (_RE_VERSION, _RE_CAMEL, _RE_TITLECASE_MULTI, _RE_ACRONYM):
                for match in pat.findall(src):
                    _add(match)
    return list(seen.keys())[:max_hints]
