"""Storyboard builder — extract one thumbnail per ResolvedAsset.

Pure orchestration. Reads broll_plan_complete.json (post-acquisition) and
optionally the analysis to attach hero_text_candidate to each entry.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .contracts import PreviewKind, Storyboard, StoryboardEntry

log = logging.getLogger("storyboard.builder")


_THUMB_W = 640


def _ffmpeg_frame(video: Path, out_jpg: Path, *, t_s: float) -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{t_s:.3f}", "-i", str(video),
        "-frames:v", "1", "-vf", f"scale={_THUMB_W}:-1",
        "-q:v", "3", str(out_jpg),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return False
    return r.returncode == 0 and out_jpg.exists() and out_jpg.stat().st_size > 256


def _resize_image(src: Path, out_jpg: Path) -> bool:
    """Copy an image scaled to thumb width via PIL."""
    try:
        from PIL import Image       # type: ignore
        with Image.open(src) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w > _THUMB_W:
                new_h = int(h * (_THUMB_W / w))
                im = im.resize((_THUMB_W, new_h), Image.LANCZOS)
            out_jpg.parent.mkdir(parents=True, exist_ok=True)
            im.save(out_jpg, "JPEG", quality=82)
        return out_jpg.exists()
    except Exception as exc:
        log.warning("resize failed for %s: %s", src, exc)
        return False


def _placeholder(text: str, out_jpg: Path) -> bool:
    """Tiny text-card placeholder (640×360) for missing assets."""
    try:
        from PIL import Image, ImageDraw, ImageFont       # type: ignore
    except ImportError:
        return False
    img = Image.new("RGB", (_THUMB_W, 360), "#1d2538")
    draw = ImageDraw.Draw(img)
    font_paths = [
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    f = None
    for fp in font_paths:
        if Path(fp).exists():
            try:
                f = ImageFont.truetype(fp, size=36)
                break
            except Exception:
                continue
    if f is None:
        f = ImageFont.load_default()
    text = (text or "missing")[:60]
    tw = draw.textlength(text, font=f)
    draw.text(((_THUMB_W - tw) / 2, (360 - 36) / 2), text, font=f, fill="#FFFFFF")
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_jpg, "JPEG", quality=82)
    return True


def _midpoint(t_start: float | None, t_end: float | None) -> float:
    if t_start is None and t_end is None:
        return 1.0
    if t_start is None:
        return float(t_end or 0)
    if t_end is None:
        return float(t_start)
    return (float(t_start) + float(t_end)) / 2


def _kind_from_path(p: Path | None, src_kind: str | None) -> PreviewKind:
    """Decide what kind of preview we'll make from a ResolvedAsset row."""
    if not p:
        return "title" if (src_kind == "title") else "missing"
    suf = p.suffix.lower()
    if suf in {".mp4", ".webm", ".mov", ".mkv"}:
        return "video"
    if suf in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        if src_kind == "screenshot":
            return "screenshot"
        if src_kind == "title":
            return "title"
        return "image"
    return "missing"


def build_storyboard(
    broll_plan: dict,
    duration_s: float,
    out_dir: Path,
    *,
    hero_text_by_beat: dict[str, str] | None = None,
    beat_window_by_id: dict[str, tuple[float, float]] | None = None,
) -> Storyboard:
    """Walk every resolved entry, extract one thumb. Returns the Storyboard.

    `hero_text_by_beat` and `beat_window_by_id` come from the balanced
    analysis when available; missing values fallback to "" / 0.
    """
    hero_text_by_beat = hero_text_by_beat or {}
    beat_window_by_id = beat_window_by_id or {}

    sb = Storyboard(
        created_at=datetime.now(timezone.utc),
        duration_s=duration_s,
    )
    thumbs_dir = out_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    resolved = broll_plan.get("resolved") or []
    for r in resolved:
        beat_id = r.get("beat_id", "")
        hi = int(r.get("hint_index", 0))
        bs, be = beat_window_by_id.get(beat_id, (
            float(r.get("beat_start_s") or 0),
            float(r.get("beat_end_s") or 0),
        ))
        abs_path = r.get("abs_path")
        src_kind = r.get("kind")
        p = Path(abs_path) if abs_path else None

        kind = _kind_from_path(p, src_kind)
        thumb_rel = f"thumbs/{beat_id}_{hi}.jpg"
        thumb_abs = out_dir / thumb_rel
        ok = False

        if kind == "video" and p and p.exists():
            t = _midpoint(r.get("t_start_s"), r.get("t_end_s"))
            ok = _ffmpeg_frame(p, thumb_abs, t_s=t)
        elif kind in ("image", "screenshot") and p and p.exists():
            ok = _resize_image(p, thumb_abs)
        elif kind == "title":
            # If there's a real PNG (text_card produced it), reuse; else placeholder
            if p and p.exists() and p.suffix.lower() == ".png":
                ok = _resize_image(p, thumb_abs)
            else:
                txt = r.get("description") or r.get("subject") or "(title)"
                ok = _placeholder(txt, thumb_abs)
        else:
            txt = r.get("description") or r.get("subject") or "(missing)"
            ok = _placeholder(txt, thumb_abs)
            kind = "missing"

        if not ok:
            sb.notes.append(f"{beat_id}#{hi}: thumb generation failed; using fallback")
            _placeholder(r.get("subject") or beat_id, thumb_abs)

        # Read final dims from the saved JPG
        w = h = None
        try:
            from PIL import Image       # type: ignore
            with Image.open(thumb_abs) as im:
                w, h = im.size
        except Exception:
            pass

        sb.entries.append(StoryboardEntry(
            beat_id=beat_id, hint_index=hi,
            beat_start_s=bs, beat_end_s=be,
            type=r.get("type", "title"),
            subject=r.get("subject"),
            hero_text=hero_text_by_beat.get(beat_id),
            description=r.get("description") or "",
            kind=kind,
            thumb_path=thumb_rel,
            source_abs_path=abs_path,
            asset_provider=r.get("source"),
            width=w, height=h,
            duration_s=r.get("duration_s"),
        ))
    return sb
