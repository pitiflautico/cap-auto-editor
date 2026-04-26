"""Tests for adaptive silence detection.

Fixture: realistic loudnorm JSON stderr captured from a real run on
myavatar_recording (7).webm (5m24s mono opus audio). The loudnorm pass
measured input_thresh = -33.14 dB (vs the fixed -30.0 dB default).

Real-world effect: 16 silences at -33.14 dB adaptive vs 55 at -30 dB fixed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from polish.detectors.silence import (
    _run_loudnorm,
    _run_silencedetect,
    detect_silences,
    detect_silences_adaptive,
    detect_silences_fixed,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

# Realistic loudnorm stderr (copied from /Volumes/.../analysis/loudnorm.log)
LOUDNORM_STDERR = """\
ffmpeg version 8.0.1 Copyright (c) 2000-2025 the FFmpeg developers
Input #0, matroska,webm, from 'recording.webm':
  Duration: N/A, start: 0.000000, bitrate: N/A
  Stream #0:1(eng): Audio: opus, 48000 Hz, mono, fltp
[opus @ 0x142e05120] Error parsing Opus packet header.
[Parsed_loudnorm_0 @ 0x600000478300]
{
\t"input_i" : "-22.70",
\t"input_tp" : "-0.04",
\t"input_lra" : "3.90",
\t"input_thresh" : "-33.14",
\t"output_i" : "-24.60",
\t"output_tp" : "-2.00",
\t"output_lra" : "4.10",
\t"output_thresh" : "-35.01",
\t"normalization_type" : "dynamic",
\t"target_offset" : "0.60"
}
[out#0/null @ 0x600000478240] video:0KiB audio:121522KiB subtitle:0KiB global headers:0KiB
size=N/A time=00:05:24.12 bitrate=N/A speed=95.2x elapsed=0:00:03.40
"""

# Minimal silencedetect stderr for a 2-silence scenario
SILENCEDETECT_STDERR = """\
[silencedetect @ 0x...] silence_start: 1.500
[silencedetect @ 0x...] silence_end: 2.100 | silence_duration: 0.600
[silencedetect @ 0x...] silence_start: 45.800
[silencedetect @ 0x...] silence_end: 47.200 | silence_duration: 1.400
"""


def _fake_audio(tmp_path: Path) -> Path:
    """Create a dummy file so exists() checks pass."""
    p = tmp_path / "audio.wav"
    p.write_bytes(b"RIFF")
    return p


# ── _run_loudnorm ─────────────────────────────────────────────────────────────

def test_run_loudnorm_parses_input_thresh(tmp_path):
    """_run_loudnorm extracts -33.14 from the realistic stderr fixture."""
    audio = _fake_audio(tmp_path)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = LOUDNORM_STDERR

    with patch("polish.detectors.silence.subprocess.run", return_value=mock_result) as mock_run:
        thresh = _run_loudnorm(audio)

    assert thresh == pytest.approx(-33.14)
    # Verify ffmpeg was called with loudnorm filter
    call_args = mock_run.call_args[0][0]
    assert "loudnorm" in " ".join(call_args)


def test_run_loudnorm_raises_on_missing_json(tmp_path):
    """_run_loudnorm raises RuntimeError if no JSON block in stderr."""
    audio = _fake_audio(tmp_path)
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = "ffmpeg: some output with no JSON block"

    with patch("polish.detectors.silence.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="loudnorm did not emit"):
            _run_loudnorm(audio)


# ── detect_silences_adaptive ──────────────────────────────────────────────────

def test_detect_silences_adaptive_uses_measured_threshold(tmp_path):
    """Adaptive mode uses the loudnorm input_thresh (-33.14) in silencedetect call."""
    audio = _fake_audio(tmp_path)

    call_count = 0
    def fake_subprocess_run(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        mock_result.returncode = 0
        if "loudnorm" in " ".join(cmd):
            mock_result.stderr = LOUDNORM_STDERR
        else:
            mock_result.stderr = SILENCEDETECT_STDERR
        return mock_result

    with patch("polish.detectors.silence.subprocess.run", side_effect=fake_subprocess_run) as mock_run:
        cuts = detect_silences_adaptive(audio, min_duration_s=0.5)

    # Two ffmpeg calls: loudnorm + silencedetect
    assert call_count == 2
    # The silencedetect call should use -33.14 as noise
    second_call_cmd = " ".join(mock_run.call_args_list[1][0][0])
    assert "-33.14" in second_call_cmd

    # Two silence regions parsed
    assert len(cuts) == 2
    assert cuts[0].start_s == pytest.approx(1.5)
    assert cuts[1].start_s == pytest.approx(45.8)


def test_detect_silences_adaptive_cut_region_shape(tmp_path):
    """Each CutRegion has correct fields and action='cut'."""
    audio = _fake_audio(tmp_path)

    def fake_run(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stderr = LOUDNORM_STDERR if "loudnorm" in " ".join(cmd) else SILENCEDETECT_STDERR
        return r

    with patch("polish.detectors.silence.subprocess.run", side_effect=fake_run):
        cuts = detect_silences_adaptive(audio)

    assert all(c.action == "cut" for c in cuts)
    assert all(c.reason == "silence" for c in cuts)
    assert all(c.detector == "ffmpeg_silencedetect" for c in cuts)
    assert all(0.0 <= c.confidence <= 1.0 for c in cuts)


# ── detect_silences() dispatcher ─────────────────────────────────────────────

def test_dispatcher_default_is_adaptive(tmp_path):
    """detect_silences() without mode argument calls adaptive path."""
    audio = _fake_audio(tmp_path)

    call_count = 0
    def fake_run(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        r.returncode = 0
        r.stderr = LOUDNORM_STDERR if "loudnorm" in " ".join(cmd) else SILENCEDETECT_STDERR
        return r

    with patch("polish.detectors.silence.subprocess.run", side_effect=fake_run):
        cuts = detect_silences(audio)

    # Two calls = adaptive (loudnorm + silencedetect)
    assert call_count == 2
    assert len(cuts) == 2


def test_dispatcher_fixed_mode_uses_minus30(tmp_path):
    """detect_silences(mode='fixed') uses -30dB and single ffmpeg call."""
    audio = _fake_audio(tmp_path)

    call_count = 0
    def fake_run(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        r.returncode = 0
        r.stderr = SILENCEDETECT_STDERR
        return r

    with patch("polish.detectors.silence.subprocess.run", side_effect=fake_run) as mock_run:
        cuts = detect_silences(audio, mode="fixed", threshold_db=-30.0)

    assert call_count == 1
    cmd_str = " ".join(mock_run.call_args_list[0][0][0])
    assert "-30.0" in cmd_str
    assert len(cuts) == 2


def test_dispatcher_bad_mode_raises(tmp_path):
    audio = _fake_audio(tmp_path)
    with pytest.raises(ValueError, match="Unknown mode"):
        detect_silences(audio, mode="turbo")  # type: ignore
