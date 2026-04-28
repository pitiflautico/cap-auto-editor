"""Build the timed CompositionPlan from broll + subtitles + analysis.

Pure-data transform — no I/O beyond reading already-loaded dicts. The
HTML emitter (in `html.py`) consumes a `CompositionPlan` and produces
the index.html that HyperFrames renders. Splitting the two means we
can unit-test the timing logic without depending on the markup format.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from .contracts import CompositionLayer, CompositionPlan

log = logging.getLogger("compositor.builder")


_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _classify_asset(path: str) -> str:
    """Return the kind tag the HTML builder switches on. Defaults to
    `image` because that's the safest fallback (still rendering)."""
    suf = Path(path).suffix.lower()
    if suf in _VIDEO_EXTS:
        return "video"
    if suf in _IMAGE_EXTS:
        return "image"
    return "image"


def _absolute_to_relative(abs_path: str, project_root: Path) -> str:
    """Try to express `abs_path` relative to the project root that
    HyperFrames will see. If the asset is outside the project, fall
    back to the absolute file:// URL — but for video tags HyperFrames'
    headless Chromium fails to load metadata across origins, so the
    cli stages assets as symlinks inside the project before calling
    this. Treat the file:// fallback as a last resort.
    """
    p = Path(abs_path)
    try:
        return str(p.relative_to(project_root))
    except ValueError:
        return p.as_uri()


def stage_assets(
    *,
    broll_plan: dict,
    audio_abs_path: Path | None,
    project_root: Path,
) -> tuple[dict, Path | None]:
    """Materialise every external asset as a symlink under
    `<project_root>/assets/` so HyperFrames sees same-origin URLs.

    Returns a copy of `broll_plan` whose `resolved[*].abs_path` points
    to the staged copy, and the new audio path (also under assets/).
    Symlinks rather than copies — these are bulky video files.
    """
    assets_dir = project_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    new_plan = {**broll_plan, "resolved": []}
    used_names: set[str] = set()

    for r in (broll_plan.get("resolved") or []):
        abs_path = r.get("abs_path")
        if not abs_path:
            new_plan["resolved"].append(r)
            continue
        src = Path(abs_path)
        if not src.exists():
            new_plan["resolved"].append(r)
            continue
        beat = r.get("beat_id") or "b???"
        idx = r.get("hint_index", 0)
        ext = src.suffix.lower() or ".bin"
        base = f"{beat}_{idx}{ext}"
        # Avoid name collisions across hints with the same id
        i = 1
        name = base
        while name in used_names:
            stem = f"{beat}_{idx}_{i}"
            name = f"{stem}{ext}"
            i += 1
        used_names.add(name)
        link = assets_dir / name
        if link.exists() or link.is_symlink():
            link.unlink()
        try:
            link.symlink_to(src.resolve())
        except OSError:
            # Fallback to file copy on filesystems without symlink support
            import shutil
            shutil.copy2(src, link)
        new_r = {**r, "abs_path": str(link)}
        new_plan["resolved"].append(new_r)

    # Audio — same idea, named explicitly so the HTML can reference it
    new_audio: Path | None = None
    if audio_abs_path is not None:
        a = Path(audio_abs_path)
        if a.exists():
            link = assets_dir / f"audio{a.suffix.lower()}"
            if link.exists() or link.is_symlink():
                link.unlink()
            try:
                link.symlink_to(a.resolve())
            except OSError:
                import shutil
                shutil.copy2(a, link)
            new_audio = link
    return new_plan, new_audio


def _broll_window(beat_start_s: float, beat_end_s: float,
                  in_pct: float, out_pct: float,
                  fallback_min_dur_s: float) -> tuple[float, float]:
    """Resolve a beat-relative timing into absolute seconds.

    Each hint declares a `timing.in_pct/out_pct` (0–1 of beat) — we
    map that onto the beat window. If the resulting window is below
    `fallback_min_dur_s` we extend it (the LLM occasionally emits
    in_pct=out_pct on punchline reveals).
    """
    dur = max(0.0, beat_end_s - beat_start_s)
    s = beat_start_s + dur * max(0.0, min(1.0, in_pct))
    e = beat_start_s + dur * max(0.0, min(1.0, out_pct))
    if e - s < fallback_min_dur_s:
        e = min(beat_end_s, s + fallback_min_dur_s)
    return s, e


