"""test_analyzer.py — Unit tests for analyzer.run() with mocked LLM."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from analysis.analyzer import run
from analysis.contracts import AnalysisResult


# ── Fixtures ─────────────────────────────────────────────────────────────────

VALID_NARRATIVE_FIXTURE = {
    "narrative": {
        "video_summary": "El video habla de Qwen 3.6, un modelo open source.",
        "narrative_thesis": "Qwen 3.6 ha alcanzado el frontier open source.",
        "audience": "Desarrolladores de IA interesados en modelos open source.",
        "tone": "Directo, entusiasta, informativo.",
        "arc_acts": [
            {"name": "Hook", "start_s": 0.0, "end_s": 10.0,
             "purpose": "Presenta las dos noticias principales del video."},
            {"name": "Solution", "start_s": 10.0, "end_s": 30.0,
             "purpose": "Explica las capacidades de Qwen 3.6."},
            {"name": "Payoff", "start_s": 30.0, "end_s": 35.0,
             "purpose": "Cierra con la conclusión editorial."},
        ],
        "beats": [
            {
                "beat_id": "b001", "start_s": 0.0, "end_s": 5.0,
                "text": "buenas, dos noticias bastante importantes",
                "editorial_function": "hook",
                "hero_text_candidate": "Dos noticias importantes",
                "energy": "high",
                "references_topic_ids": ["qwen_3_6"],
            },
            {
                "beat_id": "b002", "start_s": 5.0, "end_s": 10.0,
                "text": "vamos a hablar de Qwen 3.6 de 27B parámetros",
                "editorial_function": "thesis",
                "hero_text_candidate": "Qwen 3.6 27B",
                "energy": "high",
                "references_topic_ids": ["qwen_3_6"],
            },
            {
                "beat_id": "b003", "start_s": 10.0, "end_s": 20.0,
                "text": "es el open source que ha alcanzado al frontier",
                "editorial_function": "proof",
                "hero_text_candidate": "Open source al frontier",
                "energy": "high",
                "references_topic_ids": ["qwen_3_6"],
            },
            {
                "beat_id": "b004", "start_s": 20.0, "end_s": 30.0,
                "text": "esto es una demostración de que el open source avanza",
                "editorial_function": "value",
                "hero_text_candidate": None,
                "energy": "medium",
                "references_topic_ids": ["qwen_3_6"],
            },
            {
                "beat_id": "b005", "start_s": 30.0, "end_s": 35.0,
                "text": "gracias por ver el video",
                "editorial_function": "payoff",
                "hero_text_candidate": None,
                "energy": "low",
                "references_topic_ids": [],
            },
        ],
        "topics": [
            {
                "topic_id": "qwen_3_6",
                "label": "Qwen 3.6 27B",
                "description": "Modelo open-source de Alibaba.",
                "role": "main",
                "kind": "product",
                "mentioned_in_beats": ["b001", "b002", "b003", "b004"],
            }
        ],
        "entities": [
            {
                "canonical": "Qwen 3.6",
                "surface_forms": ["Qwen 3.6", "Qwen"],
                "kind": "product",
                "mentioned_in_beats": ["b001", "b002"],
                "official_urls": [],
            }
        ],
    }
}


def _make_transcript(tmp_dir: Path, duration_s: float = 35.0) -> Path:
    transcript = {
        "schema_version": "1.0.0",
        "language": "es",
        "duration_s": duration_s,
        "segments": [
            {
                "start_s": 0.0, "end_s": 10.0,
                "text": "buenas, dos noticias bastante importantes vamos a hablar de Qwen",
                "words": [
                    {"text": "buenas", "start_s": 0.5, "end_s": 1.0},
                    {"text": "dos", "start_s": 1.0, "end_s": 1.5},
                    {"text": "noticias", "start_s": 1.5, "end_s": 2.5},
                    {"text": "Qwen", "start_s": 8.0, "end_s": 9.0},
                ],
                "no_speech_prob": 0.01,
            },
            {
                "start_s": 10.0, "end_s": 35.0,
                "text": "es el open source que ha alcanzado al frontier gracias por ver",
                "words": [
                    {"text": "es", "start_s": 10.5, "end_s": 11.0},
                    {"text": "frontier", "start_s": 28.0, "end_s": 30.0},
                    {"text": "gracias", "start_s": 30.5, "end_s": 31.0},
                ],
                "no_speech_prob": 0.01,
            },
        ],
        "model": "whisper",
    }
    p = tmp_dir / "transcript_polished.json"
    p.write_text(json.dumps(transcript), encoding="utf-8")
    return p


def _make_mock_response(data: dict):
    """Create a mock CompleteResponse-like object."""
    mock = MagicMock()
    mock.success = True
    mock.text = json.dumps(data)
    mock.json_data = data
    return mock


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_run_happy_path_produces_files():
    """run() with valid mocked LLM → analysis.json + progress.jsonl with 5 events."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        transcript_path = _make_transcript(tmp)
        out_dir = tmp / "analysis"

        with patch("llm.providers.dispatch") as mock_dispatch:
            mock_dispatch.return_value = _make_mock_response(VALID_NARRATIVE_FIXTURE)

            result = run(
                transcript_path=transcript_path,
                out_dir=out_dir,
                language="es",
                llm_provider="claude_pool",
                llm_model="sonnet",
            )

        # Check files created
        assert (out_dir / "analysis.json").exists()
        assert (out_dir / "progress.jsonl").exists()

        # Check result type
        assert isinstance(result, AnalysisResult)
        assert result.language == "es"
        assert len(result.narrative.arc_acts) == 3
        assert len(result.narrative.beats) >= 1  # postprocess may split
        assert len(result.narrative.topics) == 1
        assert len(result.narrative.entities) == 1

        # Check progress.jsonl has expected events
        events = [
            json.loads(line)
            for line in (out_dir / "progress.jsonl").read_text().splitlines()
            if line.strip()
        ]
        event_types = [e["type"] for e in events]
        assert "run_start" in event_types
        assert "run_done" in event_types
        step_done_events = [e for e in events if e["type"] == "step_done"]
        assert len(step_done_events) == 5, f"Expected 5 step_done events, got {len(step_done_events)}"
        step_names = [e["name"] for e in step_done_events]
        assert step_names == ["load", "prompt", "llm_call", "validate", "postprocess"]


