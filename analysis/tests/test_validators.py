"""Deterministic validator tests for analysis v1.3.x.

Structure:
  1. Generic system-behaviour tests (synthetic data — no domain coupling).
  2. One regression test against a real fixture that found a production bug.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from analysis.contracts import (
    AnalysisResult,
    ArcAct,
    Beat,
    BrollHint,
    BrollTiming,
    Entity,
    Narrative,
    Topic,
    ValidationOverride,
)
from analysis.validate import (
    beat_id_resequencer,
    entity_normalizer,
    load_overrides,
    normalize_number,
    numeric_consistency_checker,
    run_all_validators,
    source_ref_validator,
    transcript_sanity_validator,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── helpers ────────────────────────────────────────────────────────────

def _hint(type_="title", desc="x", source_ref=None):
    return BrollHint(type=type_, description=desc, timing=BrollTiming(),
                     energy_match="medium", source_ref=source_ref)


def _beat(beat_id, start, end, text, ef="proof", topics=None, hints=None):
    return Beat(beat_id=beat_id, start_s=start, end_s=end, text=text,
                editorial_function=ef, hero_text_candidate=None, energy="medium",
                references_topic_ids=topics or [], broll_hints=hints or [])


def _make(beats=None, topics=None, entities=None,
          summary="x", thesis="y", arc_acts=None):
    n = Narrative(
        video_summary=summary, narrative_thesis=thesis,
        audience="z", tone="t",
        arc_acts=arc_acts or [ArcAct(name="Hook", start_s=0, end_s=10,
                                      purpose="Open the video.", topic_focus=[])],
        beats=beats or [_beat("b001", 0, 5, "hello")],
        topics=topics or [],
        entities=entities or [],
    )
    return AnalysisResult(
        created_at=datetime.now(), transcript_ref="/x", capture_manifest_ref=None,
        language="es", duration_s=316.1, llm_provider="deepseek", llm_model="x",
        narrative=n,
    )


# ───────────────────────────────────────────────────────────────────────
# 1. ENTITY_NORMALIZER  (11 generic tests)
# ───────────────────────────────────────────────────────────────────────

def test_no_recursive_replacement_when_canonical_contains_surface():
    """If canonical contains a shorter surface_form, the replacement output
    must not be patched again. 'Foo' subset of canonical 'Foo 1.0' must not
    yield 'Foo 1.0 1.0'."""
    entities = [Entity(canonical="Foo 1.0",
                       surface_forms=["Foo 1 .0", "Foo"],
                       kind="product", mentioned_in_beats=["b001"])]
    beats = [_beat("b001", 0, 5, "the model Foo 1 .0 has many params")]
    a = _make(beats=beats, entities=entities)
    a, _ = entity_normalizer(a)
    text = a.narrative.beats[0].text
    assert text.count("Foo 1.0") == 1, f"expected exactly one canonical, got: {text!r}"
    assert "1.0 1.0" not in text


def test_overlapping_spans_resolved_longest_first():
    """When two surface forms overlap, the longest match wins."""
    entities = [Entity(canonical="Acme Sonnet 4.6",
                       surface_forms=["Sonnet 4.6", "Acme Sonnet"],
                       kind="product", mentioned_in_beats=["b001"])]
    beats = [_beat("b001", 0, 5, "Acme Sonnet 4.6 is the new model")]
    a = _make(beats=beats, entities=entities)
    a, _ = entity_normalizer(a)
    # The overlapping 11-char + 13-char match must yield exactly one canonical.
    assert a.narrative.beats[0].text.count("Acme Sonnet 4.6") == 1


def test_replacement_preserves_non_matched_text():
    entities = [Entity(canonical="AlphaModel 2.0",
                       surface_forms=["AlphaModel 2 .0"],
                       kind="product", mentioned_in_beats=["b001"])]
    beats = [_beat("b001", 0, 5,
                   "intro: AlphaModel 2 .0 brings 64GB and many tokens")]
    a = _make(beats=beats, entities=entities)
    a, _ = entity_normalizer(a)
    t = a.narrative.beats[0].text
    assert "intro: " in t
    assert "brings 64GB and many tokens" in t


def test_replacement_logs_entity_patches_with_beat_id_from_to():
    entities = [Entity(canonical="AlphaModel 2.0",
                       surface_forms=["AlphaModel 2 .0"],
                       kind="product", mentioned_in_beats=["b001"])]
    beats = [_beat("b001", 0, 5, "AlphaModel 2 .0 wins")]
    a = _make(beats=beats, entities=entities)
    _, report = entity_normalizer(a)
    assert len(report.entity_patches) == 1
    p = report.entity_patches[0].model_dump(by_alias=True)
    assert p == {"beat_id": "b001", "from": "AlphaModel 2 .0", "to": "AlphaModel 2.0"}


def test_canonical_output_not_re_patched():
    """If a canonical happens to contain another canonical's surface form,
    it must not be rewritten on a second pass."""
    entities = [
        Entity(canonical="AlphaModel 2.0", surface_forms=["AlphaModel 2 .0"],
               kind="product", mentioned_in_beats=["b001"]),
        Entity(canonical="Alpha", surface_forms=["Alpha"],
               kind="company", mentioned_in_beats=["b002"]),
    ]
    beats = [
        _beat("b001", 0, 5, "AlphaModel 2 .0 is by Alpha"),
        _beat("b002", 5, 10, "Alpha published the paper"),
    ]
    a = _make(beats=beats, entities=entities)
    a, _ = entity_normalizer(a)
    t1 = a.narrative.beats[0].text
    # 'AlphaModel 2.0 is by Alpha' — the 'Alpha' inside 'AlphaModel' must NOT
    # be replaced (substring without word boundary).
    assert t1.count("AlphaModel 2.0") == 1
    assert "AlphaModel 2.0Model" not in t1


def test_compound_product_not_corrupted_by_subset_match():
    """Surface_forms of a single ambiguous word ('Foo') must NOT be applied
    when context shows a compound product ('Foo Code')."""
    entities = [Entity(canonical="Foo 1.0", surface_forms=["Foo"],
                       kind="product", mentioned_in_beats=["b001"])]
    beats = [_beat("b001", 0, 5, "Foo Code is integrated everywhere")]
    a = _make(beats=beats, entities=entities)
    a, _ = entity_normalizer(a)
    # No replacement: 'Foo' alone is too ambiguous; would corrupt 'Foo Code'.
    assert a.narrative.beats[0].text == "Foo Code is integrated everywhere"


def test_punctuated_surface_to_canonical_once():
    """ASR-style '<X> <num> .<num>' must produce '<X> <num>.<num>' exactly once."""
    entities = [Entity(canonical="Beta 5.5", surface_forms=["Beta 5 .5"],
                       kind="product", mentioned_in_beats=["b001"])]
    beats = [_beat("b001", 0, 5, "Beta 5 .5 ships next week")]
    a = _make(beats=beats, entities=entities)
    a, _ = entity_normalizer(a)
    t = a.narrative.beats[0].text
    assert t.count("Beta 5.5") == 1
    assert "5.5 5.5" not in t


def test_word_boundaries_respect_substrings():
    """Replacing 'Bar' must not affect 'Barbecue' or 'Barrera'."""
    entities = [Entity(canonical="Bar 2.0", surface_forms=["Bar 2 .0"],
                       kind="product", mentioned_in_beats=["b001"])]
    beats = [_beat("b001", 0, 5, "Barbecue and Bar 2 .0 are different")]
    a = _make(beats=beats, entities=entities)
    a, _ = entity_normalizer(a)
    t = a.narrative.beats[0].text
    assert "Barbecue" in t
    assert "Bar 2.0" in t


def test_single_word_surface_form_skipped_when_ambiguous():
    """A surface_form that is a single bare word must be skipped (whitelist
    rule). Only multi-token or digit-bearing surfaces are applied."""
    entities = [Entity(canonical="Acme 1.0",
                       surface_forms=["Acme"],   # single word, ambiguous
                       kind="company",
                       mentioned_in_beats=["b001"])]
    beats = [_beat("b001", 0, 5, "Acme released a paper")]
    a = _make(beats=beats, entities=entities)
    a, report = entity_normalizer(a)
    # No patch applied; text intact.
    assert a.narrative.beats[0].text == "Acme released a paper"
    assert report.entity_patches == []


def test_two_token_surface_form_with_digits_applied():
    """Surface forms with 2+ tokens or digits ARE applied."""
    entities = [Entity(canonical="Acme 1.0", surface_forms=["Acme 1 .0"],
                       kind="product", mentioned_in_beats=["b001"])]
    beats = [_beat("b001", 0, 5, "Acme 1 .0 is the latest release")]
    a = _make(beats=beats, entities=entities)
    a, report = entity_normalizer(a)
    assert "Acme 1.0" in a.narrative.beats[0].text
    assert len(report.entity_patches) == 1


def test_dedup_not_silenced_by_cleanup():
    """If duplicates somehow survive (regression), the test must FAIL — never
    paper-over with cleanup regex."""
    entities = [Entity(canonical="Foo 1.0",
                       surface_forms=["Foo 1 .0", "Foo"],
                       kind="product", mentioned_in_beats=["b001"])]
    beats = [_beat("b001", 0, 5, "Foo 1 .0 is awesome")]
    a = _make(beats=beats, entities=entities)
    a, _ = entity_normalizer(a)
    t = a.narrative.beats[0].text
    # Hard assertion: NO duplicates of any version-number suffix.
    assert "1.0 1.0" not in t
    assert "Foo 1.0 1.0" not in t


# ───────────────────────────────────────────────────────────────────────
# 2. NUMERIC_CONSISTENCY_CHECKER  (8 generic tests)
# ───────────────────────────────────────────────────────────────────────

def _entity_for(canonical: str, beats_ids: list[str]) -> Entity:
    return Entity(canonical=canonical, surface_forms=[canonical],
                  kind="product", mentioned_in_beats=beats_ids)


def test_million_vs_billion_same_context_blocks():
    e = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 tiene 27 millones de parámetros"),
        _beat("b002", 5, 10, "AlphaModel 1.0 con 27 mil millones de parámetros"),
    ]
    _, report = numeric_consistency_checker(_make(beats=beats, entities=[e]))
    assert report.numeric_conflicts, "expected a conflict, got none"
    assert report.blocked is True


def test_B_suffix_equals_thousand_million_no_conflict():
    e = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 tiene 27B parámetros"),
        _beat("b002", 5, 10, "AlphaModel 1.0 con 27 mil millones de parámetros"),
    ]
    _, report = numeric_consistency_checker(_make(beats=beats, entities=[e]))
    assert not report.numeric_conflicts


def test_es_billion_is_trillion_conflicts_with_thousand_million():
    """Spanish 'billones' = 1e12 (NOT 1e9 like English 'billion'). Therefore
    '27 billones' vs '27 mil millones' on the same entity is a conflict."""
    e = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 con 27 mil millones de parámetros"),
        _beat("b002", 5, 10, "AlphaModel 1.0 alcanza 27 billones de parámetros"),
    ]
    _, report = numeric_consistency_checker(_make(beats=beats, entities=[e]))
    assert report.numeric_conflicts, "27 billones (1e12) must conflict with 27 mil millones (1e9)"
    assert report.blocked is True


def test_es_billones_not_treated_as_en_billion():
    """normalize_number on the Spanish word 'billones' must yield 1e12, NOT 1e9.
    Default English translation is the typical landmine."""
    val = normalize_number("27 billones")
    assert val == pytest.approx(27e12), f"got {val}, expected 27e12"


def test_k_suffix_equals_mil_no_conflict():
    e = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 con 125 mil tokens de contexto"),
        _beat("b002", 5, 10, "AlphaModel 1.0 con 125K tokens de contexto"),
    ]
    _, report = numeric_consistency_checker(_make(beats=beats, entities=[e]))
    assert not report.numeric_conflicts


def test_unit_aliases_tokens_per_second_no_conflict():
    e = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 corre a 85 tokens por segundo"),
        _beat("b002", 5, 10, "AlphaModel 1.0 alcanza 85 TPS"),
    ]
    _, report = numeric_consistency_checker(_make(beats=beats, entities=[e]))
    assert not report.numeric_conflicts


def test_different_units_not_compared():
    """1.7% must not be grouped with '27 millones de parámetros'."""
    e = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 con 27 mil millones de parámetros"),
        _beat("b002", 5, 10, "AlphaModel 1.0 mejora un 1.7% en agencia"),
    ]
    _, report = numeric_consistency_checker(_make(beats=beats, entities=[e]))
    assert not report.numeric_conflicts


def test_same_value_different_entity_no_conflict():
    """Same magnitude/unit in two different entities → no conflict."""
    e1 = _entity_for("AlphaModel 1.0", ["b001"])
    e2 = _entity_for("BetaModel 2.0", ["b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 tiene 27 mil millones de parámetros"),
        _beat("b002", 5, 10, "BetaModel 2.0 tiene 7 mil millones de parámetros"),
    ]
    _, report = numeric_consistency_checker(_make(beats=beats, entities=[e1, e2]))
    assert not report.numeric_conflicts


def test_same_context_same_unit_different_magnitude_conflict():
    """Same entity context + same unit + different magnitude → conflict."""
    e = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 con 27 mil millones de parámetros"),
        _beat("b002", 5, 10, "AlphaModel 1.0 alcanza 13 mil millones de parámetros"),
    ]
    _, report = numeric_consistency_checker(_make(beats=beats, entities=[e]))
    assert report.numeric_conflicts


# ───────────────────────────────────────────────────────────────────────
# 3. REGRESSION — real fixture that found production bug
# ───────────────────────────────────────────────────────────────────────

def test_real_fixture_detects_param_magnitude_conflict():
    """The unvalidated analysis.json from a prior real run had three different
    magnitudes for the same product's parameter count ('27 millones' /
    '27 mil millones' / '27 billones'). The validator MUST detect this."""
    fixture = FIXTURES_DIR / "qwen_27B_real.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    a = AnalysisResult.model_validate(raw)
    _, report = numeric_consistency_checker(a)
    assert report.numeric_conflicts, (
        "expected at least 1 numeric conflict from the real fixture; got 0. "
        "Validator is too narrow or grouping is broken."
    )
    assert report.blocked is True


# ───────────────────────────────────────────────────────────────────────
# 4. PRESERVED — original validators (ASR, source_ref, resequencer)
# ───────────────────────────────────────────────────────────────────────

def test_asr_repetition_flagged_and_hero_text_nullified():
    beats = [
        _beat("b001", 0, 5, "intro normal", ef="hook"),
        _beat("b002", 5, 10,
              "lorem lorem lorem lorem ipsum",
              ef="value", hints=[_hint("video", "x")]),
    ]
    beats[1].hero_text_candidate = "leaked overlay"
    a = _make(beats=beats)
    a, report = transcript_sanity_validator(a)
    flagged_ids = {f.beat_id for f in report.flagged_beats}
    assert "b002" in flagged_ids
    flagged = next(b for b in a.narrative.beats if b.beat_id == "b002")
    assert flagged.editorial_function == "transition"
    assert flagged.broll_hints == []
    assert flagged.hero_text_candidate is None
    issue = next(f for f in report.flagged_beats if f.beat_id == "b002")
    assert issue.token == "lorem"
    assert issue.count >= 4


def test_source_ref_invalid_nullified_and_reported(tmp_path: Path):
    manifest = {
        "schema_version": "2.0.0", "created_at": "2026-04-25T00:00:00",
        "out_dir": str(tmp_path), "backend_default": "browser_sdk",
        "config_snapshot": {},
        "results": [{"request": {"url": "https://x.com",
                                  "normalized_url": "https://x.com",
                                  "slug": "real-slug-abc", "priority": 0},
                     "status": "ok", "backend": "browser_sdk",
                     "captured_at": "2026-04-25T00:00:00", "duration_ms": 100,
                     "artifacts": {}}],
    }
    mf = tmp_path / "capture_manifest.json"
    mf.write_text(json.dumps(manifest))
    beats = [
        _beat("b001", 0, 5, "ok", hints=[_hint("video", "real",
                                                source_ref="real-slug-abc")]),
        _beat("b002", 5, 10, "bad", hints=[_hint("video", "fake",
                                                  source_ref="invented-slug")]),
    ]
    a = _make(beats=beats)
    a, report = source_ref_validator(a, capture_manifest_path=mf)
    assert a.narrative.beats[0].broll_hints[0].source_ref == "real-slug-abc"
    assert a.narrative.beats[1].broll_hints[0].source_ref is None
    assert len(report.invalid_source_refs) == 1


def test_beat_resequence_updates_topics_and_entities():
    beats = [
        _beat("b001", 0, 5, "first", topics=["t1"]),
        _beat("b033", 5, 10, "second", topics=["t1"]),
        _beat("b041", 10, 15, "third", topics=["t1"]),
    ]
    topics = [Topic(topic_id="t1", label="t1", description="x", role="main",
                    kind="product", mentioned_in_beats=["b001", "b033", "b041"])]
    entities = [Entity(canonical="X", surface_forms=["X 1.0"], kind="product",
                       mentioned_in_beats=["b033", "b041"])]
    a = _make(beats=beats, topics=topics, entities=entities)
    a, report = beat_id_resequencer(a)
    assert [b.beat_id for b in a.narrative.beats] == ["b001", "b002", "b003"]
    assert a.narrative.topics[0].mentioned_in_beats == ["b001", "b002", "b003"]
    assert a.narrative.entities[0].mentioned_in_beats == ["b002", "b003"]
    assert len(report.id_remaps) == 2


def test_strict_numeric_blocks_in_runner():
    e = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 tiene 27 millones de parámetros"),
        _beat("b002", 5, 10, "AlphaModel 1.0 con 27 mil millones de parámetros"),
    ]
    a, report = run_all_validators(_make(beats=beats, entities=[e]),
                                    capture_manifest_path=None,
                                    strict_numeric=True)
    assert report.blocked is True


# ───────────────────────────────────────────────────────────────────────
# 5. VALIDATION OVERRIDES — generic across kinds
# ───────────────────────────────────────────────────────────────────────

def test_override_resolves_matching_numeric_conflict_and_unblocks():
    """A matching numeric_conflict override removes the finding and clears
    blocking state."""
    e = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 tiene 27 millones de parámetros"),
        _beat("b002", 5, 10, "AlphaModel 1.0 con 27 mil millones de parámetros"),
    ]
    overrides = [ValidationOverride(
        kind="numeric_conflict",
        match={"entity_or_topic": "entity:AlphaModel 1.0", "unit": "param"},
        resolution={"canonical_value": 27_000_000_000, "canonical_raw": "27 mil millones"},
        rationale="Speaker corrected himself; 27e9 is the canonical magnitude.",
    )]
    _, report = run_all_validators(_make(beats=beats, entities=[e]),
                                    capture_manifest_path=None,
                                    strict_numeric=True,
                                    overrides=overrides)
    assert report.numeric_conflicts == []
    assert report.blocked is False
    assert len(report.applied_overrides) == 1
    assert report.applied_overrides[0].rationale.startswith("Speaker corrected")


def test_override_with_non_matching_context_does_not_apply():
    """An override whose match dict points at a different entity must not
    consume an unrelated conflict."""
    e = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 tiene 27 millones de parámetros"),
        _beat("b002", 5, 10, "AlphaModel 1.0 con 27 mil millones de parámetros"),
    ]
    overrides = [ValidationOverride(
        kind="numeric_conflict",
        match={"entity_or_topic": "entity:DoesNotExist", "unit": "param"},
        resolution={"canonical_value": 0},
        rationale="Targeting a different entity; should not match.",
    )]
    _, report = run_all_validators(_make(beats=beats, entities=[e]),
                                    capture_manifest_path=None,
                                    strict_numeric=True,
                                    overrides=overrides)
    assert report.numeric_conflicts, "non-matching override must not consume the conflict"
    assert report.blocked is True
    assert report.applied_overrides == []


def test_partial_override_remaining_conflict_still_blocks():
    """If two unrelated conflicts exist and only one is overridden, the
    runner must remain blocked on the surviving one."""
    e1 = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    e2 = _entity_for("BetaModel 2.0", ["b003", "b004"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 tiene 27 millones de parámetros"),
        _beat("b002", 5, 10, "AlphaModel 1.0 con 27 mil millones de parámetros"),
        _beat("b003", 10, 15, "BetaModel 2.0 con 7 millones de parámetros"),
        _beat("b004", 15, 20, "BetaModel 2.0 con 7 mil millones de parámetros"),
    ]
    overrides = [ValidationOverride(
        kind="numeric_conflict",
        match={"entity_or_topic": "entity:AlphaModel 1.0", "unit": "param"},
        resolution={"canonical_value": 27_000_000_000},
        rationale="Resolve only AlphaModel; BetaModel must remain blocking.",
    )]
    _, report = run_all_validators(_make(beats=beats, entities=[e1, e2]),
                                    capture_manifest_path=None,
                                    strict_numeric=True,
                                    overrides=overrides)
    surviving = [c for c in report.numeric_conflicts
                 if c.entity_or_topic == "entity:BetaModel 2.0"]
    assert surviving, "BetaModel conflict should survive the AlphaModel-only override"
    assert report.blocked is True


def test_override_recorded_in_applied_overrides_with_full_payload():
    """``applied_overrides`` must carry the full ValidationOverride object
    (kind, match, resolution, rationale) for audit."""
    e = _entity_for("AlphaModel 1.0", ["b001", "b002"])
    beats = [
        _beat("b001", 0, 5, "AlphaModel 1.0 tiene 27 millones de parámetros"),
        _beat("b002", 5, 10, "AlphaModel 1.0 con 27 mil millones de parámetros"),
    ]
    ov = ValidationOverride(
        kind="numeric_conflict",
        match={"entity_or_topic": "entity:AlphaModel 1.0", "unit": "param"},
        resolution={"canonical_value": 27_000_000_000, "canonical_raw": "27 mil millones"},
        rationale="Manual resolution after presenter contradiction.",
    )
    _, report = run_all_validators(_make(beats=beats, entities=[e]),
                                    capture_manifest_path=None,
                                    strict_numeric=True,
                                    overrides=[ov])
    assert len(report.applied_overrides) == 1
    out = report.applied_overrides[0].model_dump()
    assert out["kind"] == "numeric_conflict"
    assert out["match"]["entity_or_topic"] == "entity:AlphaModel 1.0"
    assert out["resolution"]["canonical_value"] == 27_000_000_000
    assert out["rationale"].startswith("Manual resolution")


def test_override_invalid_source_ref_replaces_slug(tmp_path: Path):
    """An invalid_source_ref override with resolution.new_source_ref must
    patch the offending hint and remove the finding."""
    manifest = {
        "schema_version": "2.0.0", "created_at": "2026-04-25T00:00:00",
        "out_dir": str(tmp_path), "backend_default": "browser_sdk",
        "config_snapshot": {},
        "results": [{"request": {"url": "https://x.com",
                                  "normalized_url": "https://x.com",
                                  "slug": "real-slug", "priority": 0},
                     "status": "ok", "backend": "browser_sdk",
                     "captured_at": "2026-04-25T00:00:00", "duration_ms": 100,
                     "artifacts": {}}],
    }
    mf = tmp_path / "capture_manifest.json"
    mf.write_text(json.dumps(manifest))
    beats = [_beat("b001", 0, 5, "ok",
                   hints=[_hint("video", "x", source_ref="invented-slug")])]
    a = _make(beats=beats)
    overrides = [ValidationOverride(
        kind="invalid_source_ref",
        match={"beat_id": "b001", "hint_index": 0,
               "old_source_ref": "invented-slug"},
        resolution={"new_source_ref": "real-slug"},
        rationale="Operator confirmed this slug exists in the manifest.",
    )]
    a, report = run_all_validators(a, capture_manifest_path=mf,
                                    strict_numeric=True,
                                    overrides=overrides)
    assert a.narrative.beats[0].broll_hints[0].source_ref == "real-slug"
    assert report.invalid_source_refs == []
    assert len(report.applied_overrides) == 1


def test_override_asr_repetition_clears_flag_only_for_that_beat():
    """An asr_repetition override matching beat_id removes that finding.
    Other flagged beats must remain (no over-broad consumption)."""
    beats = [
        _beat("b001", 0, 5, "intro normal", ef="hook"),
        _beat("b002", 5, 10, "lorem lorem lorem lorem ipsum", ef="value"),
        _beat("b003", 10, 15, "foo foo foo foo bar", ef="value"),
    ]
    a = _make(beats=beats)
    overrides = [ValidationOverride(
        kind="asr_repetition",
        match={"beat_id": "b002", "token": "lorem"},
        resolution={},
        rationale="Operator confirms b002 is intentional cadence, not ASR garbage.",
    )]
    _, report = run_all_validators(a, capture_manifest_path=None,
                                    strict_numeric=True,
                                    overrides=overrides)
    flagged_ids = {f.beat_id for f in report.flagged_beats}
    assert "b002" not in flagged_ids
    assert "b003" in flagged_ids  # untouched
    assert len(report.applied_overrides) == 1


def test_load_overrides_from_json_file(tmp_path: Path):
    """``load_overrides`` reads {"overrides":[...]} and returns validated models."""
    payload = {
        "overrides": [
            {
                "kind": "numeric_conflict",
                "match": {"entity_or_topic": "entity:AlphaModel 1.0", "unit": "param"},
                "resolution": {"canonical_value": 27_000_000_000,
                               "canonical_raw": "27 mil millones"},
                "rationale": "Loaded from disk.",
            }
        ]
    }
    p = tmp_path / "overrides.json"
    p.write_text(json.dumps(payload))
    loaded = load_overrides(p)
    assert len(loaded) == 1
    assert loaded[0].kind == "numeric_conflict"
    assert loaded[0].match["entity_or_topic"] == "entity:AlphaModel 1.0"
    assert loaded[0].rationale == "Loaded from disk."


# ───────────────────────────────────────────────────────────────────────
# 6. NUMBER NORMALIZER — alias table
# ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("27B", 27_000_000_000),
    ("27 mil millones", 27_000_000_000),
    ("27 millones", 27_000_000),
    ("27 billones", 27_000_000_000_000),   # spanish billion = 1e12
    ("125k", 125_000),
    ("125 mil", 125_000),
    ("1.7%", 1.7),
    ("85 tokens/s", 85),
    ("85 TPS", 85),
    # Whisper occasionally emits "400 .000" (stray space before the dot) when
    # transcribing Spanish numbers like "400.000 millones". The parser must
    # treat the gap as a thousand separator, not a missing zero.
    ("400 .000 millones", 400_000_000_000),
    ("400.000 millones", 400_000_000_000),
    ("1.234.567", 1_234_567),
    ("1,7", 1.7),
    ("27,5%", 27.5),
])
def test_normalize_number_aliases(text, expected):
    val = normalize_number(text)
    assert val is not None, f"{text!r} returned None"
    assert val == pytest.approx(expected), f"{text!r} → {val}, expected {expected}"


def test_attribution_no_topic_bridge_false_positives():
    """A conflict on Entity A's beats must not be attributed to Entity B
    just because both share a topic. Pre-fix, the topic→entity bridge
    pulled every entity that ever appeared under the same topic into the
    context of every beat that referenced that topic, producing conflicts
    on entities never named in the offending text.
    """
    e_main = _entity_for("MainProduct 1.0", ["b001", "b002"])
    e_other = Entity(canonical="OtherProduct", surface_forms=["OtherProduct"],
                     kind="product", mentioned_in_beats=["b003"])
    topics = [Topic(topic_id="shared_topic", label="shared", description="x",
                    role="main", kind="concept",
                    mentioned_in_beats=["b001", "b002", "b003"])]
    beats = [
        _beat("b001", 0, 5, "MainProduct 1.0 con 27 millones de parámetros",
              topics=["shared_topic"]),
        _beat("b002", 5, 10, "MainProduct 1.0 con 27 mil millones de parámetros",
              topics=["shared_topic"]),
        _beat("b003", 10, 15, "OtherProduct standalone",
              topics=["shared_topic"]),
    ]
    a = _make(beats=beats, topics=topics, entities=[e_main, e_other])
    _, report = numeric_consistency_checker(a)
    assert report.numeric_conflicts, "magnitude conflict should be reported"
    attributed = {c.entity_or_topic for c in report.numeric_conflicts}
    assert "entity:MainProduct 1.0" in attributed
    assert "entity:OtherProduct" not in attributed, (
        "OtherProduct shares only a topic; it must NOT be tagged on MainProduct's "
        "numeric conflict"
    )
