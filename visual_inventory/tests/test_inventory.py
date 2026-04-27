"""Tests for visual_inventory orchestration (no real ffmpeg, no vision LLM)."""
from __future__ import annotations

from pathlib import Path

import pytest

from visual_inventory.contracts import Keyframe
from visual_inventory.inventory import _segments_from_keyframes


def _kf(t, shot, q=4):
    return Keyframe(t_s=t, thumb_path=f"kf_{int(t):02d}.jpg",
                    description="x", shot_type=shot, quality=q)


def test_segments_one_segment_when_all_same_shot():
    kfs = [_kf(0, "logo_centered"), _kf(2, "logo_centered"), _kf(4, "logo_centered")]
    segs = _segments_from_keyframes(kfs, duration_s=6.0)
    assert len(segs) == 1
    assert segs[0].t_start_s == 0
    assert segs[0].t_end_s == 6.0
    assert segs[0].shot_type == "logo_centered"


def test_segments_split_on_shot_change():
    kfs = [
        _kf(0, "logo_centered"),
        _kf(5, "screen_recording"),
        _kf(10, "screen_recording"),
        _kf(15, "wide"),
    ]
    segs = _segments_from_keyframes(kfs, duration_s=20.0)
    assert len(segs) == 3
    assert segs[0].shot_type == "logo_centered"
    assert segs[1].shot_type == "screen_recording"
    assert segs[2].shot_type == "wide"
    # End of last segment = duration
    assert segs[-1].t_end_s == 20.0


def test_segments_score_proportional_to_quality():
    kfs = [_kf(0, "wide", q=5)]
    segs = _segments_from_keyframes(kfs, duration_s=5.0)
    assert segs[0].score == 1.0
    assert segs[0].quality == 5


def test_segments_empty_when_no_keyframes():
    assert _segments_from_keyframes([], 10.0) == []


def test_extract_initial_timestamps_default():
    """Default policy: t=1, 6, 11, …, capped at 40s."""
    from visual_inventory.keyframe_extractor import extract_initial
    # Mock duration via duration_s arg; we don't need a real video
    # because we only inspect the timestamp generation logic.
    from unittest.mock import patch
    with patch("visual_inventory.keyframe_extractor._grab_frames") as mock_grab:
        mock_grab.return_value = []
        extract_initial(__import__("pathlib").Path("/dev/null"),
                        __import__("pathlib").Path("/tmp"),
                        duration_s=200.0)
        ts = mock_grab.call_args[0][2]
        assert ts == [1.0, 6.0, 11.0, 16.0, 21.0, 26.0, 31.0, 36.0]


def test_extract_initial_short_video_truncates():
    """A 12-second clip yields only [1, 6, 11]."""
    from visual_inventory.keyframe_extractor import extract_initial
    from unittest.mock import patch
    with patch("visual_inventory.keyframe_extractor._grab_frames") as mock_grab:
        mock_grab.return_value = []
        extract_initial(__import__("pathlib").Path("/dev/null"),
                        __import__("pathlib").Path("/tmp"),
                        duration_s=12.0)
        ts = mock_grab.call_args[0][2]
        assert ts == [1.0, 6.0, 11.0]


def test_extract_initial_5s_clip_yields_one_frame():
    from visual_inventory.keyframe_extractor import extract_initial
    from unittest.mock import patch
    with patch("visual_inventory.keyframe_extractor._grab_frames") as mock_grab:
        mock_grab.return_value = []
        extract_initial(__import__("pathlib").Path("/dev/null"),
                        __import__("pathlib").Path("/tmp"),
                        duration_s=5.0)
        ts = mock_grab.call_args[0][2]
        assert ts == [1.0]   # only t=1; next would be 6 > 5


def test_keyframe_pydantic_validates_quality_range():
    """Quality is clamped 1-5; out-of-range coercion is up to vision_analyzer.
    Pydantic itself accepts the int — we don't constrain at schema level so a
    value like 10 reaches downstream where it can be detected."""
    k = Keyframe(t_s=0.0, thumb_path="x.jpg", description="x", quality=4)
    assert k.quality == 4
