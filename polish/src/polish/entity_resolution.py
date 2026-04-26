"""LLM-based entity resolution for v6/polish/.

Given a normalized transcript and a list of EntityCandidate objects from
entity_candidates.py, calls the LLM (default: claude_pool / sonnet) to decide
whether each candidate is a real entity that was mis-transcribed.

The LLM is the sole decision-maker. It has:
  - The full transcript for cross-checking.
  - Source text from each capture (title + first ~2000 chars of text.txt).
  - Explicit hard rules to prevent hallucination and numeric-fact corruption.

Output:
  - entity_resolutions.json: full LLM reasoning + decisions for each candidate.
  - list[TranscriptPatch]: patches ready for transcript_patches.apply_patches().

Design principles (from INTERFACE.md v2.2):
  1. "unresolved" is the safe default. Under-correct, never hallucinate.
  2. NEVER correct a numeric magnitude (e.g. "X million" vs "X billion",
     "5%" vs "50%"). That is factual and requires human evidence.
  3. The correction must preserve the speaker's exact meaning — only changes
     orthographic form, not semantics.
  4. If the candidate appears consistently and context gives no signal → unresolved.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .contracts import EntityResolution, EntityResolutionSet, Transcript
from .entity_candidates import EntityCandidate
from .text_normalizer import NormalizationPatch

log = logging.getLogger("entity_resolution")

# ── Prompt constants ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a transcription corrector. Your job is threefold:

A) For each CANDIDATE received, decide whether it is a real entity that was \
mis-transcribed and, if so, what its canonical form is (decision: "canonical" \
or "unresolved").

B) DISCOVER additional entities present in the TRANSCRIPT that the detector \
did NOT include in the candidate list. This covers products, brands, people, \
companies, tools, or technical concepts that the ASR transcribed in lowercase \
or with spelling errors and therefore went undetected. For each one, return \
an entry with decision: "discovered" and the correct canonical. Only discover \
items with SOLID EVIDENCE in the transcript itself or in the sources \
(repeated technical-context use, adjacent version number, cross-mention with \
related products, etc.).

C) Hard rules (non-negotiable, apply to all three categories):
1. If there is no CLEAR EVIDENCE, return "unresolved" or omit the entry. \
NEVER invent a canonical.
2. NEVER correct a numeric magnitude (e.g. "X million" vs "X billion", or \
"5%" vs "50%"). That is factual and requires human evidence.
3. The correction must preserve the speaker's exact meaning — only change \
ORTHOGRAPHIC form, not semantics.
4. If the surface appears consistently and the context does not point to a \
correction, it is probably correct → "unresolved" (or do not discover it).

Output a JSON object with this exact shape:
{
  "resolutions": [
    {
      "surface_form": "<surface as it appears in the transcript>",
      "decision": "canonical" | "unresolved" | "discovered",
      "canonical": "<canonical form when decision in {canonical, discovered}, else null>",
      "confidence": 0.0-1.0,
      "evidence": "<literal quote from transcript or source supporting it, or null>",
      "reasoning": "<one short sentence explaining the decision>"
    }
  ]
}

Write `reasoning` and `evidence` in the SAME LANGUAGE as the transcript \
(matches the {LANG} hint in the user message). The JSON keys and the \
`decision` enum values stay in English.

Do not add text outside the JSON. Do not add explanations. JSON only.\
"""

_TRANSCRIPT_CHAR_LIMIT = 8000
_SOURCE_CHAR_LIMIT = 2000
_TIMESTAMP_EVERY_N_WORDS = 100


