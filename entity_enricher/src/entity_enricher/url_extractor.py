"""Extract official platform handles from URLs the operator supplied.

Pure function. No I/O. The operator passes URLs via --sources to the
pipeline; capture/ persists them in capture_manifest.json. Whatever URL
matches a platform pattern yields a handle without browser lookup.

Coverage:
    x.com/<handle>                  → ("x",       "@<handle>")
    x.com/<handle>/status/<id>      → ("x",       "@<handle>")
    twitter.com/<handle>            → ("x",       "@<handle>")
    reddit.com/r/<sub>              → ("reddit",  "r/<sub>")
    reddit.com/user/<u>             → ("reddit",  "u/<u>")
    youtube.com/@<handle>           → ("youtube", "@<handle>")
    youtube.com/c/<channel>         → ("youtube", "@<channel>")
    youtube.com/channel/<id>        → ("youtube", channel_id)
    instagram.com/<handle>          → ("instagram", "@<handle>")
    github.com/<org>                → ("github",  "@<org>")
    github.com/<org>/<repo>         → ("github",  "@<org>")
    tiktok.com/@<handle>            → ("tiktok",  "@<handle>")
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .contracts import Platform


# Reserved URL paths that are NOT user handles
_X_RESERVED = {"home", "search", "explore", "i", "settings", "messages",
               "notifications", "compose", "tos", "privacy", "about",
               "intent", "share", "hashtag", "search-advanced"}
_REDDIT_RESERVED = {"r", "user", "u", "wiki", "search", "submit"}
_YT_RESERVED = {"watch", "playlist", "results", "feed", "shorts"}
_GH_RESERVED = {"login", "join", "marketplace", "explore", "topics",
                "settings", "trending", "issues", "pulls", "notifications",
                "search", "about", "features", "pricing", "enterprise"}
_IG_RESERVED = {"explore", "accounts", "p", "reel", "stories", "tv",
                "direct", "about"}


def _norm(host: str) -> str:
    return (host or "").lower().lstrip("www.")


def extract_from_url(url: str) -> tuple[Platform, str, str] | None:
    """Return (platform, handle, normalized_url) or None.

    The third tuple item is a clean canonical URL of the handle's profile
    page (used as audit trail in HandleEntry.url).
    """
    try:
        p = urlparse(url)
    except Exception:
        return None
    host = _norm(p.hostname or "")
    parts = [seg for seg in (p.path or "").split("/") if seg]

    # ── X / Twitter ─────────────────────────────────────────────────
    if host in ("x.com", "twitter.com", "mobile.twitter.com"):
        if not parts:
            return None
        handle = parts[0]
        if handle.lower() in _X_RESERVED:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
            return None
        return ("x", f"@{handle}", f"https://x.com/{handle}")

    # ── Reddit ──────────────────────────────────────────────────────
    if host in ("reddit.com", "old.reddit.com", "new.reddit.com"):
        if len(parts) < 2:
            return None
        kind, name = parts[0].lower(), parts[1]
        if kind == "r" and re.fullmatch(r"[A-Za-z0-9_]{2,21}", name):
            return ("reddit", f"r/{name}", f"https://reddit.com/r/{name}")
        if kind in ("u", "user") and re.fullmatch(r"[A-Za-z0-9_-]{3,20}", name):
            return ("reddit", f"u/{name}", f"https://reddit.com/u/{name}")
        return None

    # ── YouTube ─────────────────────────────────────────────────────
    if host in ("youtube.com", "m.youtube.com", "youtu.be"):
        if not parts:
            return None
        first = parts[0]
        if first.startswith("@") and len(first) >= 2:
            handle = first
            return ("youtube", handle, f"https://youtube.com/{handle}")
        if first == "c" and len(parts) >= 2:
            return ("youtube", f"@{parts[1]}", f"https://youtube.com/c/{parts[1]}")
        if first == "channel" and len(parts) >= 2:
            return ("youtube", parts[1], f"https://youtube.com/channel/{parts[1]}")
        if first.lower() in _YT_RESERVED:
            return None
        return None

    # ── Instagram ───────────────────────────────────────────────────
    if host == "instagram.com":
        if not parts:
            return None
        handle = parts[0]
        if handle.lower() in _IG_RESERVED:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_.]{1,30}", handle):
            return None
        return ("instagram", f"@{handle}", f"https://instagram.com/{handle}")

    # ── GitHub ──────────────────────────────────────────────────────
    if host == "github.com":
        if not parts:
            return None
        owner = parts[0]
        if owner.lower() in _GH_RESERVED:
            return None
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner):
            return None
        return ("github", f"@{owner}", f"https://github.com/{owner}")

    # ── TikTok ──────────────────────────────────────────────────────
    if host in ("tiktok.com", "vm.tiktok.com"):
        if not parts:
            return None
        first = parts[0]
        if first.startswith("@") and len(first) >= 2:
            return ("tiktok", first, f"https://tiktok.com/{first}")
        return None

    return None


def extract_handles_from_sources(urls: list[str]) -> list[tuple[Platform, str, str]]:
    """Apply ``extract_from_url`` to every URL, dedupe by (platform, handle)."""
    out: list[tuple[Platform, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for u in urls:
        result = extract_from_url(u)
        if result is None:
            continue
        platform, handle, profile_url = result
        key = (platform, handle.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((platform, handle, profile_url))
    return out
