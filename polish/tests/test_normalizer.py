"""Tests for text_normalizer and project_aliases."""
from __future__ import annotations

from pathlib import Path

from polish.contracts import Segment, Transcript, Word
from polish.project_aliases import (
    ProjectAlias,
    apply_project_aliases,
    load_project_aliases,
)
from polish.text_normalizer import (
    NormalizationRule,
    load_rules,
    normalize_text,
    normalize_transcript,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ── Text normalizer ────────────────────────────────────────────────

def test_load_rules_filters_non_auto_apply():
    rules = load_rules(PROJECT_ROOT / "text_normalization_rules.yaml")
    # All returned rules must be auto_apply
    assert all(r.auto_apply for r in rules)
    # At least the core punctuation rules are present
    froms = [r.from_ for r in rules]
    assert " ," in froms
    assert " ." in froms
    assert "  " in froms


def test_normalize_text_punctuation_spaces():
    rules = [
        NormalizationRule(from_=" ,", to=",", type="punctuation"),
        NormalizationRule(from_=" .", to=".", type="punctuation"),
    ]
    text = "hola , mundo . adiós"
    out, patches = normalize_text(text, rules)
    assert out == "hola, mundo. adiós"
    assert len(patches) == 2
    assert {p.from_ for p in patches} == {" ,", " ."}


def test_normalize_text_double_space():
    rules = [NormalizationRule(from_="  ", to=" ", type="whitespace")]
    out, patches = normalize_text("a  b   c    d", rules)
    assert out == "a b c d"
    assert len(patches) == 1  # collapsed within one rule application


def test_normalize_transcript_preserves_word_timings():
    words = [Word(text="hola", start_s=0.0, end_s=0.3),
             Word(text=",", start_s=0.3, end_s=0.4),
             Word(text="mundo", start_s=0.5, end_s=0.9)]
    seg = Segment(start_s=0.0, end_s=1.0, text="hola , mundo", words=words)
    t = Transcript(duration_s=1.0, segments=[seg])
    rules = [NormalizationRule(from_=" ,", to=",", type="punctuation")]
    new_t, patches = normalize_transcript(t, rules)
    assert new_t.segments[0].text == "hola, mundo"
    # Words unchanged
    assert [w.text for w in new_t.segments[0].words] == ["hola", ",", "mundo"]
    assert new_t.segments[0].words[0].start_s == 0.0


# ── Project aliases ────────────────────────────────────────────────

def test_load_project_aliases_none_path():
    assert load_project_aliases(None) == []


def test_load_project_aliases_missing_file(tmp_path):
    assert load_project_aliases(tmp_path / "does-not-exist.yaml") == []


def test_apply_project_aliases_entity():
    aliases = [ProjectAlias(
        from_="GPT 5.5", to="GPT-5.5", type="entity",
        auto_apply=True, case_sensitive=True,
    )]
    seg = Segment(
        start_s=0.0, end_s=5.0,
        text="hoy hablamos de GPT 5.5 lanzado por OpenAI",
        words=[],
    )
    t = Transcript(duration_s=5.0, segments=[seg])
    new_t, patches = apply_project_aliases(t, aliases)
    assert new_t.segments[0].text == "hoy hablamos de GPT-5.5 lanzado por OpenAI"
    assert len(patches) == 1
    assert patches[0].from_ == "GPT 5.5"


def test_apply_project_aliases_case_insensitive():
    aliases = [ProjectAlias(
        from_="SONNET", to="Sonnet", type="entity",
        auto_apply=True, case_sensitive=False,
    )]
    seg = Segment(start_s=0, end_s=1, text="el sonnet 4.6 y el SONNET", words=[])
    t = Transcript(duration_s=1.0, segments=[seg])
    new_t, _ = apply_project_aliases(t, aliases)
    assert new_t.segments[0].text == "el Sonnet 4.6 y el Sonnet"


def test_apply_project_aliases_no_match_no_patch():
    aliases = [ProjectAlias(
        from_="Cloud Code", to="Claude Code", type="entity",
        auto_apply=True,
    )]
    seg = Segment(start_s=0, end_s=1, text="hola mundo", words=[])
    t = Transcript(duration_s=1.0, segments=[seg])
    _, patches = apply_project_aliases(t, aliases)
    assert patches == []
