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


# ── v2.0 prompt: analysis only emits visual_need; no broll planning ──


def test_prompt_has_visual_need_section():
    """The director must emit visual_need / visual_anchor_type /
    visual_subject per beat. The actual broll_hints planning lives in
    the dedicated broll_planner phase."""
    prompt = ANALYSIS_PROMPT
    assert "visual_need" in prompt
    assert "visual_anchor_type" in prompt
    assert "visual_subject" in prompt


def test_prompt_lists_visual_need_levels():
    """Three levels: required / optional / none."""
    prompt = ANALYSIS_PROMPT
    assert "`required`" in prompt
    assert "`optional`" in prompt
    assert "`none`" in prompt


def test_prompt_lists_visual_anchor_types():
    """Anchor taxonomy the broll_planner relies on."""
    prompt = ANALYSIS_PROMPT
    for anchor in ("entity", "metric", "comparison", "quote",
                    "platform", "feature", "mood"):
        assert anchor in prompt, f"anchor type {anchor!r} missing"


def test_prompt_does_not_emit_broll_hints():
    """Analysis 2.0 explicitly tells the director NOT to plan b-roll;
    the broll_planner does that in a second pass with full context.
    Emission rules for slide_kind / mockup_kind / queries / source_ref
    must NOT live in the analysis prompt anymore."""
    prompt = ANALYSIS_PROMPT
    assert "DO NOT emit b-roll hints" in prompt
    assert "broll_planner" in prompt
    # No traces of broll-only fields
    assert "slide_kind" not in prompt
    assert "mockup_kind" not in prompt
    assert "capcut_effect" not in prompt
    assert "queries_fallback" not in prompt


def test_prompt_teaches_topic_id_format():
    """Deterministic topic_id rule with version-aware snake_case."""
    prompt = ANALYSIS_PROMPT
    assert "topic_id" in prompt
    assert "qwen_3_6" in prompt        # the example format
    assert "snake_case" in prompt


def test_prompt_teaches_retakes_via_flags_not_text():
    """Retakes / silence / asr_garbage MUST be flagged, not written
    into beat.text as synthetic placeholder strings."""
    prompt = ANALYSIS_PROMPT
    assert "speaker_retake" in prompt
    assert "asr_garbage" in prompt
    assert "Do NOT write synthetic placeholder text" in prompt


def test_prompt_teaches_surface_form_disambiguation():
    """Bare one-word aliases that collide with versioned names must
    not become surface_forms. This is what protected the polish phase
    from corrupting 'Qwen' when the canonical was 'Qwen 3.6'."""
    prompt = ANALYSIS_PROMPT
    assert "Surface forms must be specific" in prompt
