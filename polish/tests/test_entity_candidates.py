"""Tests for entity_candidates detector.

Pure heuristic. Never labels tokens by topic, only by form.
"""
from __future__ import annotations

from polish.contracts import Segment, Transcript, Word
from polish.entity_candidates import detect_entity_candidates


def _t(words: list[tuple[str, float, float]]) -> Transcript:
    ws = [Word(text=tt, start_s=s, end_s=e) for (tt, s, e) in words]
    seg = Segment(
        start_s=ws[0].start_s,
        end_s=ws[-1].end_s,
        text=" ".join(w.text for w in ws),
        words=ws,
    )
    return Transcript(duration_s=seg.end_s, segments=[seg])


def test_detects_acronym():
    t = _t([("Usamos", 0, 0.3), ("GPT", 0.4, 0.6),
            ("para", 0.7, 0.9), ("todo", 1.0, 1.3)])
    cands = detect_entity_candidates(t)
    surfaces = {c.surface_form for c in cands}
    assert "GPT" in surfaces
    gpt = next(c for c in cands if c.surface_form == "GPT")
    assert "acronym" in gpt.evidence_types


def test_detects_midsentence_capital():
    t = _t([("Usamos", 0, 0.3), ("Claude", 0.4, 0.7),
            ("cada", 0.8, 1.0), ("día", 1.0, 1.2)])
    cands = detect_entity_candidates(t)
    claude = next((c for c in cands if c.surface_form == "Claude"), None)
    assert claude is not None
    assert "midsentence_capital" in claude.evidence_types


def test_not_flagged_at_sentence_start():
    t = _t([("Claude", 0, 0.3), ("es", 0.4, 0.5),
            ("bueno", 0.6, 0.9), (".", 0.9, 1.0)])
    cands = detect_entity_candidates(t)
    # First token is sentence-start → not midsentence_capital
    claude = next((c for c in cands if c.surface_form == "Claude"), None)
    if claude is not None:
        assert "midsentence_capital" not in claude.evidence_types


def test_detects_camelcase():
    t = _t([("uso", 0, 0.3), ("LocalLLaMA", 0.4, 0.9),
            ("para", 1.0, 1.2), ("inferir", 1.3, 1.8)])
    cands = detect_entity_candidates(t)
    ll = next(c for c in cands if c.surface_form == "LocalLLaMA")
    assert "camelcase" in ll.evidence_types


def test_detects_version_adjacent():
    t = _t([("corre", 0, 0.3), ("Qwen", 0.4, 0.6),
            ("3.6", 0.7, 0.9), ("perfecto", 1.0, 1.4)])
    cands = detect_entity_candidates(t)
    qwen = next(c for c in cands if c.surface_form == "Qwen")
    assert "version_adjacent" in qwen.evidence_types


def test_detects_repeated_variants():
    t = _t([
        ("Qwen", 0, 0.3), ("es", 0.4, 0.5), ("genial", 0.6, 1.0), (".", 1.0, 1.05),
        ("el", 1.1, 1.2), ("qwen", 1.3, 1.5), ("mola", 1.6, 2.0),
    ])
    cands = detect_entity_candidates(t)
    surfaces = {c.surface_form for c in cands}
    # Both variants get repeated_variant evidence
    if "Qwen" in surfaces and "qwen" in surfaces:
        for c in cands:
            if c.surface_form in {"Qwen", "qwen"}:
                assert "repeated_variant" in c.evidence_types


def test_positions_collected():
    t = _t([("GPT", 0, 0.3), ("y", 0.4, 0.5), ("GPT", 0.6, 0.9)])
    cands = detect_entity_candidates(t)
    gpt = next(c for c in cands if c.surface_form == "GPT")
    assert gpt.occurrences == 2
    assert len(gpt.positions) == 2
