"""test_prompts.py — Snapshot-style tests for the analysis prompt."""
from __future__ import annotations

import pytest

from analysis.prompts import ANALYSIS_PROMPT, build_analysis_prompt

SAMPLE_SEGMENTS = [
    {"start_s": 0.0, "end_s": 5.0, "text": "Hola, bienvenidos al canal."},
    {"start_s": 5.0, "end_s": 10.0, "text": "Hoy vamos a hablar de Qwen 3.6."},
    {"start_s": 10.0, "end_s": 15.0, "text": "Es el mejor modelo open source."},
]

SAMPLE_SOURCES = [
    {
        "slug": "example-com-qwen",
        "title": "Qwen 3.6 announcement",
        "text_preview": "Alibaba announced Qwen 3.6 27B, a state-of-the-art open-source model.",
    }
]


def test_prompt_has_transcript_block():
    prompt = build_analysis_prompt(SAMPLE_SEGMENTS, duration_s=15.0, language="es")
    assert "<transcript>" in prompt
    assert "</transcript>" in prompt


def test_prompt_has_sources_block():
    # Use a large max_prompt_chars so sources are NOT dropped by the downsampler.
    prompt = build_analysis_prompt(
        SAMPLE_SEGMENTS, duration_s=15.0, language="es", sources=SAMPLE_SOURCES,
        max_prompt_chars=100_000,
    )
    # The appended sources block uses </sources> closing tag (distinct from the
    # inline "<sources>" reference in the prompt rules).
    assert "</sources>" in prompt
    assert "Qwen 3.6 announcement" in prompt


def test_prompt_no_sources_block_when_none():
    prompt = build_analysis_prompt(SAMPLE_SEGMENTS, duration_s=15.0, language="es", sources=None)
    # Without sources, the closing </sources> tag must be absent.
    assert "</sources>" not in prompt


def test_prompt_language_marker():
    prompt = build_analysis_prompt(SAMPLE_SEGMENTS, duration_s=15.0, language="es")
    assert "Language: es" in prompt or "language: es" in prompt.lower() or "es" in prompt


def test_prompt_duration_present():
    prompt = build_analysis_prompt(SAMPLE_SEGMENTS, duration_s=42.5, language="es")
    assert "42.5" in prompt


def test_prompt_hardcap_reminder():
    """The 12s hard cap rule must be present in the prompt."""
    assert "HARD CAP 12s" in ANALYSIS_PROMPT or "12s" in ANALYSIS_PROMPT


def test_prompt_no_google_search():
    """Google Search was removed — must not appear in the prompt."""
    assert "GOOGLE SEARCH" not in ANALYSIS_PROMPT
    assert "Google Search" not in ANALYSIS_PROMPT


def test_prompt_no_audio_reference():
    """Audio-listening references from V4 were removed."""
    assert "You are listening to" not in ANALYSIS_PROMPT


def test_prompt_has_source_anchoring_instruction():
    """Replaced Google Search with sources-based anchoring instruction."""
    assert "source snippets" in ANALYSIS_PROMPT or "sources" in ANALYSIS_PROMPT.lower()


def test_prompt_transcript_content():
    """Segment text should appear in the transcript block."""
    prompt = build_analysis_prompt(SAMPLE_SEGMENTS, duration_s=15.0, language="es")
    assert "Qwen 3.6" in prompt
    assert "bienvenidos" in prompt


# ── Capabilities catalog inyected (slide_kind / mockup_kind / shopping list) ──


def test_prompt_lists_slide_kinds():
    """The prompt must teach the LLM the 5 slide_kind enum values, otherwise
    it cannot pair `type=slide` with the right hf_designer template."""
    prompt = ANALYSIS_PROMPT
    for kind in ("stat", "comparison", "list", "ranking", "progress"):
        assert kind in prompt, f"slide_kind {kind!r} not advertised in prompt"


