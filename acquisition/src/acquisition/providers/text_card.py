"""text_card — generate a still PNG (or .mp4 loop) with the hint's hero text.

Last-resort provider: never fails. PIL renders a 1080×1920 frame with the
subject (or hint description) centred, white text on dark gradient bg,
brand-neutral. ffmpeg loops it into a short .mp4 when type=video.

Falls back to .png when ffmpeg isn't available — the compositor can
display a static image.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import textwrap
from pathlib import Path

log = logging.getLogger("acquisition.text_card")


_DEFAULT_SIZE = (1080, 1920)        # 9:16 portrait
_FONT_SIZES = (96, 72, 60)           # try, descending
_BG_GRADIENT = ("#0e1320", "#1d2538")
_TEXT_COLOR = "#FFFFFF"


def _wrap(text: str, max_chars_per_line: int = 22) -> list[str]:
    text = (text or "").strip()
    if not text:
        return ["(no subject)"]
    return textwrap.wrap(text, width=max_chars_per_line)[:4] or [text[:max_chars_per_line]]


def _render_png(text: str, out: Path,
                size: tuple[int, int] = _DEFAULT_SIZE) -> Path:
    from PIL import Image, ImageDraw, ImageFont   # type: ignore

    w, h = size
    # Dark vertical gradient
    img = Image.new("RGB", (w, h), _BG_GRADIENT[0])
    top = _hex_to_rgb(_BG_GRADIENT[0])
    bot = _hex_to_rgb(_BG_GRADIENT[1])
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        ImageDraw.Draw(img).line([(0, y), (w, y)], fill=(r, g, b))

    draw = ImageDraw.Draw(img)
    lines = _wrap(text)

    # Pick a font size that fits
    font_path = _find_font()
    chosen_font = None
    for fs in _FONT_SIZES:
        f = _load_font(font_path, fs)
        widths = [draw.textlength(line, font=f) for line in lines]
        if max(widths) < w * 0.85:
            chosen_font = f
            break
    if chosen_font is None:
        chosen_font = _load_font(font_path, _FONT_SIZES[-1])

    bbox_h = chosen_font.size * len(lines) * 1.15
    y = (h - bbox_h) / 2
    for line in lines:
        tw = draw.textlength(line, font=chosen_font)
        # Drop shadow for legibility on any bg
        draw.text(((w - tw) / 2 + 3, y + 3), line, font=chosen_font, fill="#000000")
        draw.text(((w - tw) / 2, y), line, font=chosen_font, fill=_TEXT_COLOR)
        y += chosen_font.size * 1.15

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


def _hex_to_rgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _find_font() -> str | None:
    """Pick a bold sans font available on macOS / Linux."""
    for cand in (
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Helvetica.ttc",
    ):
        if Path(cand).exists():
            return cand
    return None


def _load_font(path: str | None, size: int):
    from PIL import ImageFont   # type: ignore
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _png_to_mp4_loop(png: Path, mp4: Path, duration_s: float = 4.0) -> bool:
    """Loop a still image into a short mp4 (silent)."""
    if shutil.which("ffmpeg") is None:
        return False
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(png),
        "-t", f"{duration_s:.2f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", "30",
        "-vf", "scale=1080:1920:flags=lanczos",
        str(mp4),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False
    return r.returncode == 0 and mp4.exists() and mp4.stat().st_size > 1024


def generate(
    text: str,
    out_dir: Path,
    *,
    name: str = "card",
    as_video: bool = False,
    duration_s: float = 4.0,
) -> tuple[Path, str, float | None]:
    """Render a text card. Returns (path, kind, duration_s).

    kind is "title" when ``as_video`` is False (returns the PNG), "video"
    when as_video is True and ffmpeg succeeded loop-encoding it.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{name}.png"
    _render_png(text, png)
    if not as_video:
        return png, "title", None
    mp4 = out_dir / f"{name}.mp4"
    if _png_to_mp4_loop(png, mp4, duration_s=duration_s):
        return mp4, "video", duration_s
    # ffmpeg unavailable → fall back to the still
    return png, "title", None
