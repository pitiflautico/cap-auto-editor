"""text_card — renderizador de slots "diseñados" (title / slide / mockup).

Tres plantillas, 1080×1920 portrait, deterministas (PIL):

  • `title`   — hero text bottom-third con pill negro semi-transparente,
                gradient bg, opcional subtext pequeño debajo. Coincide
                visualmente con el subtitler para que el compositor
                pueda mezclarlo sin saltos de estilo.
  • `slide`   — título arriba + 2-3 bullets stacked (icono ▸), texto
                blanco sobre gradient.
  • `mockup`  — frame de teléfono dibujado con vector simple, texto
                interior. Placeholder hasta que la fase 13 (Remotion)
                renderice el mockup real con la UI del producto.

Cuando `as_video=True` y ffmpeg está disponible, el PNG se loop-encodea
a un .mp4 silente para que el compositor pueda timearlo.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Literal

log = logging.getLogger("acquisition.text_card")


_DEFAULT_SIZE = (1080, 1920)
_BG_GRADIENT = ("#0e1320", "#1d2538")
_TEXT_COLOR = "#FFFFFF"
_ACCENT_COLOR = "#7CFFB2"      # subtle accent for slide bullets
_PILL_COLOR = (0, 0, 0, 192)   # black, alpha 75%

Layout = Literal["title", "slide", "mockup"]


# ── helpers ─────────────────────────────────────────────────────────


def _hex_to_rgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _find_font() -> str | None:
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
    from PIL import ImageFont       # type: ignore
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _draw_gradient(img):
    from PIL import ImageDraw       # type: ignore
    w, h = img.size
    top = _hex_to_rgb(_BG_GRADIENT[0])
    bot = _hex_to_rgb(_BG_GRADIENT[1])
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def _wrap_to_width(text: str, font, draw, max_width: int) -> list[str]:
    """Greedy word-wrap that respects the actual rendered text width."""
    words = (text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        candidate = f"{cur} {w}"
        if draw.textlength(candidate, font=font) <= max_width:
            cur = candidate
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _fit_font(text: str, draw, font_path, size_candidates,
              max_width: int, max_lines: int) -> tuple[object, list[str]]:
    """Pick the largest size from `size_candidates` whose wrapped text
    fits in (max_width × max_lines). Falls back to the smallest."""
    for size in size_candidates:
        f = _load_font(font_path, size)
        lines = _wrap_to_width(text, f, draw, max_width)
        if len(lines) <= max_lines and all(
            draw.textlength(l, font=f) <= max_width for l in lines
        ):
            return f, lines
    f = _load_font(font_path, size_candidates[-1])
    lines = _wrap_to_width(text, f, draw, max_width)
    return f, lines[:max_lines]


# ── renderers ───────────────────────────────────────────────────────


def _render_title(out: Path, hero: str, subtext: str | None) -> Path:
    """Hero text with semi-transparent black pill, anchored bottom-third.
    Mirrors the subtitler style so compositor mixing is seamless.
    """
    from PIL import Image, ImageDraw       # type: ignore

    w, h = _DEFAULT_SIZE
    img = Image.new("RGB", (w, h), _BG_GRADIENT[0])
    _draw_gradient(img)
    draw = ImageDraw.Draw(img, "RGBA")

    fp = _find_font()
    f, lines = _fit_font(
        hero, draw, fp,
        size_candidates=(140, 120, 100, 84, 72),
        max_width=int(w * 0.84), max_lines=3,
    )

    line_h = int(f.size * 1.18)
    block_h = line_h * len(lines)
    y_anchor_norm = 0.72
    y0 = int(h * y_anchor_norm - block_h / 2)

    pad_x, pad_y = 36, 22
    radius = 36

    for i, line in enumerate(lines):
        tw = int(draw.textlength(line, font=f))
        cx = (w - tw) // 2
        cy = y0 + i * line_h
        # Pill background per line (looks like one pill per word/line),
        # consistent with the subtitler word-by-word style.
        draw.rounded_rectangle(
            [cx - pad_x, cy - pad_y // 2, cx + tw + pad_x, cy + line_h - pad_y // 2],
            radius=radius, fill=_PILL_COLOR,
        )
        # Drop-shadow + text
        draw.text((cx + 3, cy + 3), line, font=f, fill="#000000")
        draw.text((cx, cy), line, font=f, fill=_TEXT_COLOR)

    if subtext:
        sub_f = _load_font(fp, 44)
        sub = subtext.strip()
        if len(sub) > 90:
            sub = sub[:87] + "…"
        sub_w = int(draw.textlength(sub, font=sub_f))
        sx = (w - sub_w) // 2
        sy = y0 + block_h + 24
        draw.text((sx + 2, sy + 2), sub, font=sub_f, fill="#000000")
        draw.text((sx, sy), sub, font=sub_f, fill="#C8D4E6")

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


def _render_slide(out: Path, title: str, bullets: list[str]) -> Path:
    """Slide layout: title up top + bullets stacked center."""
    from PIL import Image, ImageDraw       # type: ignore

    w, h = _DEFAULT_SIZE
    img = Image.new("RGB", (w, h), _BG_GRADIENT[0])
    _draw_gradient(img)
    draw = ImageDraw.Draw(img)

    fp = _find_font()
    title_f, title_lines = _fit_font(
        title or "Highlights", draw, fp,
        size_candidates=(96, 84, 72, 60),
        max_width=int(w * 0.86), max_lines=2,
    )
    title_h = int(title_f.size * 1.22)

    y = int(h * 0.18)
    for line in title_lines:
        tw = int(draw.textlength(line, font=title_f))
        cx = (w - tw) // 2
        draw.text((cx + 2, y + 2), line, font=title_f, fill="#000000")
        draw.text((cx, y), line, font=title_f, fill=_TEXT_COLOR)
        y += title_h

    # Underline accent below the title
    line_y = y + 12
    draw.rectangle([(w * 0.30, line_y), (w * 0.70, line_y + 4)], fill=_ACCENT_COLOR)

    bullets = [b.strip() for b in (bullets or []) if b and b.strip()][:3]
    if not bullets:
        bullets = ["—"]

    bullet_f = _load_font(fp, 64)
    bullet_h = int(bullet_f.size * 1.5)
    block_h = bullet_h * len(bullets)
    by = int(h * 0.48 - block_h / 2)

    bullet_x = int(w * 0.10)
    text_x = int(w * 0.16)
    max_text_w = int(w * 0.78)

    for txt in bullets:
        # Wrap each bullet to two lines max
        sub_f, sub_lines = _fit_font(
            txt, draw, fp,
            size_candidates=(64, 56, 48, 42),
            max_width=max_text_w, max_lines=2,
        )
        # Bullet glyph (filled chevron)
        draw.polygon([
            (bullet_x, by + 14),
            (bullet_x + 30, by + sub_f.size // 2 + 14),
            (bullet_x, by + sub_f.size + 14),
        ], fill=_ACCENT_COLOR)
        cy = by
        for line in sub_lines:
            draw.text((text_x + 2, cy + 14 + 2), line, font=sub_f, fill="#000000")
            draw.text((text_x, cy + 14), line, font=sub_f, fill=_TEXT_COLOR)
            cy += int(sub_f.size * 1.18)
        by += max(bullet_h, cy - by + 24)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


def _render_mockup(out: Path, label: str, subtext: str | None) -> Path:
    """Phone-frame placeholder with label + subtext inside. The
    compositor (phase 13) replaces this with a real animated mockup
    once Remotion templates are wired; this keeps the slot non-empty.
    """
    from PIL import Image, ImageDraw       # type: ignore

    w, h = _DEFAULT_SIZE
    img = Image.new("RGB", (w, h), _BG_GRADIENT[0])
    _draw_gradient(img)
    draw = ImageDraw.Draw(img, "RGBA")

    # Phone bezel
    fw = int(w * 0.62)
    fh = int(h * 0.62)
    fx = (w - fw) // 2
    fy = int(h * 0.18)
    bezel = 18
    draw.rounded_rectangle(
        [fx - bezel, fy - bezel, fx + fw + bezel, fy + fh + bezel],
        radius=72, fill="#0a0d16", outline="#FFFFFF", width=4,
    )
    # Screen
    draw.rounded_rectangle(
        [fx, fy, fx + fw, fy + fh],
        radius=56, fill=(20, 26, 42, 255),
    )
    # Notch
    draw.rounded_rectangle(
        [fx + fw // 2 - 80, fy + 14, fx + fw // 2 + 80, fy + 44],
        radius=18, fill="#0a0d16",
    )

    # Label + subtext inside the screen
    fp = _find_font()
    f, lines = _fit_font(
        label or "(mockup)", draw, fp,
        size_candidates=(80, 68, 56, 48),
        max_width=int(fw * 0.86), max_lines=3,
    )
    line_h = int(f.size * 1.2)
    block_h = line_h * len(lines)
    y0 = fy + (fh - block_h) // 2 - 30
    for line in lines:
        tw = int(draw.textlength(line, font=f))
        draw.text((fx + (fw - tw) // 2, y0), line, font=f, fill=_TEXT_COLOR)
        y0 += line_h

    badge_text = "MOCKUP — render in compositor"
    badge_f = _load_font(fp, 28)
    bw = int(draw.textlength(badge_text, font=badge_f))
    bx = (w - bw) // 2
    by = fy + fh + bezel + 30
    draw.rounded_rectangle(
        [bx - 16, by - 8, bx + bw + 16, by + 38],
        radius=18, fill=(255, 255, 255, 36),
    )
    draw.text((bx, by), badge_text, font=badge_f, fill="#9FB0CE")

    if subtext:
        sub_f = _load_font(fp, 36)
        sub = subtext.strip()
        if len(sub) > 80:
            sub = sub[:77] + "…"
        sw = int(draw.textlength(sub, font=sub_f))
        sx = (w - sw) // 2
        sy = by + 70
        draw.text((sx, sy), sub, font=sub_f, fill="#C8D4E6")

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


def _png_to_mp4_loop(png: Path, mp4: Path, duration_s: float = 4.0) -> bool:
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


# ── public API ──────────────────────────────────────────────────────


def generate(
    text: str,
    out_dir: Path,
    *,
    name: str = "card",
    layout: Layout = "title",
    subtext: str | None = None,
    bullets: list[str] | None = None,
    as_video: bool = False,
    duration_s: float = 4.0,
) -> tuple[Path, str, float | None]:
    """Render a designed slot. Returns (path, kind, duration_s).

    `kind` is the storyboard/compositor hint:
      • "title"  — when the file is a still PNG layout
      • "video"  — when as_video succeeded and the file is an .mp4 loop
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{name}.png"

    if layout == "slide":
        _render_slide(png, title=text, bullets=bullets or [])
    elif layout == "mockup":
        _render_mockup(png, label=text, subtext=subtext)
    else:
        _render_title(png, hero=text, subtext=subtext)

    if not as_video:
        return png, "title", None
    mp4 = out_dir / f"{name}.mp4"
    if _png_to_mp4_loop(png, mp4, duration_s=duration_s):
        return mp4, "video", duration_s
    return png, "title", None