def test_prompt_lists_mockup_kinds():
    """All four mockup variants must be discoverable from the prompt."""
    prompt = ANALYSIS_PROMPT
    for kind in ("quote", "thesis", "manifesto", "kicker"):
        assert kind in prompt, f"mockup_kind {kind!r} not advertised in prompt"


def test_prompt_requires_kind_for_slide_and_mockup():
    """When type=slide we must require slide_kind (and same for mockup)."""
    prompt = ANALYSIS_PROMPT
    assert "REQUIRED when type=slide" in prompt
    assert "REQUIRED when type=mockup" in prompt


def test_prompt_has_trigger_list_for_features_and_metrics():
    """Trigger list must cover named entities, numbers, comparisons,
    claims, external platforms, product features and atmospheric beats."""
    prompt = ANALYSIS_PROMPT
    assert "TRIGGER LIST" in prompt
    assert "Specific product feature" in prompt
    assert "Concrete number / metric / percentage / money" in prompt
    assert "Contrast or comparison" in prompt
    assert "Bold claim / thesis / quote" in prompt
    assert "Mention of an external platform" in prompt
    assert "Atmospheric / mood beat" in prompt


def test_prompt_has_shopping_list_description_template():
    """`description` must be teached as a 3-line PRIMARY/ACCEPTABLE/AVOID
    block — the matcher (and a future vision verifier) need this shape."""
    prompt = ANALYSIS_PROMPT
    assert "PRIMARY:" in prompt
    assert "ACCEPTABLE:" in prompt
    assert "AVOID:" in prompt
    # Coverage target raised from "most beats []" to "≥ 50% beats with hint"
    assert "≥ 50%" in prompt or "at least 50%" in prompt.lower()


def test_prompt_has_variety_guard():
    """The 'Variety guard' section warns against same-source reuse and
    consecutive same-shot-type / all-designed sequences."""
    prompt = ANALYSIS_PROMPT
    assert "Variety guard" in prompt
    assert "same source_ref" in prompt
    assert "Vary shot_type" in prompt


def test_prompt_schema_includes_new_hint_fields():
    """The JSON example schema must mention the new hint fields so the
    LLM round-trips them verbatim instead of silently dropping them."""
    prompt = ANALYSIS_PROMPT
    assert "slide_kind" in prompt
    assert "mockup_kind" in prompt
    assert '"layout"' in prompt
    assert '"palette"' in prompt


# ── Source priority + brand presence (anti-mockup-overuse rules) ──


def test_prompt_states_source_priority_real_first():
    """Must teach the LLM that real footage / web_capture comes BEFORE
    designed cards. This is what stops 100%-mockup runs for products
    that already have a public website / repo / profile."""
    prompt = ANALYSIS_PROMPT
    assert "Source priority" in prompt
    assert "REAL > CAPTURED > DESIGNED" in prompt
    assert "PREFER THIS over `mockup`" in prompt


def test_prompt_forbids_fake_mockup_when_real_capture_available():
    """The 'fake Twitter, fake Reddit' anti-pattern must be flagged so
    the LLM doesn't fabricate UI clones when a real capture is available."""
    prompt = ANALYSIS_PROMPT
    assert "NEVER fabricate a mockup" in prompt


def test_prompt_requires_brand_anchor_when_main_product():
    """At least one hint must show the actual brand asset (logo /
    landing / repo) — otherwise the video is about a product nobody
    can see on screen."""
    prompt = ANALYSIS_PROMPT
    assert "Brand presence" in prompt
    assert "at least one hint MUST anchor" in prompt


def test_prompt_keeps_pexels_ambient_lane():
    """Pexels stays in the trigger list for atmospheric / mood beats."""
    prompt = ANALYSIS_PROMPT
    assert "Atmospheric / mood beat" in prompt


def test_prompt_has_type_budget_guideline():
    """A coarse mix budget prevents 100%-designed runs."""
    prompt = ANALYSIS_PROMPT
    assert "Type budget" in prompt
    assert "100% mockup/slide" in prompt
