"""Adapter: v6 phase outputs → v4 `visual_plan_resolved.json`.

Pure data, no I/O beyond reading already-loaded dicts. Tested without
the v4 builder so we can verify the mapping in isolation.

Mapping:
  • Each beat in `analysis.narrative.beats` becomes either a
    `presenter` beat (when visual_need=none OR no broll resolved)
    or a `broll_image` / `broll_video` beat (when there's an asset).
    A presenter beat carries no asset; the v4 builder uses
    plan_dict["video_path_h264"] for the source video.
  • If the beat has `hero_text_candidate`, it rides on the broll
    beat as `punch_text` (so the v4 punch layer adds the overlay).
  • All `subtitle_clips[*]` are grouped into phrase-level
    `SubtitleCue`s (max 8 words / 3.5s per phrase, per the v4 spec).
  • Optional MusicCue if a music_path is provided.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

# Phrase grouping for karaoke subtitles (v4 spec §subtitles)
_MAX_WORDS_PER_PHRASE = 8
_MAX_PHRASE_DURATION_S = 3.5


# ── Asset classification ────────────────────────────────────────────


_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".avi", ".mkv"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".gif"}

# Aspect-ratio thresholds (asset_width / asset_height):
#   ≤ 0.7  → already vertical or square-ish, fullscreen fits cleanly
#   0.7-1.5 → moderately horizontal, fullscreen with smoother Ken Burns
#   ≥ 1.5  → ultra-wide, fullscreen would crop ≥66% of the asset →
#            drop to split_bottom (1080×960, ratio 1.125) so the asset
#            shows in proportion in the lower half. The upper half can
#            be a presenter / background.
_RATIO_FULLSCREEN_OK_MAX = 1.5      # above this → split layout


def _probe_asset_dimensions(path: str) -> tuple[int, int] | None:
    """Best-effort (width, height) probe.

    Tries ffprobe for any container (video AND image work); falls
    back to PIL for image-only formats. None when both fail or the
    file is missing — the v4 builder will probe again at build time.

    Imports are lazy so unit tests stay free of ffprobe / Pillow.
    """
    if not os.path.exists(path):
        return None
    import shutil, subprocess
    if shutil.which("ffprobe"):
        try:
            out = subprocess.check_output(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height",
                 "-of", "csv=p=0", path],
                timeout=8,
            )
            parts = out.decode().strip().split(",")
            if len(parts) >= 2 and parts[0] and parts[1]:
                return int(parts[0]), int(parts[1])
        except Exception:
            pass
    try:
        from PIL import Image                # type: ignore
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:
        return None


def _layout_for_aspect(width: int, height: int, requested: str) -> str:
    """Pick a v4-compatible layout based on the asset's aspect ratio.

    Honours an explicit `requested` layout when it's one v4 actually
    knows (`fullscreen` or `split_bottom`). Anything else (`split_top`,
    `split_right`, …) is normalised — `split_top` becomes `split_bottom`
    rather than silently dropping back to fullscreen, which would have
    rendered a half-height card stretched across the full canvas.
    """
    if height <= 0:
        return "fullscreen"
    ratio = width / height
    if requested == "split_top":
        return "split_bottom"
    if requested in ("fullscreen", "split_bottom"):
        return requested
    if ratio >= _RATIO_FULLSCREEN_OK_MAX:
        return "split_bottom"
    return "fullscreen"


def _classify_asset(path: str) -> str:
    """Return the v4 beat type literal — `broll_image` or `broll_video`.

    The v4 builder ALSO infers from extension internally, but we set
    the type proactively so plan dumps are self-explanatory and so
    log lines mention the right kind.
    """
    suf = Path(path).suffix.lower()
    if suf in _VIDEO_EXTS:
        return "broll_video"
    if suf in _IMAGE_EXTS:
        return "broll_image"
    return "broll_image"     # safe default — still renders


# ── Subtitle phrase grouping ────────────────────────────────────────


def _group_subtitle_clips(clips: list[dict]) -> list[dict]:
    """Group word-level clips into v4 SubtitleCue phrases.

    Each output entry is `{"start_s","end_s","words":[{"text",
    "start_ms","end_ms"}]}` where word offsets are RELATIVE to the
    phrase start (the v4 builder expects this).

    A phrase ends when:
      • word count reaches _MAX_WORDS_PER_PHRASE, OR
      • phrase duration would exceed _MAX_PHRASE_DURATION_S, OR
      • a gap > 0.6s separates two consecutive words.
    """
    phrases: list[dict] = []
    current: list[dict] = []
    phrase_start: float | None = None

    def _flush():
        nonlocal current, phrase_start
        if not current or phrase_start is None:
            current = []
            phrase_start = None
            return
        end_s = max(w["end_s"] for w in current)
        words_rel = [
            {
                "text": w["text"],
                "start_ms": int(round((w["start_s"] - phrase_start) * 1000)),
                "end_ms":   int(round((w["end_s"]   - phrase_start) * 1000)),
            }
            for w in current
        ]
        phrases.append({
            "start_s": round(phrase_start, 3),
            "end_s":   round(end_s, 3),
            "words":   words_rel,
        })
        current = []
        phrase_start = None

    last_end_s: float | None = None
    for c in clips:
        text = (c.get("text") or "").strip()
        if not text:
            continue
        s = float(c.get("start_s", 0.0))
        e = float(c.get("end_s", s))
        gap = (s - last_end_s) if last_end_s is not None else 0.0

        # Split conditions
        if phrase_start is None:
            phrase_start = s
        else:
            duration = e - phrase_start
            if (len(current) >= _MAX_WORDS_PER_PHRASE
                    or duration > _MAX_PHRASE_DURATION_S
                    or gap > 0.6):
                _flush()
                phrase_start = s

        current.append({"text": text, "start_s": s, "end_s": e})
        last_end_s = e

    _flush()
    return phrases


# ── Beat builders ───────────────────────────────────────────────────


def _resolved_by_beat(broll_plan: dict) -> dict[str, list[dict]]:
    """Index the `resolved` list by beat_id so we can pair with beats."""
    out: dict[str, list[dict]] = {}
    for r in (broll_plan.get("resolved") or []):
        bid = r.get("beat_id") or ""
        out.setdefault(bid, []).append(r)
    # Sort each beat's hints by hint_index for stable ordering
    for bid in out:
        out[bid].sort(key=lambda r: r.get("hint_index", 0))
    return out


def _beat_for_presenter(beat: dict) -> dict:
    """Emit a presenter beat — talking-head fullscreen with optional
    Ken Burns. The v4 builder pulls the source video from the plan's
    top-level `video_path_h264`, so we don't repeat it per beat.
    """
    return {
        "beat_id": beat["beat_id"],
        "type": "presenter",
        "start_s": float(beat["start_s"]),
        "end_s": float(beat["end_s"]),
        "layout": "fullscreen",
        "matting": False,            # toggled by `--matting` in CLI later
        "motion": "static",          # presenter Ken Burns is opinionated; default static
    }


def _beat_for_broll(beat: dict, resolved: dict, *,
                    promote_punch: bool, suffix: str = "") -> dict:
    """Emit a b-roll beat. If `promote_punch` is True and the beat has
    `hero_text_candidate`, we ride a `punch_text` on the b-roll so the
    v4 punch layer prints the kinetic overlay.

    `suffix` disambiguates the beat_id when one beat carries several
    hints — the v4 builder runs an invariant check that rejects
    duplicate segment / material IDs (UUIDs are determinístic from
    beat_id), so two hints sharing the same beat_id would collide.
    """
    asset = resolved.get("abs_path") or ""
    btype = _classify_asset(asset)
    requested_layout = resolved.get("layout") or "fullscreen"
    dims = _probe_asset_dimensions(asset)
    asset_w, asset_h = (dims if dims else (None, None))
    layout = (_layout_for_aspect(asset_w, asset_h, requested_layout)
              if dims else
              ("split_bottom" if requested_layout == "split_top"
               else (requested_layout if requested_layout in
                     ("fullscreen", "split_bottom") else "fullscreen")))
    out = {
        "beat_id": beat["beat_id"] + (f"_{suffix}" if suffix else ""),
        "type": btype,
        "start_s": float(beat["start_s"]),
        "end_s": float(beat["end_s"]),
        "asset_path": asset,
        "layout": layout,
        "motion": "ken_burns_in",
        "entry_anim": "fade",
    }
    if asset_w is not None:
        out["asset_width"] = asset_w
    if asset_h is not None:
        out["asset_height"] = asset_h
    if resolved.get("kind") == "video" or btype == "broll_video":
        out["asset_duration_us"] = int(
            (resolved.get("duration_s") or 0) * 1_000_000
        ) or None
    if promote_punch:
        hero = (beat.get("hero_text_candidate") or "").strip()
        if hero:
            out["punch_text"] = hero
            out["punch_style"] = _punch_style_for(beat, resolved)
    return out


def _punch_style_for(beat: dict, resolved: dict) -> str:
    """Pick a v4 punch style from the beat's editorial intent.

    The v4 builder accepts {impacto, stat, contexto, cinematic}.

    Order matters here — earlier checks win:
      1. hook beat with high energy → 'impacto'   (the strongest editorial signal)
      2. hero looks like a money / percentage stat → 'stat'
         (must have $ or %; bare digits like "20-yr-old" don't count)
      3. designed kicker / thesis ride-along → 'cinematic'
      4. fallback → 'contexto'
    """
    hero = (beat.get("hero_text_candidate") or "").strip()
    energy = beat.get("energy", "medium")
    # Stat takes priority over impacto when the hero is a metric —
    # a hook beat that says "$4M raised in 24h" is fundamentally a
    # stat card; the impacto style would lose the number's weight.
    has_metric_symbol = any(t in hero for t in ("$", "€", "£", "%"))
    has_compact_metric = any(
        s in hero for s in (" M ", " M.", "M.", "k ", "B ", "K ")
    )
    if has_metric_symbol or has_compact_metric:
        return "stat"
    if beat.get("editorial_function") == "hook" or energy == "high":
        return "impacto"
    if (resolved.get("slide_kind") in ("ranking", "progress", "stat")
            or resolved.get("mockup_kind") in ("kicker", "thesis")):
        return "cinematic"
    return "contexto"


# ── Main entry ──────────────────────────────────────────────────────


def build_visual_plan(
    *,
    analysis: dict,
    broll_plan: dict,
    subtitle_clips: dict,
    presenter_video_path: str,
    background_path: str,
    music_path: str | None = None,
    project_name: str | None = None,
) -> dict:
    """Return the `visual_plan_resolved.json` dict the v4 builder eats.

    The dict is JSON-serialisable; tests assert its shape without
    pulling in the v4 builder.
    """
    duration_s = float(analysis.get("duration_s") or 0.0)
    language = analysis.get("language") or "en"
    beats = (analysis.get("narrative") or {}).get("beats") or []
    by_id = _resolved_by_beat(broll_plan)

    out_beats: list[dict] = []
    for beat in beats:
        bid = beat.get("beat_id") or ""
        hits = by_id.get(bid) or []
        if not hits:
            out_beats.append(_beat_for_presenter(beat))
            continue
        # Multiple b-roll hints on the same beat → emit each as its
        # own beat with the SAME [start_s,end_s] window but a
        # disambiguated beat_id (h0/h1/...) so the v4 builder's
        # invariant check on UUIDs doesn't reject the plan. The
        # builder's broll-track scheduler still handles overlap by
        # assigning the second hint to a different track.
        for hi, r in enumerate(hits):
            suffix = f"h{hi}" if len(hits) > 1 else ""
            out_beats.append(
                _beat_for_broll(beat, r, promote_punch=(hi == 0),
                                 suffix=suffix)
            )

    plan = {
        "name": project_name or analysis.get("run_name") or "v6_compositor",
        "video_path_h264": presenter_video_path,
        "background_path": background_path,
        "duration_s": duration_s,
        "language": language,
        "beats": out_beats,
        "subtitle_cues": _group_subtitle_clips(subtitle_clips.get("clips") or []),
    }
    if music_path:
        plan["music_cue"] = {
            "path": music_path,
            "volume": 0.12,
            "fade_out_dur_s": 3.0,
        }
    return plan
