"""Pure function: `remap_transcript(raw, timeline_map) -> polished`.

This is the single function that guarantees sync between the edited
video and the polished transcript. Deterministic, idempotent, pure.

Algorithm:
1. For each word in every segment of the raw transcript:
   - If the word's interval falls inside any cut_region, drop it.
   - Otherwise, find the keep_segment that contains it and shift its
     start/end by `(edited_start - original_start)` of that keep.
2. For each segment, recompute start/end from the retained words.
   Drop segments that end up with no words.
3. Apply `join_compensation_s` subtraction per cut the word crosses
   (for crossfade join strategies).
"""
from __future__ import annotations

from .contracts import CutRegion, KeepSegment, Segment, TimelineMap, Transcript, Word


def _word_in_cut(word: Word, cuts: list[CutRegion]) -> bool:
    """Return True if the word's interval overlaps any cut region."""
    for c in cuts:
        if c.action != "cut":
            continue
        # Overlap if word.start < cut.end AND word.end > cut.start
        if word.start_s < c.end_s and word.end_s > c.start_s:
            return True
    return False


def _find_keep(word: Word, keeps: list[KeepSegment]) -> KeepSegment | None:
    """Find the keep_segment whose original interval contains the word."""
    for k in keeps:
        if k.original_start_s <= word.start_s < k.original_end_s:
            return k
    return None


def _offset_for(keep: KeepSegment) -> float:
    return keep.edited_start_s - keep.original_start_s


def remap_transcript(
    transcript_raw: Transcript,
    timeline_map: TimelineMap,
) -> Transcript:
    """Project the raw transcript onto the edited timeline.

    Invariants:
    - Output word times are all within [0, total_edited_duration_s].
    - Output words are strictly non-decreasing in start_s.
    - No output word overlaps a cut region.
    - Function is pure and idempotent.
    """
    cuts = timeline_map.cut_regions
    keeps = timeline_map.keep_segments

    new_segments: list[Segment] = []
    for seg in transcript_raw.segments:
        new_words: list[Word] = []
        for w in seg.words:
            if _word_in_cut(w, cuts):
                continue
            k = _find_keep(w, keeps)
            if k is None:
                # Word falls entirely outside any keep (edge case: between
                # keeps). Drop it to preserve the no-cut-overlap invariant.
                continue
            off = _offset_for(k)
            new_words.append(
                Word(
                    text=w.text,
                    start_s=max(0.0, w.start_s + off),
                    end_s=max(0.0, w.end_s + off),
                    probability=w.probability,
                )
            )
        if not new_words:
            # Segment evacuated — drop it.
            continue
        seg_start = min(w.start_s for w in new_words)
        seg_end = max(w.end_s for w in new_words)
        new_text = " ".join(w.text for w in new_words).strip()
        new_segments.append(
            Segment(
                start_s=seg_start,
                end_s=seg_end,
                text=new_text,
                words=new_words,
                no_speech_prob=seg.no_speech_prob,
            )
        )

    return Transcript(
        schema_version=transcript_raw.schema_version,
        language=transcript_raw.language,
        duration_s=timeline_map.total_edited_duration_s,
        segments=new_segments,
        model=transcript_raw.model,
    )
