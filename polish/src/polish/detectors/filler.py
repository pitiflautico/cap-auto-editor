"""Filler word detector.

Matches a configurable list of filler words/phrases against the
transcript's word-level tokens and emits one CutRegion per match.

Supports multi-word fillers ("o sea", "como que") via sliding n-gram
over the flattened word list.
"""
from __future__ import annotations

import unicodedata

from ..contracts import CutRegion, Transcript, Word

DETECTOR = "filler_es"


def _normalise(text: str) -> str:
    """Lowercase, strip NFD diacritics, drop surrounding punctuation."""
    lowered = text.lower().strip()
    decomposed = unicodedata.normalize("NFD", lowered)
    ascii_only = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    # Trim common punctuation (leading and trailing)
    return ascii_only.strip(".,;:!?¡¿\"'()[]{}…")


def _flat_words(transcript: Transcript) -> list[Word]:
    out: list[Word] = []
    for seg in transcript.segments:
        out.extend(seg.words)
    return out


def detect_fillers(
    transcript: Transcript,
    *,
    filler_words: list[str],
    detector_version: str = "1.0.0",
) -> list[CutRegion]:
    """Emit CutRegion per filler match. Respects multi-word fillers."""
    words = _flat_words(transcript)
    if not words:
        return []

    # Pre-normalise filler terms and bucket by token count
    by_len: dict[int, list[tuple[str, list[str]]]] = {}
    for f in filler_words:
        toks = [_normalise(t) for t in f.split()]
        n = len(toks)
        by_len.setdefault(n, []).append((f, toks))

    # Normalise transcript words once
    norm_words = [_normalise(w.text) for w in words]

    cuts: list[CutRegion] = []
    i = 0
    n_total = len(words)
    # Greedy longest-first match so "o sea" is preferred over "o" + "sea"
    max_len = max(by_len.keys(), default=1)
    while i < n_total:
        matched = False
        for n in range(max_len, 0, -1):
            if i + n > n_total:
                continue
            window = norm_words[i : i + n]
            if window == [""] * n:
                continue
            for original, toks in by_len.get(n, []):
                if window == toks:
                    first = words[i]
                    last = words[i + n - 1]
                    cuts.append(
                        CutRegion(
                            id=f"fil_{len(cuts):03d}",
                            start_s=first.start_s,
                            end_s=last.end_s,
                            reason="filler",
                            detector=DETECTOR,
                            detector_version=detector_version,
                            confidence=0.95,
                            action="cut",
                            affected_words=list(range(i, i + n)),
                            notes=original,
                        )
                    )
                    i += n
                    matched = True
                    break
            if matched:
                break
        if not matched:
            i += 1
    return cuts
