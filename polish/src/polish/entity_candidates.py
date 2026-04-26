"""Detect possible entities / suspicious tokens in a transcript.

Detects — does NOT correct. Emits a list of candidates that the
entity_resolution layer (LLM + grounding) uses to decide canonical
form. This module is 100% deterministic and has no domain knowledge.

Heuristics (language-agnostic):
1. Acronyms: 2-6 consecutive uppercase letters (e.g. typical 3-letter acronym).
2. Mid-sentence capitalisation: Capitalised token not at sentence start.
3. Version-like: token adjacent to a number or version separator
   (e.g. "<Word> 3.6", "<Acronym>-5.5").
4. CamelCase: mixed upper+lower within a token (e.g. "MixedCaseName").
5. Repeated-variant: same stem appearing with different casings across
   the transcript (hint of inconsistent transcription).
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from .contracts import Transcript, Word

EvidenceType = Literal[
    "acronym",
    "midsentence_capital",
    "version_adjacent",
    "camelcase",
    "repeated_variant",
]


@dataclass
class EntityCandidate:
    surface_form: str                        # token as it appears
    positions: list[tuple[int, int]] = field(default_factory=list)  # (seg_idx, word_idx)
    evidence_types: set[EvidenceType] = field(default_factory=set)
    first_time_s: float = 0.0
    occurrences: int = 0


# ── Helpers ────────────────────────────────────────────────────────

_RE_ACRONYM = re.compile(r"^[A-Z]{2,6}$")
_RE_VERSION_LIKE = re.compile(r"^\d+(\.\d+)*$")
_RE_ALPHANUM = re.compile(r"^[A-Za-z0-9\-]+$")

_SENTENCE_END = {".", "?", "!", "…"}


def _strip_punct(token: str) -> str:
    return token.strip(".,;:!?¡¿\"'()[]{}…").strip()


def _is_acronym(token: str) -> bool:
    return bool(_RE_ACRONYM.match(token))


def _is_camelcase(token: str) -> bool:
    """Mixed upper+lower inside the token (not just a capitalised start)."""
    if len(token) < 2:
        return False
    has_upper_inside = any(c.isupper() for c in token[1:])
    has_lower = any(c.islower() for c in token)
    return has_upper_inside and has_lower


def _is_version_token(token: str) -> bool:
    return bool(_RE_VERSION_LIKE.match(token))


def _is_capitalised(token: str) -> bool:
    return bool(token) and token[0].isupper() and any(c.islower() for c in token[1:])


def _normalise_stem(token: str) -> str:
    """Casefold + strip diacritics for repeated-variant comparison."""
    decomposed = unicodedata.normalize("NFD", token.casefold())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


# ── Main detector ──────────────────────────────────────────────────

def detect_entity_candidates(transcript: Transcript) -> list[EntityCandidate]:
    """Flatten transcript, walk once, emit candidates with evidence."""
    # Flatten for walking with a "previous token ended a sentence" flag
    items: list[tuple[int, int, Word]] = []
    for s_idx, seg in enumerate(transcript.segments):
        for w_idx, w in enumerate(seg.words):
            items.append((s_idx, w_idx, w))

    by_surface: dict[str, EntityCandidate] = {}

    prev_ended_sentence = True  # very first token counts as sentence-start
    for idx, (s_idx, w_idx, w) in enumerate(items):
        raw = w.text
        token = _strip_punct(raw)
        if not token:
            prev_ended_sentence = raw.strip() in _SENTENCE_END or False
            continue

        evidences: set[EvidenceType] = set()

        # Acronym
        if _is_acronym(token):
            evidences.add("acronym")
        # CamelCase
        if _is_camelcase(token):
            evidences.add("camelcase")
        # Mid-sentence capitalisation
        if _is_capitalised(token) and not prev_ended_sentence:
            evidences.add("midsentence_capital")
        # Version-adjacent: this token or the neighbour is version-like.
        # Only add this evidence if the token ALSO qualifies by another
        # criterion (capitalised, acronym, camelcase). Otherwise "de",
        # "tiene", "mil" adjacent to numbers pollute the list.
        neighbour_version = False
        if idx > 0:
            neighbour_version |= _is_version_token(_strip_punct(items[idx - 1][2].text))
        if idx + 1 < len(items):
            neighbour_version |= _is_version_token(_strip_punct(items[idx + 1][2].text))
        token_qualifies = (
            _is_acronym(token)
            or _is_camelcase(token)
            or _is_capitalised(token)
        )
        if neighbour_version and token_qualifies and _RE_ALPHANUM.match(token):
            evidences.add("version_adjacent")

        if evidences:
            cand = by_surface.get(token)
            if cand is None:
                cand = EntityCandidate(
                    surface_form=token,
                    first_time_s=w.start_s,
                )
                by_surface[token] = cand
            cand.positions.append((s_idx, w_idx))
            cand.evidence_types.update(evidences)
            cand.occurrences += 1

        # Update sentence-end flag for next iteration
        last_char = raw.strip()[-1] if raw.strip() else ""
        prev_ended_sentence = last_char in _SENTENCE_END

    # Post-pass: repeated-variant detection
    by_stem: dict[str, list[str]] = defaultdict(list)
    for surface in by_surface:
        by_stem[_normalise_stem(surface)].append(surface)
    for variants in by_stem.values():
        if len(variants) > 1:
            for v in variants:
                by_surface[v].evidence_types.add("repeated_variant")

    return sorted(by_surface.values(), key=lambda c: c.first_time_s)
