"""Extract keyframes from a video with ffmpeg.

Two strategies:
  - "uniform": N keyframes evenly spaced (default for short clips ≤ 60s).
  - "scenes":  scene-change detection (better for longer videos).

Pure subprocess wrapper. Returns the list of generated jpg paths.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("visual_inventory.keyframes")


def probe_video(path: Path) -> dict:
    """Return ffprobe metadata: duration_s, width, height, fps."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return {}
        data = json.loads(out.stdout)
        fmt = data.get("format", {})
        streams = data.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        try:
            num, den = (v_stream.get("r_frame_rate") or "0/1").split("/")
            fps = float(num) / float(den) if float(den) else 0.0
        except Exception:
            fps = 0.0
        return {
            "duration_s": float(fmt.get("duration") or 0.0),
            "width": int(v_stream.get("width") or 0),
            "height": int(v_stream.get("height") or 0),
            "fps": fps,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return {}


def extract_uniform(
    video: Path,
    out_dir: Path,
    *,
    n_frames: int = 6,
    duration_s: float | None = None,
) -> list[tuple[float, Path]]:
    """Sample ``n_frames`` evenly spaced keyframes (legacy strategy).

    Kept for cases where the editorial brief requires whole-video coverage.
    Default extraction now uses ``extract_initial`` (front-loaded sample).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if duration_s is None:
        duration_s = probe_video(video).get("duration_s") or 0.0
    if duration_s <= 0:
        return []
    n = max(1, n_frames)
    pad = max(0.5, duration_s * 0.05)
    usable = max(0.0, duration_s - 2 * pad)
    if n == 1:
        timestamps = [duration_s / 2]
    else:
        timestamps = [pad + usable * i / (n - 1) for i in range(n)]
    return _grab_frames(video, out_dir, timestamps)


def extract_initial(
    video: Path,
    out_dir: Path,
    *,
    start_s: float = 1.0,
    step_s: float = 5.0,
    max_s: float = 40.0,
    duration_s: float | None = None,
) -> list[tuple[float, Path]]:
    """Front-loaded sampling: keyframes from t=start_s every step_s up to max_s.

    Editorial rationale: official b-roll videos pack the high-impact frames
    (logo reveals, hero shots, key UI screens) in the first 30-40 seconds.
    Sampling the rest is rarely worth a vision LLM call. For a 5-second
    teaser we sample 1 frame; for a 3-minute trailer we still cap at 40s.

    Default: t = 1, 6, 11, 16, 21, 26, 31, 36 → 8 frames over 35s.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if duration_s is None:
        duration_s = probe_video(video).get("duration_s") or 0.0
    if duration_s <= 0:
        return []

    upper = min(duration_s, max_s)
    timestamps: list[float] = []
    t = start_s
    while t <= upper:
        timestamps.append(round(t, 3))
        t += step_s
    if not timestamps:
        timestamps = [min(start_s, max(0.0, duration_s / 2))]
    return _grab_frames(video, out_dir, timestamps)


def _grab_frames(
    video: Path,
    out_dir: Path,
    timestamps: list[float],
) -> list[tuple[float, Path]]:
    out: list[tuple[float, Path]] = []
    for i, t in enumerate(timestamps):
        jpg = out_dir / f"kf_{i:02d}.jpg"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{t:.3f}",
            "-i", str(video),
            "-frames:v", "1",
            "-vf", "scale=640:-1",
            "-q:v", "3",
            str(jpg),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            log.warning("ffmpeg timeout extracting frame at %.2fs from %s", t, video)
            continue
        if r.returncode == 0 and jpg.exists() and jpg.stat().st_size > 256:
            out.append((round(t, 3), jpg))
    return out
