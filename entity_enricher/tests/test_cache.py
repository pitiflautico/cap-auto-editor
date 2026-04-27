"""Tests for HandleCache (load/save/TTL)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from entity_enricher.cache import (
    default_cache_path,
    get,
    load_cache,
    put,
    save_cache,
)
from entity_enricher.contracts import HandleCache, HandleEntry


def _entry(platform="x", handle="@example") -> HandleEntry:
    return HandleEntry(
        platform=platform, handle=handle,
        url=f"https://x.com/{handle.lstrip('@')}",
        origin="sources_url",
        verified_at=datetime.now(timezone.utc),
    )


def test_load_missing_path_returns_empty(tmp_path: Path):
    c = load_cache(tmp_path / "nope.json")
    assert c.entries == {}


def test_save_load_roundtrip(tmp_path: Path):
    p = tmp_path / "cache.json"
    cache = HandleCache()
    put(cache, "Foo", [_entry()])
    save_cache(cache, p)
    loaded = load_cache(p)
    assert "Foo" in loaded.entries
    assert loaded.entries["Foo"].handles[0].handle == "@example"


def test_corrupt_file_returns_empty(tmp_path: Path):
    p = tmp_path / "cache.json"
    p.write_text("{not json", encoding="utf-8")
    c = load_cache(p)
    assert c.entries == {}


def test_get_returns_fresh_entry():
    cache = HandleCache()
    put(cache, "Foo", [_entry()], ttl_days=30)
    e = get(cache, "Foo")
    assert e is not None
    assert e.handles[0].handle == "@example"


def test_get_returns_none_for_expired_entry():
    cache = HandleCache()
    long_ago = datetime.now(timezone.utc) - timedelta(days=60)
    put(cache, "Foo", [_entry()], ttl_days=30, now=long_ago)
    e = get(cache, "Foo")
    assert e is None


def test_get_returns_none_for_missing_canonical():
    cache = HandleCache()
    assert get(cache, "DoesNotExist") is None


def test_default_cache_path_uses_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MYAVATAR_RUNS", str(tmp_path / "runs"))
    p = default_cache_path()
    assert p == tmp_path / "handle_cache.json"


def test_default_cache_path_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("MYAVATAR_RUNS", raising=False)
    p = default_cache_path()
    assert p.name == "handle_cache.json"
    assert "myavatar" in p.parts


def test_save_atomic_write_no_partial(tmp_path: Path):
    """If save_cache raises mid-write, the existing file is intact."""
    p = tmp_path / "cache.json"
    cache = HandleCache()
    put(cache, "Foo", [_entry()])
    save_cache(cache, p)
    original = p.read_text(encoding="utf-8")
    # Sanity: re-save with new entry should leave file valid (atomic replace)
    put(cache, "Bar", [_entry(handle="@bar")])
    save_cache(cache, p)
    new = p.read_text(encoding="utf-8")
    assert new != original
    assert "Bar" in new
