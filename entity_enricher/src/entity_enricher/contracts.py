"""Pydantic contracts for entity_enricher.

Keeps the schema for the cache + lookup report (whose entries are reusable
across runs) decoupled from the analysis schema, which only knows the
final `Entity.official_handles: dict[str, list[str]]` shape.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Platforms we resolve. Add new keys here as we add lookup support.
Platform = Literal["x", "reddit", "youtube", "instagram", "github", "tiktok"]

# Reason a handle was selected.
LookupOrigin = Literal["sources_url", "browser_search", "cache"]


class HandleEntry(BaseModel):
    """One handle resolved for an (entity, platform) pair."""
    model_config = ConfigDict(extra="forbid")

    platform: Platform
    handle: str                    # "@googleai", "r/Bard", "@google"
    url: str                       # absolute platform URL (audit trail)
    origin: LookupOrigin
    verified_at: datetime
    confidence: float = 0.9        # 0..1 — sources_url=1.0, browser=0.7-0.9


class CacheEntry(BaseModel):
    """One cached lookup keyed by canonical entity name."""
    model_config = ConfigDict(extra="forbid")

    canonical: str
    handles: list[HandleEntry] = Field(default_factory=list)
    last_lookup_at: datetime
    ttl_days: int = 30


class HandleCache(BaseModel):
    schema_version: str = "1.0.0"
    entries: dict[str, CacheEntry] = Field(default_factory=dict)


class EnrichmentReport(BaseModel):
    """Run-time report. Persisted as analysis_enrichment_report.json."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    created_at: datetime
    entities_total: int = 0
    entities_enriched: int = 0
    handles_added: int = 0
    handles_from_sources: int = 0
    handles_from_browser: int = 0
    handles_from_cache: int = 0
    skipped_entities: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