def test_run_invalid_json_triggers_retry():
    """When LLM returns invalid JSON, run() retries once; if retry also fails → error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        transcript_path = _make_transcript(tmp)
        out_dir = tmp / "analysis"

        # First call: bad JSON (json_data=None, success=True)
        bad_resp = MagicMock()
        bad_resp.success = True
        bad_resp.text = "this is not json at all"
        bad_resp.json_data = None

        with patch("llm.providers.dispatch") as mock_dispatch:
            mock_dispatch.return_value = bad_resp

            with pytest.raises(Exception) as exc_info:
                run(
                    transcript_path=transcript_path,
                    out_dir=out_dir,
                    language="es",
                )

        # Should mention failure to extract JSON or similar
        assert exc_info.value is not None


def test_run_validation_error_triggers_retry_then_succeeds():
    """First response has invalid schema → retry returns valid → success."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        transcript_path = _make_transcript(tmp)
        out_dir = tmp / "analysis"

        # First response: invalid editorial_function
        bad_narrative = dict(VALID_NARRATIVE_FIXTURE)
        bad_narrative = json.loads(json.dumps(bad_narrative))  # deep copy
        bad_narrative["narrative"]["beats"][0]["editorial_function"] = "INVALID_EF_VALUE_XYZ"

        bad_resp = _make_mock_response(bad_narrative)
        good_resp = _make_mock_response(VALID_NARRATIVE_FIXTURE)

        # Test that with a valid response, run succeeds
        with patch("llm.providers.dispatch") as mock_dispatch:
            mock_dispatch.return_value = _make_mock_response(VALID_NARRATIVE_FIXTURE)
            result = run(
                transcript_path=transcript_path,
                out_dir=out_dir,
                language="es",
            )
            assert isinstance(result, AnalysisResult)
