"""test_postprocess.py — Unit tests for deterministic postprocess guards."""
from __future__ import annotations

import pytest

from analysis.contracts import Beat
from analysis.postprocess import (
    close_beat_gaps,
    consolidate_consecutive_duplicates,
    split_long_beats,
)


def _beat(beat_id: str, start_s: float, end_s: float, text: str = "test text",
          ef: str = "hook", energy: str = "medium") -> Beat:
    return Beat(
        beat_id=beat_id,
        start_s=start_s,
        end_s=end_s,
        text=text,
        editorial_function=ef,
        hero_text_candidate=None,
        energy=energy,
        references_topic_ids=[],
    )


# ── split_long_beats ─────────────────────────────────────────────────────────

def test_split_long_beat_by_word_gap():
    """A 13s beat with a large word gap in the middle should split at that gap."""
    # Beat spans 0-13s. Words: some at 1s-4s, big gap, more at 9s-12s.
    beat = _beat("b001", 0.0, 13.0, "primera parte segunda parte")
    segments = [
        {
            "start_s": 0.0, "end_s": 6.5, "text": "primera parte",
            "words": [
                {"text": "primera", "start_s": 1.0, "end_s": 2.0},
                {"text": "parte", "start_s": 2.0, "end_s": 4.0},
                # gap from 4.0 to 8.0 (4s gap)
            ],
        },
        {
            "start_s": 8.0, "end_s": 13.0, "text": "segunda parte",
            "words": [
                {"text": "segunda", "start_s": 8.0, "end_s": 10.0},
                {"text": "parte", "start_s": 10.0, "end_s": 12.0},
            ],
        },
    ]
    result = split_long_beats([beat], max_s=12.0, segments=segments)
    assert len(result) == 2, f"Expected 2 beats, got {len(result)}"
    assert result[0].end_s == result[1].start_s, "Slices must be contiguous"
    assert result[0].start_s == 0.0
    assert result[1].end_s == 13.0
    # Both slices should be ≤12s
    for b in result:
        assert b.end_s - b.start_s <= 12.0


def test_split_long_beat_no_words_uses_midpoint():
    """When no word timestamps are available, split at the arithmetic midpoint."""
    beat = _beat("b001", 0.0, 14.0, "some text here")
    result = split_long_beats([beat], max_s=12.0, segments=[])
    assert len(result) == 2
    assert abs(result[0].end_s - 7.0) < 0.01  # midpoint of 0-14


def test_short_beats_unchanged():
    beats = [_beat(f"b{i:03d}", i * 5.0, i * 5.0 + 5.0) for i in range(4)]
    result = split_long_beats(beats, max_s=12.0, segments=[])
    assert len(result) == 4


# ── close_beat_gaps ──────────────────────────────────────────────────────────

def test_close_small_gap():
    """A gap of 0.05s (≤ 0.15 tolerance) should be closed by extending prev."""
    beats = [
        _beat("b001", 0.0, 5.0),
        _beat("b002", 5.05, 10.0),  # 0.05s gap
    ]
    result = close_beat_gaps(beats, tolerance_s=0.15)
    assert result[0].end_s == 5.05
    assert result[1].start_s == 5.05


def test_close_large_gap_unchanged():
    """A gap > tolerance should NOT be closed."""
    beats = [
        _beat("b001", 0.0, 5.0),
        _beat("b002", 6.0, 10.0),  # 1.0s gap
    ]
    result = close_beat_gaps(beats, tolerance_s=0.15)
    # Gap should not be closed (1.0 > 0.15)
    assert result[0].end_s == 5.0
    assert result[1].start_s == 6.0


def test_close_overlap():
    """Overlapping beats should be fixed by advancing the later beat's start."""
    beats = [
        _beat("b001", 0.0, 5.5),
        _beat("b002", 5.0, 10.0),  # 0.5s overlap
    ]
    result = close_beat_gaps(beats, tolerance_s=0.15)
    assert result[1].start_s == result[0].end_s


# ── consolidate_consecutive_duplicates ───────────────────────────────────────

def test_consolidate_identical_beats():
    """Two consecutive beats with identical text should collapse into one."""
    text = "este es el mismo texto exactamente igual y tiene bastantes palabras"
    beats = [
        _beat("b001", 0.0, 5.0, text=text),
        _beat("b002", 5.0, 10.0, text=text),
    ]
    result = consolidate_consecutive_duplicates(beats, threshold=0.75)
    assert len(result) == 1
    assert result[0].end_s == 10.0
    assert result[0].beat_id == "b001"


def test_consolidate_different_beats_unchanged():
    """Beats with distinct content should not be collapsed."""
    beats = [
        _beat("b001", 0.0, 5.0, text="primera parte del video con contenido"),
        _beat("b002", 5.0, 10.0, text="segunda parte totalmente diferente aqui"),
    ]
    result = consolidate_consecutive_duplicates(beats, threshold=0.75)
    assert len(result) == 2


def test_consolidate_non_adjacent_not_collapsed():
    """Non-adjacent high-similarity beats (gap > 0.5s) should NOT collapse."""
    text = "contenido similar que se repite bastante en el video"
    beats = [
        _beat("b001", 0.0, 5.0, text=text),
        _beat("b002", 10.0, 15.0, text=text),  # 5s gap → not adjacent
    ]
    result = consolidate_consecutive_duplicates(beats, threshold=0.75)
    assert len(result) == 2
