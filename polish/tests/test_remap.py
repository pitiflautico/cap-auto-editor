"""Invariants of `remap_transcript`.

If these tests pass, the sync between edited video and polished
transcript is guaranteed by construction (Phase 0 core promise).
"""
from __future__ import annotations

from datetime import datetime

from polish.contracts import (
    CutRegion,
    KeepSegment,
    Segment,
    TimelineMap,
    Transcript,
    Word,
)
from polish.remap import remap_transcript


def _cut(cid: str, start: float, end: float) -> CutRegion:
    return CutRegion(
        id=cid,
        start_s=start,
        end_s=end,
        reason="silence",
        detector="test",
        detector_version="1.0.0",
        confidence=0.9,
        action="cut",
    )


def _keep(os: float, oe: float, es: float, ee: float, before: list[str] | None = None) -> KeepSegment:
    return KeepSegment(
        original_start_s=os,
        original_end_s=oe,
        edited_start_s=es,
        edited_end_s=ee,
        source_cut_ids_before=before or [],
    )


def _transcript(words: list[tuple[str, float, float]]) -> Transcript:
    ws = [Word(text=t, start_s=s, end_s=e) for (t, s, e) in words]
    seg = Segment(
        start_s=min(w.start_s for w in ws),
        end_s=max(w.end_s for w in ws),
        text=" ".join(w.text for w in ws),
        words=ws,
    )
    return Transcript(
        duration_s=seg.end_s,
        segments=[seg],
    )


def _tm(cuts: list[CutRegion], keeps: list[KeepSegment], edit_dur: float) -> TimelineMap:
    return TimelineMap(
        created_at=datetime(2026, 4, 24),
        source_video_path="/tmp/in.mp4",
        transcript_original_ref="raw.json",
        cut_regions=cuts,
        keep_segments=keeps,
        total_original_duration_s=100.0,
        total_edited_duration_s=edit_dur,
    )


# ── Base case: no cuts ─────────────────────────────────────────────

def test_no_cuts_no_changes():
    raw = _transcript([("hola", 0.0, 0.5), ("mundo", 0.5, 1.0)])
    tm = _tm(
        cuts=[],
        keeps=[_keep(0, 100, 0, 100)],
        edit_dur=100.0,
    )
    out = remap_transcript(raw, tm)
    assert len(out.segments) == 1
    assert [w.text for w in out.segments[0].words] == ["hola", "mundo"]
    assert out.segments[0].words[0].start_s == 0.0


# ── Single cut drops the affected words ────────────────────────────

def test_cut_drops_words_inside():
    raw = _transcript([
        ("uno", 0.0, 0.5),
        ("dos", 0.5, 1.0),
        ("tres", 2.0, 2.5),  # This one lies inside the cut [1.0, 2.0]
        ("cuatro", 2.5, 3.0),
    ])
    cut = _cut("c1", 1.0, 2.0)
    # word "tres" at [2.0, 2.5] is NOT inside [1.0, 2.0] — it starts
    # exactly at the cut end. Use a stricter case:
    raw2 = _transcript([
        ("uno", 0.0, 0.5),
        ("dos", 0.5, 1.0),
        ("muletilla", 1.2, 1.7),  # inside the cut
        ("tres", 2.5, 3.0),
    ])
    tm = _tm(
        cuts=[cut],
        keeps=[
            _keep(0.0, 1.0, 0.0, 1.0),
            _keep(2.0, 3.0, 1.0, 2.0, before=["c1"]),
        ],
        edit_dur=2.0,
    )
    out = remap_transcript(raw2, tm)
    texts = [w.text for seg in out.segments for w in seg.words]
    assert "muletilla" not in texts
    assert texts == ["uno", "dos", "tres"]


# ── Times in the edited transcript fall within [0, edit_dur] ───────

def test_times_in_edited_bounds():
    raw = _transcript([
        ("a", 0.0, 0.5),
        ("b", 5.0, 5.5),
        ("c", 20.0, 20.5),
    ])
    tm = _tm(
        cuts=[_cut("c1", 1.0, 4.0), _cut("c2", 6.0, 19.0)],
        keeps=[
            _keep(0.0, 1.0, 0.0, 1.0),
            _keep(4.0, 6.0, 1.0, 3.0, before=["c1"]),
            _keep(19.0, 25.0, 3.0, 9.0, before=["c1", "c2"]),
        ],
        edit_dur=9.0,
    )
    out = remap_transcript(raw, tm)
    for seg in out.segments:
        for w in seg.words:
            assert 0.0 <= w.start_s < out.duration_s
            assert w.end_s <= out.duration_s
            assert w.end_s >= w.start_s


# ── Monotonicity: start times non-decreasing ───────────────────────

def test_words_monotonic_after_remap():
    raw = _transcript([
        ("x", 0.0, 0.5),
        ("y", 10.0, 10.5),
        ("z", 20.0, 20.5),
    ])
    tm = _tm(
        cuts=[_cut("c1", 1.0, 9.0), _cut("c2", 11.0, 19.0)],
        keeps=[
            _keep(0.0, 1.0, 0.0, 1.0),
            _keep(9.0, 11.0, 1.0, 3.0, before=["c1"]),
            _keep(19.0, 25.0, 3.0, 9.0, before=["c1", "c2"]),
        ],
        edit_dur=9.0,
    )
    out = remap_transcript(raw, tm)
    all_starts = [w.start_s for seg in out.segments for w in seg.words]
    assert all_starts == sorted(all_starts)


# ── Idempotence: remap(remap(x)) == remap(x) ───────────────────────

def test_idempotent():
    raw = _transcript([
        ("uno", 0.0, 0.5),
        ("filler", 1.2, 1.5),
        ("dos", 2.0, 2.5),
    ])
    tm = _tm(
        cuts=[_cut("c1", 1.0, 2.0)],
        keeps=[
            _keep(0.0, 1.0, 0.0, 1.0),
            _keep(2.0, 5.0, 1.0, 4.0, before=["c1"]),
        ],
        edit_dur=4.0,
    )
    once = remap_transcript(raw, tm)
    # Apply an identity timeline on the already-polished transcript:
    noop_tm = _tm(
        cuts=[],
        keeps=[_keep(0.0, 4.0, 0.0, 4.0)],
        edit_dur=4.0,
    )
    twice = remap_transcript(once, noop_tm)
    assert [w.text for seg in once.segments for w in seg.words] == [
        w.text for seg in twice.segments for w in seg.words
    ]


# ── No cuts inside output: any surviving word is outside every cut ──

def test_no_surviving_word_overlaps_cut():
    raw = _transcript([
        ("a", 0.0, 0.3),
        ("b", 0.5, 0.8),
        ("c", 1.2, 1.6),
        ("d", 2.0, 2.3),
    ])
    cut = _cut("c1", 1.0, 1.8)
    tm = _tm(
        cuts=[cut],
        keeps=[
            _keep(0.0, 1.0, 0.0, 1.0),
            _keep(1.8, 5.0, 1.0, 4.2, before=["c1"]),
        ],
        edit_dur=4.2,
    )
    out = remap_transcript(raw, tm)
    surviving_texts = [w.text for seg in out.segments for w in seg.words]
    assert "c" not in surviving_texts  # was inside the cut
    assert "a" in surviving_texts and "b" in surviving_texts and "d" in surviving_texts
