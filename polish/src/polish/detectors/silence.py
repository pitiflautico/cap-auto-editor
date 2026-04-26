"""Silence detector backed by `ffmpeg silencedetect`.

Emits `CutRegion` candidates; the cut_planner decides cut/keep/compress.

Two modes:
  adaptive (default) — runs loudnorm first to measure input_thresh, then uses
                        that as the noise gate. Adapts per-audio, prevents over-
                        cutting quiet recordings or under-cutting loud ones.
  fixed              — legacy -30dB fixed threshold (behaviour pre-v2.2).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Literal

from ..contracts import CutRegion

DETECTOR = "ffmpeg_silencedetect"

_RE_START = re.compile(r"silence_start:\s*([\d\.]+)")
_RE_END = re.compile(r"silence_end:\s*([\d\.]+)\s*\|\s*silence_duration:\s*([\d\.]+)")
_RE_JSON_BLOCK = re.compile(r"\{[^{}]+\}", re.DOTALL)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_silences(stderr: str, detector_version: str) -> list[CutRegion]:
    """Parse ffmpeg silencedetect stderr into CutRegion list."""
    starts: list[float] = [float(m.group(1)) for m in _RE_START.finditer(stderr)]
    ends: list[tuple[float, float]] = [
        (float(m.group(1)), float(m.group(2)))
        for m in _RE_END.finditer(stderr)
    ]
    cuts: list[CutRegion] = []
    for idx, s in enumerate(starts):
        if idx < len(ends):
            e, dur = ends[idx]
        else:
            # Trailing silence without an end — skip (remap needs duration).
            continue
        cuts.append(
            CutRegion(
                id=f"sil_{idx:03d}",
                start_s=s,
                end_s=e,
                reason="silence",
                detector=DETECTOR,
                detector_version=detector_version,
                confidence=min(1.0, 0.5 + dur / 4.0),  # longer = more confident
                action="cut",
                affected_words=[],
            )
        )
    return cuts


def _run_loudnorm(audio_path: Path) -> float:
    """Run ffmpeg loudnorm analysis and return input_thresh in dB.

    Returns the raw measured input_thresh so silencedetect can use the
    same gate the audio actually has, rather than a fixed -30dB.

    Raises RuntimeError if ffmpeg fails or the JSON block is missing.
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i", str(audio_path),
        "-map", "0:a",
        "-af", "loudnorm=print_format=json",
        "-f", "null",
        "/dev/null",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # loudnorm prints JSON to stderr; non-zero exit is normal when output is /dev/null
    stderr = result.stderr

    # Find the JSON block in stderr
    match = _RE_JSON_BLOCK.search(stderr)
    if not match:
        raise RuntimeError(
            f"loudnorm did not emit a JSON block in stderr.\n"
            f"stderr tail: {stderr[-500:]}"
        )
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse loudnorm JSON: {exc}\nraw: {match.group()}") from exc

    thresh_str = data.get("input_thresh")
    if thresh_str is None:
        raise RuntimeError(f"loudnorm JSON missing 'input_thresh': {data}")

    return float(thresh_str)


def _run_silencedetect(
    audio_path: Path,
    threshold_db: float,
    min_duration_s: float,
) -> str:
    """Run ffmpeg silencedetect and return stderr. Raises on ffmpeg error."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i", str(audio_path),
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration_s}",
        "-f", "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg silencedetect failed (exit {result.returncode}):\n{result.stderr[-500:]}"
        )
    return result.stderr


# ── Public API ────────────────────────────────────────────────────────────────

def detect_silences_adaptive(
    audio_path: Path | str,
    min_duration_s: float = 0.5,
    detector_version: str = "2.2.0",
) -> list[CutRegion]:
    """Adaptive silence detection using loudnorm to calibrate the gate.

    Two ffmpeg passes:
    1. loudnorm analysis → extract input_thresh (audio-specific gate level).
    2. silencedetect with noise=input_thresh dB.

    Returns the same list[CutRegion] as detect_silences_fixed().
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(audio_path)

    threshold_db = _run_loudnorm(audio_path)
    stderr = _run_silencedetect(audio_path, threshold_db, min_duration_s)
    return _parse_silences(stderr, detector_version)


def detect_silences_fixed(
    audio_path: Path | str,
    threshold_db: float = -30.0,
    min_duration_s: float = 0.4,
    detector_version: str = "1.0.0",
) -> list[CutRegion]:
    """Fixed-threshold silence detection (legacy -30dB behaviour pre-v2.2).

    Kept for reproducibility and testing. Use detect_silences() dispatcher
    with mode='fixed' from pipeline code.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(audio_path)

    stderr = _run_silencedetect(audio_path, threshold_db, min_duration_s)
    return _parse_silences(stderr, detector_version)


def detect_silences(
    audio_path: Path | str,
    mode: Literal["adaptive", "fixed"] = "adaptive",
    *,
    # adaptive params
    min_duration_s: float = 0.5,
    # fixed params
    threshold_db: float = -30.0,
    min_duration_s_fixed: float = 0.4,
    detector_version: str | None = None,
) -> list[CutRegion]:
    """Dispatcher: adaptive (default) or fixed silence detection.

    Args:
        audio_path:        Path to audio file.
        mode:              "adaptive" (default) or "fixed".
        min_duration_s:    Minimum silence duration for adaptive mode (s).
        threshold_db:      Noise gate for fixed mode (dB). Default -30.0.
        min_duration_s_fixed: Minimum silence duration for fixed mode (s).
        detector_version:  Override detector_version tag in CutRegion.

    Returns:
        list[CutRegion] ready for cut_planner.plan_cuts().
    """
    if mode == "adaptive":
        ver = detector_version or "2.2.0"
        return detect_silences_adaptive(audio_path, min_duration_s=min_duration_s, detector_version=ver)
    elif mode == "fixed":
        ver = detector_version or "1.0.0"
        return detect_silences_fixed(
            audio_path,
            threshold_db=threshold_db,
            min_duration_s=min_duration_s_fixed,
            detector_version=ver,
        )
    else:
        raise ValueError(f"Unknown mode {mode!r}. Expected 'adaptive' or 'fixed'.")
