"""Orchestrator: combine sources URLs + cache + browser lookup.

For each entity in an analysis.json, derive ``official_handles`` and
write ``analysis_enriched.json`` plus a sidecar enrichment report.

Eligibility rule: only entities with kind ∈ {product, company, person,
platform} are looked up. Sectors and concepts ("on_device_ai") rarely
have a single handle and would burn browser sessions for nothing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from analysis.contracts import AnalysisResult, Entity

from .browser_lookup import lookup_handles, neobrowser_search
from .cache import (
    HandleCache,
    default_cache_path,
    get,
    load_cache,
    put,
    save_cache,
)
from .contracts import EnrichmentReport, HandleEntry, Platform
from .url_extractor import extract_handles_from_sources

log = logging.getLogger("entity_enricher")


_PLATFORMS_DEFAULT: tuple[Platform, ...] = ("x", "reddit", "youtube", "github")
_ELIGIBLE_KINDS = frozenset({"product", "company", "person", "platform"})


def _entity_matches_handle_owner(entity: Entity, handle: str) -> bool:
    """Heuristic: the handle likely belongs to this entity if the handle's
    own name (post-prefix) shares a token with the canonical.

    The check runs against the HANDLE itself ("@mirofish", "r/MachineLearning"),
    not the full URL. Otherwise an entity called "GitHub" would absorb every
    handle on github.com just because "github" appears in the host.

    Conservative: false negatives are fine, false positives waste broll
    resolutions and (worse) leak the wrong handles into the resolver.
    """
    import re
    # Strip platform prefix
    name = handle
    for prefix in ("@", "r/", "u/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    name_low = name.lower()
    if not name_low:
        return False
    canonical_tokens = [
        t for t in re.findall(r"[a-z0-9]+", entity.canonical.lower())
        if len(t) >= 3
    ]
    if not canonical_tokens:
        return False
    # Match if any canonical token is in the handle name OR vice-versa
    # (covers "MiroFish" ↔ "mirofish" and "Google AI" ↔ "googleai").
    return any(t in name_low or name_low in t for t in canonical_tokens)


def _derive_handles_from_sources(
    entity: Entity,
    sources_urls: list[str],
) -> list[HandleEntry]:
    """Take raw URLs the operator gave; keep only those that belong to this
    entity (heuristic match) and convert to HandleEntry."""
    extracted = extract_handles_from_sources(sources_urls)
    now = datetime.now(timezone.utc)
    out: list[HandleEntry] = []
    for platform, handle, profile_url in extracted:
        if not _entity_matches_handle_owner(entity, handle):
            continue
        out.append(HandleEntry(
            platform=platform,
            handle=handle,
            url=profile_url,
            origin="sources_url",
            verified_at=now,
            confidence=1.0,
        ))
    return out


def enrich_entities(
    analysis: AnalysisResult,
    sources_urls: list[str],
    *,
    search_fn: Callable | None = None,
    cache_path: Path | None = None,
    platforms: tuple[Platform, ...] = _PLATFORMS_DEFAULT,
    use_browser: bool = True,
) -> tuple[AnalysisResult, EnrichmentReport]:
    """Populate ``Entity.official_handles`` on a copy of ``analysis``.

    Args:
        analysis:        AnalysisResult (unmodified).
        sources_urls:    raw URLs from the capture_manifest / --sources file.
        search_fn:       browser search fn (default: neobrowser). Tests pass a fake.
        cache_path:      override (defaults to ~/myavatar/handle_cache.json).
        platforms:       which platforms to look up.
        use_browser:     if False, skip the network step (sources + cache only).

    Returns:
        (enriched_analysis, report) — both fully populated.
    """
    cache = load_cache(cache_path)
    report = EnrichmentReport(created_at=datetime.now(timezone.utc))
    report.entities_total = len(analysis.narrative.entities)

    if use_browser and search_fn is None:
        search_fn = neobrowser_search

    enriched_entities: list[Entity] = []
    for entity in analysis.narrative.entities:
        if entity.kind not in _ELIGIBLE_KINDS:
            report.skipped_entities.append(entity.canonical)
            enriched_entities.append(entity)
            continue

        handles: list[HandleEntry] = []

        # 1) Cache (cross-runs)
        cached = get(cache, entity.canonical)
        if cached is not None:
            handles.extend(cached.handles)
            report.handles_from_cache += len(cached.handles)
        else:
            # 2) URLs the operator gave (deterministic, free)
            from_sources = _derive_handles_from_sources(entity, sources_urls)
            handles.extend(from_sources)
            report.handles_from_sources += len(from_sources)

            # 3) Browser lookup for missing platforms
            if use_browser:
                already = {h.platform for h in handles}
                missing = tuple(p for p in platforms if p not in already)
                if missing:
                    try:
                        from_browser = lookup_handles(
                            entity.canonical, missing, search_fn=search_fn,
                        )
                        handles.extend(from_browser)
                        report.handles_from_browser += len(from_browser)
                    except Exception as exc:
                        report.errors.append(
                            f"browser lookup failed for {entity.canonical!r}: {exc}"
                        )

            # 4) Persist to cache (even if empty — locks in TTL)
            put(cache, entity.canonical, handles)

        # Group by platform: dict[str, list[str]] is what analysis schema expects
        grouped: dict[str, list[str]] = {}
        for h in handles:
            grouped.setdefault(h.platform, []).append(h.handle)

        new_entity = entity.model_copy(update={"official_handles": grouped})
        enriched_entities.append(new_entity)
        if grouped:
            report.entities_enriched += 1
            report.handles_added += sum(len(v) for v in grouped.values())

    save_cache(cache, cache_path)

    enriched = analysis.model_copy(deep=True)
    enriched.narrative.entities = enriched_entities
    return enriched, report