def _build_transcript_excerpt(transcript: Transcript) -> str:
    """Flatten transcript to text with timestamps every ~100 words."""
    lines: list[str] = []
    word_count = 0
    for seg in transcript.segments:
        for word in seg.words:
            if word_count % _TIMESTAMP_EVERY_N_WORDS == 0:
                minutes = int(seg.start_s // 60)
                seconds = seg.start_s % 60
                lines.append(f"[t={minutes:02d}:{seconds:05.2f}]")
            lines.append(word.text)
            word_count += 1
    text = " ".join(lines)
    if len(text) > _TRANSCRIPT_CHAR_LIMIT:
        text = text[:_TRANSCRIPT_CHAR_LIMIT] + "…"
    return text


def _build_candidates_block(candidates: list[EntityCandidate]) -> str:
    """Format candidates for the prompt."""
    lines: list[str] = []
    for c in candidates:
        minutes = int(c.first_time_s // 60)
        seconds = c.first_time_s % 60
        ev_str = ", ".join(sorted(c.evidence_types))
        lines.append(
            f"- {c.surface_form} ({c.occurrences} ocurrencias, "
            f"evidence: [{ev_str}], first at {minutes:02d}:{seconds:05.2f})"
        )
    return "\n".join(lines)


def _build_sources_block(capture_manifest_path: Path) -> str:
    """Read capture manifest and format source texts for the prompt."""
    try:
        data = json.loads(capture_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read capture manifest: %s", exc)
        return "(no sources available)"

    out_dir = Path(data.get("out_dir", capture_manifest_path.parent))
    blocks: list[str] = []

    for entry in data.get("results", []):
        if entry.get("status") != "ok":
            continue
        slug = entry["request"]["slug"]
        text_path = out_dir / "captures" / slug / "text.txt"
        try:
            raw = text_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        chunk = raw[:_SOURCE_CHAR_LIMIT]
        blocks.append(f"=== source: {slug} ===\n{chunk}")

    if not blocks:
        return "(no sources available)"
    return "\n\n".join(blocks)


def _build_user_prompt(
    transcript: Transcript,
    candidates: list[EntityCandidate],
    capture_manifest_path: Path | None,
) -> str:
    transcript_text = _build_transcript_excerpt(transcript)
    candidates_text = _build_candidates_block(candidates)
    sources_text = (
        _build_sources_block(capture_manifest_path)
        if capture_manifest_path
        else "(no sources provided)"
    )

    return (
        f"LANG: {transcript.language}\n\n"
        f"TRANSCRIPT (timestamps every ~{_TIMESTAMP_EVERY_N_WORDS} words):\n"
        f"{transcript_text}\n\n"
        f"DETECTED CANDIDATES (surface forms with occurrences and evidence types):\n"
        f"{candidates_text}\n\n"
        f"SOURCES SUPPLIED BY THE CREATOR (title + first {_SOURCE_CHAR_LIMIT} chars of each text.txt):\n"
        f"{sources_text}\n\n"
        f"Proceed. Remember: write `reasoning` and `evidence` in {transcript.language}."
    )


# ── Patch builder ─────────────────────────────────────────────────────────────

def _count_occurrences(transcript: Transcript, surface: str) -> int:
    """Count case-insensitive whole-word occurrences of `surface` across the
    transcript. Used to size patches for entities the detector did not flag."""
    import re as _re
    pattern = _re.compile(
        r"(?<![\w])" + _re.escape(surface) + r"(?![\w])",
        flags=_re.IGNORECASE,
    )
    n = 0
    for seg in transcript.segments:
        n += len(pattern.findall(seg.text))
    return n


def _resolution_to_patches(
    resolutions: list[dict[str, Any]],
    candidates: list[EntityCandidate],
    transcript: Transcript,
) -> list[NormalizationPatch]:
    """Convert LLM resolutions to NormalizationPatch list.

    "canonical" → patch sized by the candidate's known occurrences.
    "discovered" → patch sized by counting the surface in the transcript
                   (the detector never saw it, so no occurrence count exists).
    "unresolved" / null canonical / canonical == surface → no patch.
    """
    by_cand_surface: dict[str, EntityCandidate] = {c.surface_form: c for c in candidates}
    patches: list[NormalizationPatch] = []

    for r in resolutions:
        surface = r.get("surface_form")
        if not surface:
            continue
        decision = r.get("decision")
        if decision not in ("canonical", "discovered"):
            continue
        canonical = r.get("canonical")
        if not canonical or canonical == surface:
            continue

        cand = by_cand_surface.get(surface)
        if cand is not None:
            occurrences = cand.occurrences
        else:
            occurrences = _count_occurrences(transcript, surface)
            if occurrences == 0:
                # LLM hallucinated a surface that does not exist in the transcript.
                log.warning(
                    "discovered surface %r not found in transcript — skipping patch",
                    surface,
                )
                continue

        patches.append(
            NormalizationPatch(
                layer="entity_resolution_llm",
                rule_type="typo",
                from_=surface,
                to=canonical,
                segment_idx=None,
                word_idx=None,
                occurrences=occurrences,
            )
        )

    return patches


# ── Main entry point ──────────────────────────────────────────────────────────

def resolve_entities(
    transcript: Transcript,
    candidates: list[EntityCandidate],
    capture_manifest_path: Path | None = None,
    provider: str = "claude_pool",
    model: str = "sonnet",
    timeout_s: int = 120,
) -> tuple[list[EntityResolution], list[NormalizationPatch], list[dict[str, Any]]]:
    """Run LLM entity resolution on detected candidates.

    Args:
        transcript:             Normalized transcript (post text_normalizer, pre-cut).
        candidates:             Output of entity_candidates.detect_entity_candidates().
        capture_manifest_path:  Optional path to capture manifest JSON.
                                When provided, source text.txt files are included
                                as context for the LLM.
        provider:               LLM provider (default: "claude_pool").
        model:                  Model name (default: "sonnet" — more reliable than
                                haiku for ambiguous entity disambiguation).
        timeout_s:              LLM call timeout.

    Returns:
        Tuple of:
        - list[EntityResolution]: canonical Pydantic models for resolved entities
          (only those with decision="canonical"). Unresolved entries are omitted.
        - list[NormalizationPatch]: patches ready for apply_patches(). One patch
          per resolved entity.
        - list[dict]: raw LLM resolution dicts (all candidates, canonical + unresolved)
          for writing to entity_resolutions.json.

    Side effects:
        None. Caller is responsible for writing entity_resolutions.json.

    Cost: single LLM call per video. Token usage is logged at INFO level.
    """
    from llm import complete  # imported here to keep polish/ independent if llm is unavailable

    # We always call the LLM, even with zero candidates: it may still discover
    # entities (lowercase products, brands the heuristic detector missed) by
    # reading the transcript directly.

    user_prompt = _build_user_prompt(transcript, candidates, capture_manifest_path)

    log.info(
        "Calling LLM for entity resolution: %d candidates, provider=%s model=%s",
        len(candidates),
        provider,
        model,
    )
    t0 = time.monotonic()
    response = complete(
        prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        provider=provider,  # type: ignore[arg-type]
        model=model,
        timeout_s=timeout_s,
        max_turns=1,
        as_json=True,
        allowed_tools=[],  # pure-text JSON task: no tools
    )
    elapsed = time.monotonic() - t0
    log.info(
        "LLM entity resolution done: success=%s duration=%.1fs",
        response.success,
        elapsed,
    )

    if not response.success:
        log.error("LLM call failed: %s", response.text[-500:])
        return [], [], []

    raw_resolutions: list[dict[str, Any]] = []
    if response.json_data:
        raw_resolutions = response.json_data.get("resolutions", [])
    else:
        log.warning("LLM did not return parseable JSON. Raw output: %s", response.text[:500])

    # Build EntityResolution Pydantic models for canonical + discovered decisions
    entity_resolutions: list[EntityResolution] = []
    for r in raw_resolutions:
        if r.get("decision") not in ("canonical", "discovered"):
            continue
        canonical = r.get("canonical")
        if not canonical:
            continue
        entity_resolutions.append(
            EntityResolution(
                canonical=canonical,
                surface_forms=[r["surface_form"]],
                confidence=float(r.get("confidence", 0.5)),
                source_url=None,
                confirmed_by="llm",
            )
        )

    patches = _resolution_to_patches(raw_resolutions, candidates, transcript)

    log.info(
        "Entity resolution: %d canonical, %d unresolved, %d patches",
        len(entity_resolutions),
        len(raw_resolutions) - len(entity_resolutions),
        len(patches),
    )

    return entity_resolutions, patches, raw_resolutions
