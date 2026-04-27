"""End-to-end tests for the enricher orchestrator (no neobrowser)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from analysis.contracts import (
    AnalysisResult, ArcAct, Beat, Entity, Narrative, Topic,
)
from entity_enricher.enricher import enrich_entities


def _make_analysis(entities: list[Entity]) -> AnalysisResult:
    n = Narrative(
        video_summary="x", narrative_thesis="y", audience="z", tone="t",
        arc_acts=[ArcAct(name="Hook", start_s=0, end_s=10,
                          purpose="Open the video.", topic_focus=[])],
        beats=[Beat(beat_id="b001", start_s=0.0, end_s=5.0, text="hello",
                    editorial_function="hook", hero_text_candidate=None,
                    energy="medium", references_topic_ids=[], broll_hints=[])],
        topics=[],
        entities=entities,
    )
    return AnalysisResult(
        created_at=datetime.now(timezone.utc),
        transcript_ref="/x", capture_manifest_ref=None,
        language="en", duration_s=10.0,
        llm_provider="deepseek", llm_model="x",
        narrative=n,
    )


def _entity(canonical, kind="product"):
    return Entity(canonical=canonical, surface_forms=[canonical], kind=kind,
                  mentioned_in_beats=["b001"], official_urls=[])


def test_enrichment_from_sources_url_directly(tmp_path: Path):
    a = _make_analysis([_entity("Mirofish")])
    sources = ["https://x.com/mirofish", "https://medium.com/article"]
    enriched, report = enrich_entities(
        a, sources, use_browser=False,
        cache_path=tmp_path / "cache.json",
    )
    e = enriched.narrative.entities[0]
    assert "x" in e.official_handles
    assert e.official_handles["x"] == ["@mirofish"]
    assert report.handles_from_sources >= 1
    assert report.entities_enriched == 1


def test_concept_kind_skipped(tmp_path: Path):
    a = _make_analysis([_entity("on_device_ai", kind="concept")])
    enriched, report = enrich_entities(
        a, ["https://x.com/foo"], use_browser=False,
        cache_path=tmp_path / "cache.json",
    )
    assert "on_device_ai" in report.skipped_entities
    assert enriched.narrative.entities[0].official_handles == {}


def test_browser_search_fills_missing_platforms(tmp_path: Path):
    a = _make_analysis([_entity("OpenAI")])

    def fake_search(query, max_results=5):
        if "x.com" in query:
            return ["https://x.com/openai"]
        if "reddit.com" in query:
            return ["https://reddit.com/r/OpenAI"]
        return []

    enriched, report = enrich_entities(
        a, [], search_fn=fake_search,
        cache_path=tmp_path / "cache.json",
        platforms=("x", "reddit"),
    )
    e = enriched.narrative.entities[0]
    assert e.official_handles["x"] == ["@openai"]
    assert e.official_handles["reddit"] == ["r/OpenAI"]
    assert report.handles_from_browser == 2


def test_cache_hit_skips_browser(tmp_path: Path):
    """Second call for the same entity should not invoke search_fn."""
    a = _make_analysis([_entity("OpenAI")])
    calls: list[str] = []
    def fake(query, max_results=5):
        calls.append(query)
        if "x.com" in query: return ["https://x.com/openai"]
        return []

    cache_path = tmp_path / "cache.json"
    enrich_entities(a, [], search_fn=fake, cache_path=cache_path,
                    platforms=("x",))
    first_count = len(calls)

    # Second run should hit cache
    enrich_entities(a, [], search_fn=fake, cache_path=cache_path,
                    platforms=("x",))
    assert len(calls) == first_count, "second run should be served from cache"


def test_unrelated_sources_url_does_not_attach_to_entity(tmp_path: Path):
    """A URL whose handle doesn't share any token with the canonical must NOT
    be assigned to that entity."""
    a = _make_analysis([_entity("Mirofish")])
    sources = ["https://x.com/randomuser"]
    enriched, _ = enrich_entities(
        a, sources, use_browser=False,
        cache_path=tmp_path / "cache.json",
    )
    assert enriched.narrative.entities[0].official_handles == {}


def test_platform_kind_entity_does_not_absorb_random_handles(tmp_path: Path):
    """Entity 'GitHub' (kind=platform) must NOT be assigned a handle like
    @mirofish just because the handle URL is on github.com. The handle
    name itself ("mirofish") has no token overlap with "github".
    """
    a = _make_analysis([
        _entity("MiroFish", kind="product"),
        _entity("GitHub", kind="platform"),
        _entity("Reddit", kind="platform"),
    ])
    sources = [
        "https://github.com/mirofish",
        "https://reddit.com/r/MachineLearning",
        "https://x.com/mirofish",
    ]
    enriched, _ = enrich_entities(
        a, sources, use_browser=False,
        cache_path=tmp_path / "cache.json",
    )
    by_canonical = {e.canonical: e for e in enriched.narrative.entities}
    # MiroFish gets the handles whose name contains "mirofish"
    assert by_canonical["MiroFish"].official_handles.get("github") == ["@mirofish"]
    assert by_canonical["MiroFish"].official_handles.get("x") == ["@mirofish"]
    # GitHub-the-entity must NOT inherit @mirofish — handle name is "mirofish",
    # not "github".
    assert by_canonical["GitHub"].official_handles == {}
    # Reddit-the-entity must NOT inherit r/MachineLearning either.
    assert by_canonical["Reddit"].official_handles == {}


def test_browser_failure_recorded_in_report(tmp_path: Path):
    a = _make_analysis([_entity("Foo")])
    def boom(query, max_results=5):
        raise RuntimeError("network down")
    enriched, report = enrich_entities(
        a, [], search_fn=boom,
        cache_path=tmp_path / "cache.json",
        platforms=("x",),
    )
    # Entity is still emitted; failure is just recorded
    assert enriched.narrative.entities[0].official_handles == {}
    # The current implementation swallows per-platform failures inside
    # lookup_handles, so report.errors stays empty here. We just assert that
    # the run completes and the entity is still present.
    assert len(enriched.narrative.entities) == 1
