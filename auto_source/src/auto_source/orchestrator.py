"""auto_source orchestrator: search official URLs per main topic + recapture.

Drives the whole phase. Eligibility rule for a topic:
  topic.role == "main"  AND  topic.kind in eligible kinds.

Per topic:
  1. Skip if any entity sharing the canonical/label already has a URL whose
     host is non-social — the operator already provided enough.
  2. Run neobrowser google search '<topic.label> official'.
  3. Pick first non-social URL.
  4. Recapture that URL into the same captures/ dir.
  5. Append the URL to entity.official_urls (entity matched by canonical).

Outputs:
  - analysis_super_enriched.json     (analysis with URLs filled)
  - capture_manifest_enriched.json   (original + new captures merged)
  - auto_source_report.json          (per-topic discovery audit)
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from analysis.contracts import AnalysisResult, Entity, Topic
from .contracts import AutoSourceReport, TopicSourceDiscovery
from .recapture import recapture_urls
from .searcher import find_official_url

log = logging.getLogger("auto_source.orchestrator")

_ELIGIBLE_KINDS = frozenset({"product", "company", "person", "platform", "sector", "event"})


def _entity_already_has_official_url(
    entity: Entity,
    non_official_hosts: set[str],
) -> bool:
    from urllib.parse import urlparse
    for url in entity.official_urls or []:
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            continue
        if host.startswith("www."):
            host = host[4:]
        if host and host not in non_official_hosts:
            return True
    return False


def _find_entity_for_topic(
    topic: Topic,
    entities: list[Entity],
) -> Entity | None:
    """Match a topic to its primary entity by canonical/label.

    Topic.label is "as in video" (e.g. "Gemma 4"); Entity.canonical may be
    the same string. We do a case-insensitive token-level overlap to be
    forgiving with whitespace / casing.
    """
    label_low = topic.label.lower().strip()
    for ent in entities:
        if ent.canonical.lower().strip() == label_low:
            return ent
    # Fallback: match any entity whose canonical contains the topic_id or label
    for ent in entities:
        if topic.label.lower() in ent.canonical.lower():
            return ent
        if ent.canonical.lower() in topic.label.lower():
            return ent
    return None


def auto_source(
    enriched_analysis: AnalysisResult,
    capture_manifest: dict,
    capture_out_dir: Path,
    *,
    search_fn: Callable[[str, int], list[str]] | None = None,
    recapture: bool = True,
    capture_bin: str | None = None,
) -> tuple[AnalysisResult, dict, AutoSourceReport]:
    """Run the full auto-source pass.

    Args:
        enriched_analysis:   analysis_enriched.json (from entity_enricher)
        capture_manifest:    current capture_manifest dict (in memory)
        capture_out_dir:     dir where captures/ live (== run_dir/capture/)
        search_fn:           neobrowser search fn (default uses
                             entity_enricher.browser_lookup.neobrowser_search)
        recapture:           if False, just discover URLs; do not invoke capture.
        capture_bin:         path to the capture binary (override for tests).

    Returns:
        (super_enriched_analysis, merged_manifest, report)
    """
    from .searcher import _NON_OFFICIAL_HOSTS

    if search_fn is None:
        from entity_enricher.browser_lookup import neobrowser_search
        search_fn = neobrowser_search

    report = AutoSourceReport(created_at=datetime.now(timezone.utc))
    topics = enriched_analysis.narrative.topics or []
    entities = list(enriched_analysis.narrative.entities)
    report.topics_total = len(topics)

    # Track entities mutated so we can build a new analysis at the end.
    canonical_to_url: dict[str, str] = {}
    new_capture_urls: list[str] = []

    for topic in topics:
        if topic.role != "main" or topic.kind not in _ELIGIBLE_KINDS:
            continue
        report.topics_eligible += 1

        ent = _find_entity_for_topic(topic, entities)
        if ent is None:
            report.discoveries.append(TopicSourceDiscovery(
                topic_id=topic.topic_id, topic_label=topic.label,
                query="", status="skipped",
                error="no entity matches this topic",
            ))
            continue

        # Skip if the entity already has at least one canonical URL
        if _entity_already_has_official_url(ent, _NON_OFFICIAL_HOSTS):
            report.discoveries.append(TopicSourceDiscovery(
                topic_id=topic.topic_id, topic_label=topic.label,
                query="(skipped)", status="skipped",
                error="entity already has an official URL",
            ))
            continue

        t0 = time.monotonic()
        chosen, all_urls = find_official_url(
            topic.label, search_fn=search_fn, max_results=10,
        )
        elapsed = int((time.monotonic() - t0) * 1000)

        if chosen is None:
            report.discoveries.append(TopicSourceDiscovery(
                topic_id=topic.topic_id, topic_label=topic.label,
                query=f'"{topic.label}" official',
                candidate_urls=all_urls, chosen_url=None,
                status="no_official", duration_ms=elapsed,
            ))
            continue

        canonical_to_url[ent.canonical] = chosen
        new_capture_urls.append(chosen)
        report.discoveries.append(TopicSourceDiscovery(
            topic_id=topic.topic_id, topic_label=topic.label,
            query=f'"{topic.label}" official',
            candidate_urls=all_urls, chosen_url=chosen,
            status="found", duration_ms=elapsed,
        ))
        report.topics_resolved += 1

    # Recapture all discovered URLs in one call (capture handles batching).
    new_manifest_results: list[dict] = []
    if recapture and new_capture_urls:
        kwargs = {}
        if capture_bin is not None:
            kwargs["capture_bin"] = capture_bin
        new_manifest = recapture_urls(new_capture_urls, capture_out_dir, **kwargs)
        if new_manifest:
            new_manifest_results = new_manifest.get("results", [])
            report.new_captures = sum(
                1 for r in new_manifest_results if r.get("status") == "ok"
            )
        else:
            report.errors.append("recapture returned empty manifest")

    # Build url → slug mapping from newly captured results
    url_to_slug: dict[str, str] = {}
    for r in new_manifest_results:
        req = r.get("request", {})
        url = req.get("normalized_url") or req.get("url") or ""
        slug = req.get("slug")
        if url and slug:
            url_to_slug[url] = slug

    # Update entities + discoveries with the slug
    new_entities: list[Entity] = []
    for ent in entities:
        if ent.canonical in canonical_to_url:
            url = canonical_to_url[ent.canonical]
            urls_with_new = list(ent.official_urls) + [url]
            new_entities.append(ent.model_copy(update={"official_urls": urls_with_new}))
        else:
            new_entities.append(ent)

    for d in report.discoveries:
        if d.chosen_url:
            d.chosen_slug = url_to_slug.get(d.chosen_url) or url_to_slug.get(d.chosen_url + "/")

    # Merge manifests: existing results + new ones (dedupe by slug)
    merged = dict(capture_manifest)
    existing = list(merged.get("results", []))
    seen_slugs = {r.get("request", {}).get("slug") for r in existing}
    for r in new_manifest_results:
        slug = r.get("request", {}).get("slug")
        if slug and slug not in seen_slugs:
            existing.append(r)
            seen_slugs.add(slug)
    merged["results"] = existing

    super_enriched = enriched_analysis.model_copy(deep=True)
    super_enriched.narrative.entities = new_entities

    return super_enriched, merged, report
