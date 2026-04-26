"""postprocess.py — Deterministic quality guards for beat lists.

Ported from V4 transcript_analyze.py postprocess helpers with adaptation:
  - split_long_beats: uses word-level timestamps from transcript segments
    instead of ffmpeg silencedetect (we don't re-run audio here).
  - close_beat_gaps: unchanged from V4.
  - consolidate_consecutive_duplicates: unchanged from V4.
"""
from __future__ import annotations

import re
from typing import Any

from .contracts import Beat


# ── Text helpers ──────────────────────────────────────────────────────────────

def _text_fingerprint(text: str) -> set[str]:
    """Bag-of-words normalised for similarity comparison."""
    tok = re.findall(r"[a-záéíóúñ0-9]{3,}", (text or "").lower())
    stop = {"que", "como", "pero", "para", "por", "con", "sin", "los", "las",
            "una", "uno", "unos", "unas", "del", "esto", "esta", "este",
            "ese", "eso", "aqui", "ahi", "mas", "muy", "hay"}
    return {t for t in tok if t not in stop}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── split_long_beats ──────────────────────────────────────────────────────────

def _find_biggest_word_gap(
    start_s: float,
    end_s: float,
    words: list[dict],
) -> float | None:
    """Find the midpoint of the largest gap between consecutive words
    that fall within [start_s, end_s].

    Returns None if fewer than 2 words found in range.
    """
    in_range = [
        w for w in words
        if w.get("end_s", 0.0) > start_s and w.get("start_s", 0.0) < end_s
    ]
    if len(in_range) < 2:
        return None

    best_gap = 0.0
    best_mid = None
    for i in range(len(in_range) - 1):
        gap_start = in_range[i].get("end_s", 0.0)
        gap_end = in_range[i + 1].get("start_s", 0.0)
        gap = gap_end - gap_start
        if gap > best_gap:
            best_gap = gap
            best_mid = (gap_start + gap_end) / 2.0

    return best_mid


def _text_for_range(start_s: float, end_s: float, segments: list[dict]) -> str:
    parts = [
        s.get("text", "").strip()
        for s in segments
        if s.get("text", "").strip()
        and s.get("end_s", 0.0) > start_s
        and s.get("start_s", 0.0) < end_s
    ]
    return " ".join(parts).strip()


def _make_slice(
    b: Beat,
    start_s: float,
    end_s: float,
    id_suffix: str,
    segments: list[dict],
) -> Beat:
    """Create a sub-beat slice. Preserves transition label for retakes."""
    if b.editorial_function == "transition" and b.text.startswith("("):
        return b.model_copy(update={
            "beat_id": b.beat_id + id_suffix,
            "start_s": start_s,
            "end_s": end_s,
            "hero_text_candidate": None,
        })

    text = _text_for_range(start_s, end_s, segments)
    if not text:
        return b.model_copy(update={
            "beat_id": b.beat_id + id_suffix,
            "start_s": start_s,
            "end_s": end_s,
            "text": "(speaker retakes)",
            "editorial_function": "transition",
            "hero_text_candidate": None,
            "references_topic_ids": [],
        })

    return b.model_copy(update={
        "beat_id": b.beat_id + id_suffix,
        "start_s": start_s,
        "end_s": end_s,
        "text": text,
        "hero_text_candidate": (b.hero_text_candidate if id_suffix == "a" else None),
    })


def split_long_beats(
    beats: list[Beat],
    max_s: float = 12.0,
    silences: list[tuple[float, float]] | None = None,
    segments: list[dict] | None = None,
) -> list[Beat]:
    """Split any beat exceeding max_s duration.

    Split point selection (in order of preference):
      1. Largest word gap within the beat (from transcript word timestamps).
      2. Midpoint of largest silence (if silences list provided).
      3. Arithmetic midpoint (last resort).

    Each split half is re-labeled from transcript segments.
    """
    # Flatten all words from segments for gap detection
    all_words: list[dict] = []
    if segments:
        for seg in segments:
            all_words.extend(seg.get("words", []))

    changed = True
    guard = 0
    while changed and guard < 20:
        changed = False
        guard += 1
        out: list[Beat] = []
        for b in beats:
            dur = b.end_s - b.start_s
            if dur <= max_s:
                out.append(b)
                continue

            # Try word gap first
            mid = _find_biggest_word_gap(b.start_s, b.end_s, all_words)

            # Fall back to silence midpoint
            if mid is None and silences:
                inside = [
                    (s, e) for s, e in silences
                    if s >= b.start_s and e <= b.end_s
                ]
                if inside:
                    best_sil = max(inside, key=lambda se: se[1] - se[0])
                    mid = (best_sil[0] + best_sil[1]) / 2.0

            # Last resort: arithmetic midpoint
            if mid is None:
                mid = (b.start_s + b.end_s) / 2.0

            left = _make_slice(b, b.start_s, mid, "a", segments or [])
            right = _make_slice(b, mid, b.end_s, "b", segments or [])

            # If both slices got the same text, the right one is a retake
            if (left.text and left.text == right.text
                    and left.editorial_function != "transition"):
                right = right.model_copy(update={
                    "text": "(speaker retakes)",
                    "editorial_function": "transition",
                    "hero_text_candidate": None,
                    "references_topic_ids": [],
                })

            out.append(left)
            out.append(right)
            changed = True
        beats = out

    return beats


# ── close_beat_gaps ───────────────────────────────────────────────────────────

def close_beat_gaps(beats: list[Beat], tolerance_s: float = 0.15) -> list[Beat]:
    """Extend each beat's end_s to the next beat's start_s if the gap is
    ≤ tolerance_s, absorbing silences into the preceding beat.

    Also clamps overlaps: if beat[i+1].start_s < beat[i].end_s, advance
    beat[i+1].start_s to beat[i].end_s.
    """
    if not beats:
        return beats

    beats = sorted(beats, key=lambda b: b.start_s)
    out = [beats[0]]
    for b in beats[1:]:
        prev = out[-1]
        gap = b.start_s - prev.end_s
        if gap > 0 and gap <= tolerance_s:
            # Close gap by extending prev
            out[-1] = prev.model_copy(update={"end_s": b.start_s})
        elif b.start_s < prev.end_s - tolerance_s:
            # Overlap: push b forward
            b = b.model_copy(update={"start_s": prev.end_s})
        out.append(b)
    return out


# ── consolidate_consecutive_duplicates ────────────────────────────────────────

def consolidate_consecutive_duplicates(
    beats: list[Beat],
    threshold: float = 0.75,
) -> list[Beat]:
    """Collapse consecutive beats with near-identical text into one.

    Keeps the first beat in each cluster, extending its end_s to cover
    the cluster. Uses Jaccard similarity on bag-of-words fingerprints.
    """
    if len(beats) < 2:
        return beats

    out: list[Beat] = [beats[0]]
    for b in beats[1:]:
        prev = out[-1]
        sim = _jaccard(
            _text_fingerprint(prev.text),
            _text_fingerprint(b.text),
        )
        adjacent = (b.start_s - prev.end_s) <= 0.5
        if sim >= threshold and adjacent:
            out[-1] = prev.model_copy(update={"end_s": b.end_s})
            continue
        out.append(b)

    return out
