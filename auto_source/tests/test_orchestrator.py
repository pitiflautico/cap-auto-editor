"""End-to-end tests for the auto_source orchestrator (no real browser)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from analysis.contracts import (
    AnalysisResult, ArcAct, Beat, Entity, Narrative, Topic,
)
from auto_source.orchestrator import auto_source


def _make_analysis(topics: list[Topic], entities: list[Entity]) -> AnalysisResult:
    n = Narrative(
        video_summary="x", narrative_thesis="y", audience="z", tone="t",
        arc_acts=[ArcAct(name="Hook", start_s=0, end_s=10,
                          purpose="Open the video.", topic_focus=[])],
        beats=[Beat(beat_id="b001", start_s=0.0, end_s=5.0, text="hello",
                    editorial_function="hook", hero_text_candidate=None,
                    energy="medium", references_topic_ids=[], broll_hints=[])],
        topics=topics, entities=entities,
    )
    return AnalysisResult(
        created_at=datetime.now(timezone.utc),
        transcript_ref="/x", capture_manifest_ref=None,
        language="en", duration_s=10.0,
        llm_provider="deepseek", llm_model="x",
        narrative=n,
    )


def test_main_topic_resolved_and_url_attached(tmp_path: Path):
    topic = Topic(topic_id="gemma_4", label="Gemma 4",
                  description="Google open AI model.",
                  role="main", kind="product",
                  mentioned_in_beats=["b001"])
    entity = Entity(canonical="Gemma 4", surface_forms=["Gemma 4"],
                    kind="product", mentioned_in_beats=["b001"],
                    official_urls=[])
    a = _make_analysis([topic], [entity])

    fake_search = lambda q, n=5: [
        "https://en.wikipedia.org/wiki/Gemma",
        "https://deepmind.google/models/gemma/gemma-4/",
    ]
    super_enriched, merged, report = auto_source(
        a, capture_manifest={"results": []},
        capture_out_dir=tmp_path,
        search_fn=fake_search, recapture=False,
    )
    assert report.topics_eligible == 1
    assert report.topics_resolved == 1
    e = super_enriched.narrative.entities[0]
    assert "https://deepmind.google/models/gemma/gemma-4/" in e.official_urls


def test_supporting_topic_skipped(tmp_path: Path):
    topic = Topic(topic_id="competitor", label="Llama 4",
                  description="Mentioned only as comparison.",
                  role="supporting", kind="product",
                  mentioned_in_beats=["b001"])
    entity = Entity(canonical="Llama 4", surface_forms=["Llama 4"],
                    kind="product", mentioned_in_beats=["b001"],
                    official_urls=[])
    a = _make_analysis([topic], [entity])

    super_enriched, _, report = auto_source(
        a, {"results": []}, tmp_path,
        search_fn=lambda *args: [], recapture=False,
    )
    assert report.topics_eligible == 0   # supporting not eligible
    assert report.topics_resolved == 0
    assert super_enriched.narrative.entities[0].official_urls == []


def test_concept_kind_skipped(tmp_path: Path):
    topic = Topic(topic_id="ai_local", label="On-device AI",
                  description="Concept.", role="main", kind="concept",
                  mentioned_in_beats=["b001"])
    a = _make_analysis([topic], [])
    _, _, report = auto_source(
        a, {"results": []}, tmp_path,
        search_fn=lambda *args: [], recapture=False,
    )
    assert report.topics_eligible == 0


def test_entity_with_existing_official_url_skipped(tmp_path: Path):
    topic = Topic(topic_id="gemma_4", label="Gemma 4",
                  description="x", role="main", kind="product",
                  mentioned_in_beats=["b001"])
    entity = Entity(canonical="Gemma 4", surface_forms=["Gemma 4"],
                    kind="product", mentioned_in_beats=["b001"],
                    official_urls=["https://deepmind.google/models/gemma/gemma-4/"])
    a = _make_analysis([topic], [entity])
    super_enriched, _, report = auto_source(
        a, {"results": []}, tmp_path,
        search_fn=lambda *args: ["https://example.com/foo"], recapture=False,
    )
    assert report.topics_eligible == 1
    assert report.topics_resolved == 0   # already had a canonical URL → skipped
    # URL list unchanged
    assert super_enriched.narrative.entities[0].official_urls == \
        ["https://deepmind.google/models/gemma/gemma-4/"]


def test_no_official_url_found(tmp_path: Path):
    topic = Topic(topic_id="x", label="X",
                  description="x", role="main", kind="product",
                  mentioned_in_beats=["b001"])
    entity = Entity(canonical="X", surface_forms=["X"],
                    kind="product", mentioned_in_beats=["b001"],
                    official_urls=[])
    a = _make_analysis([topic], [entity])
    super_enriched, _, report = auto_source(
        a, {"results": []}, tmp_path,
        search_fn=lambda *args: ["https://reddit.com/r/x", "https://x.com/x"],
        recapture=False,
    )
    assert report.topics_eligible == 1
    assert report.topics_resolved == 0
    d = report.discoveries[0]
    assert d.status == "no_official"
    assert len(d.candidate_urls) == 2


def test_manifest_merge_dedupes_by_slug(tmp_path: Path):
    topic = Topic(topic_id="gemma_4", label="Gemma 4",
                  description="x", role="main", kind="product",
                  mentioned_in_beats=["b001"])
    entity = Entity(canonical="Gemma 4", surface_forms=["Gemma 4"],
                    kind="product", mentioned_in_beats=["b001"],
                    official_urls=[])
    a = _make_analysis([topic], [entity])
    existing_manifest = {
        "results": [
            {"request": {"slug": "deepmind-google-gemma-4",
                         "url": "https://deepmind.google/models/gemma/gemma-4/",
                         "normalized_url": "https://deepmind.google/models/gemma/gemma-4"},
             "status": "ok", "backend": "browser_sdk",
             "captured_at": "2026-04-27T08:00:00", "duration_ms": 100,
             "artifacts": {}}
        ]
    }
    _, merged, _ = auto_source(
        a, existing_manifest, tmp_path,
        search_fn=lambda *args: ["https://deepmind.google/models/gemma/gemma-4/"],
        recapture=False,
    )
    slugs = [r["request"]["slug"] for r in merged.get("results", [])]
    assert slugs.count("deepmind-google-gemma-4") <= 1
