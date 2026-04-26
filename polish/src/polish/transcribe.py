"""Whisper word-level transcription.

Wraps mlx-whisper and normalises the output to our `Transcript` contract.
Uses a GENERIC initial_prompt per language (see INTERFACE.md v1.1) that
biases the decoder toward form-preservation without injecting domain
content. Callers may extend the prompt with entity hints derived from
sources (those come from sources.py, never from hardcoded lists).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import Segment, Transcript, Word


# Language-agnostic style prompts. NO domain terms, no brands.
# Each entry biases the decoder toward preserving proper nouns, numbers,
# and tool/brand names as spoken — without telling the model WHICH ones.
GENERIC_PROMPTS: dict[str, str] = {
    "es": (
        "Transcripción en español. Mantén nombres propios, marcas, "
        "herramientas, números y términos técnicos con la forma más "
        "probable. No traduzcas nombres de productos. Conserva siglas "
        "y cifras."
    ),
    "en": (
        "English transcription. Preserve proper nouns, brand names, "
        "tools, numbers, and technical terms in their most likely form. "
        "Do not translate product names. Keep acronyms and figures."
    ),
}


def build_initial_prompt(
    language: str = "es",
    entity_hints: list[str] | None = None,
    extra_context: str | None = None,
    max_chars: int = 600,
) -> str:
    """Build a generic+optional-hints initial_prompt.

    `entity_hints` come from sources.py (fetched titles/meta) — never
    from a hardcoded project list. `extra_context` is an escape hatch
    for callers who really know what they are doing.
    """
    base = GENERIC_PROMPTS.get(language, GENERIC_PROMPTS["en"])
    parts = [base]
    if entity_hints:
        # Join hints into a single natural-language tail
        tail = "Términos mencionados: " + ", ".join(entity_hints) + "."
        parts.append(tail)
    if extra_context:
        parts.append(extra_context)
    prompt = " ".join(parts)
    if len(prompt) > max_chars:
        prompt = prompt[:max_chars].rsplit(" ", 1)[0]
    return prompt


def transcribe(
    audio_path: Path | str,
    model: str = "large-v3",
    language: str | None = None,
    initial_prompt: str | None = None,
    hf_repo: str | None = None,
    condition_on_previous_text: bool = False,
    temperature: float = 0.0,
) -> Transcript:
    """Run mlx-whisper with word timestamps and return a `Transcript`.

    Parameters
    ----------
    audio_path : path to a wav/mp3/m4a/... file. ffmpeg-readable.
    model      : whisper model size (used to pick default HF repo).
    language   : ISO code (e.g. "es", "en"). When ``None`` (default) whisper
        auto-detects the language from the audio. Forcing a wrong code makes
        whisper pseudo-translate on the fly ("spawna", "arguen") and corrupts
        downstream analysis.
    initial_prompt : text injected into the decoder context.
    hf_repo    : override the MLX Hugging Face repo id explicitly.
    condition_on_previous_text : default False — overriding mlx-whisper's
        own default of True. With True, low-confidence segments (silences,
        retakes, noise) ride the previous segment's text and loop into
        hallucinated phrases ("No te dejes nada a nadie" recurring across a
        full minute of silence is the canonical symptom). False breaks the
        chain so each window is decoded fresh.
    temperature : kept at 0.0 for determinism.

    Raises
    ------
    ImportError if mlx-whisper is not installed.
    FileNotFoundError if audio_path is missing.
    """
    import mlx_whisper  # local import: optional dependency

    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(audio_path)

    repo = hf_repo or f"mlx-community/whisper-{model}-mlx"

    kwargs: dict[str, Any] = {
        "path_or_hf_repo": repo,
        "word_timestamps": True,
        "initial_prompt": initial_prompt,
        "condition_on_previous_text": condition_on_previous_text,
        "temperature": temperature,
    }
    if language is not None:
        kwargs["language"] = language
    result: dict[str, Any] = mlx_whisper.transcribe(str(audio_path), **kwargs)

    segments: list[Segment] = []
    duration = 0.0
    for seg in result.get("segments", []):
        words = [
            Word(
                text=str(w.get("word", "")).strip(),
                start_s=float(w["start"]),
                end_s=float(w["end"]),
                probability=w.get("probability"),
            )
            for w in seg.get("words", [])
        ]
        segments.append(
            Segment(
                start_s=float(seg["start"]),
                end_s=float(seg["end"]),
                text=str(seg.get("text", "")).strip(),
                words=words,
                no_speech_prob=seg.get("no_speech_prob"),
            )
        )
        duration = max(duration, float(seg["end"]))

    detected_language = result.get("language") or language or "unknown"
    return Transcript(
        duration_s=duration,
        segments=segments,
        model=model,
        language=detected_language,
    )