def build_plan(
    *,
    broll_plan: dict,
    subtitle_clips: dict,
    duration_s: float,
    beat_window_by_id: dict[str, tuple[float, float]],
    project_root: Path,
    audio_abs_path: Path | None = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    min_broll_window_s: float = 0.6,
) -> CompositionPlan:
    """Assemble layers from the upstream phase outputs.

    Args:
        broll_plan: parsed broll_plan_complete.json (from acquisition).
        subtitle_clips: parsed subtitle_clips.json (from subtitler).
        duration_s: total video duration.
        beat_window_by_id: {beat_id: (start_s, end_s)} — usually from
            analysis_with_broll or analysis_balanced narrative.beats.
        project_root: directory that becomes HyperFrames' cwd. Asset
            paths inside it are emitted relative; outside paths fall
            back to absolute file:// URLs.
        audio_abs_path: optional override for the audio track. If None
            we look for a sibling `audio.wav` in project_root.

    Returns the fully populated CompositionPlan.
    """
    notes: list[str] = []
    layers: list[CompositionLayer] = []

    # ── b-roll layers ──────────────────────────────────────────────
    for r in (broll_plan.get("resolved") or []):
        beat_id = r.get("beat_id") or ""
        win = beat_window_by_id.get(beat_id)
        if win is None:
            # Fall back to the broll_plan's own beat window if upstream
            # didn't pass an analysis (e.g. unit tests).
            bs = float(r.get("beat_start_s") or 0.0)
            be = float(r.get("beat_end_s") or 0.0)
            win = (bs, be)
        bs, be = win
        if be <= bs:
            notes.append(f"{beat_id}: empty beat window — skipped")
            continue
        abs_path = r.get("abs_path")
        if not abs_path:
            notes.append(f"{beat_id}: no abs_path — skipped")
            continue
        in_pct = float((r.get("timing") or {}).get("in_pct", 0.0))
        out_pct = float((r.get("timing") or {}).get("out_pct", 1.0))
        s, e = _broll_window(bs, be, in_pct, out_pct,
                              fallback_min_dur_s=min_broll_window_s)
        kind = _classify_asset(abs_path)
        layers.append(CompositionLayer(
            kind="broll",
            start_s=round(s, 3), end_s=round(e, 3),
            asset_rel=_absolute_to_relative(abs_path, project_root),
            asset_kind=kind,
            layout=(r.get("layout") or "fullscreen"),
            beat_id=beat_id,
        ))

    # ── subtitle layers ────────────────────────────────────────────
    for c in (subtitle_clips.get("clips") or []):
        text = (c.get("text") or "").strip()
        if not text:
            continue
        layers.append(CompositionLayer(
            kind="subtitle",
            start_s=round(float(c.get("start_s", 0.0)), 3),
            end_s=round(float(c.get("end_s", 0.0)), 3),
            text=text,
        ))

    # ── audio (single track for the whole video) ───────────────────
    audio_rel: str | None = None
    if audio_abs_path is not None and Path(audio_abs_path).exists():
        audio_rel = _absolute_to_relative(str(audio_abs_path), project_root)
    else:
        candidate = project_root / "audio.wav"
        if candidate.exists():
            audio_rel = "audio.wav"
        else:
            notes.append("no audio.wav located — final.mp4 will be silent")

    return CompositionPlan(
        created_at=datetime.now(timezone.utc),
        duration_s=duration_s,
        width=width, height=height, fps=fps,
        audio_rel=audio_rel,
        layers=layers,
        notes=notes,
    )


def beat_windows_from_analysis(analysis: dict) -> dict[str, tuple[float, float]]:
    """Pull (beat_id → start/end) out of an analysis dict (any of the
    enriched variants — schema is stable across them)."""
    out: dict[str, tuple[float, float]] = {}
    for b in (analysis.get("narrative") or {}).get("beats") or []:
        bid = b.get("beat_id")
        if bid:
            out[bid] = (
                float(b.get("start_s", 0.0)),
                float(b.get("end_s", 0.0)),
            )
    return out
