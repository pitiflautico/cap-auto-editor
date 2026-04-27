"""HandleCache — persistent (entity → handles) cache with TTL.

Cache lives at $MYAVATAR_RUNS/../handle_cache.json by default
(i.e. ~/myavatar/handle_cache.json), shared across runs. Entries expire
after `ttl_days` (default 30). Expired entries are returned as None so
the caller can re-look-up; they are NOT auto-evicted on read — eviction
only happens on the next ``save()`` call so we don't fight concurrent
runs.

Atomic writes: tempfile + os.replace. Lock-free is acceptable: races
manifest as a re-lookup, never as a corrupt file.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .contracts import CacheEntry, HandleCache, HandleEntry


def default_cache_path() -> Path:
    base = os.environ.get("MYAVATAR_RUNS")
    if base:
        return Path(base).parent / "handle_cache.json"
    return Path.home() / "myavatar" / "handle_cache.json"


def load_cache(path: Path | None = None) -> HandleCache:
    """Load cache from disk. Missing or corrupt → empty cache."""
    p = path or default_cache_path()
    if not p.exists():
        return HandleCache()
    try:
        return HandleCache.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception:
        return HandleCache()


def save_cache(cache: HandleCache, path: Path | None = None) -> None:
    """Atomic write: tmp file then rename."""
    p = path or default_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".handle_cache.", suffix=".json", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(cache.model_dump_json(indent=2))
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _is_fresh(entry: CacheEntry, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    age = now - _aware(entry.last_lookup_at)
    return age < timedelta(days=entry.ttl_days)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def get(cache: HandleCache, canonical: str, *, now: datetime | None = None
        ) -> CacheEntry | None:
    """Return cached entry IFF still fresh; None otherwise (caller re-looks-up)."""
    entry = cache.entries.get(canonical)
    if entry is None:
        return None
    return entry if _is_fresh(entry, now=now) else None


def put(cache: HandleCache, canonical: str, handles: list[HandleEntry],
        *, ttl_days: int = 30, now: datetime | None = None) -> None:
    """Insert/refresh an entry."""
    cache.entries[canonical] = CacheEntry(
        canonical=canonical,
        handles=handles,
        last_lookup_at=now or datetime.now(timezone.utc),
        ttl_days=ttl_days,
    )
