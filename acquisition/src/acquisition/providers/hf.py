"""hf provider — bridge from a pending broll hint to the hf_designer
LLM card and HyperFrames renderer.

The orchestrator delegates `type=slide` and `type=mockup` here. We:
  1. derive the `brief` from the hint (subject + description, with the
     `query` as fallback),
  2. pick the kind ("slide" | "mockup") based on `hint.type`,
  3. call `hf_designer.design()` to get HTML,
  4. render to MP4 via `hf_designer.render_to_mp4()`,
  5. return (path, kind, duration) the orchestrator expects.

If anything fails we re-raise: the orchestrator catches and falls back
to its existing `text_card` provider so the slot is never empty.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

log = logging.getLogger("acquisition.hf")


_DEFAULT_DURATION_S = 5.0
_DEFAULT_LAYOUT: str = "fullscreen"


def _hint_to_brief(hint: dict) -> str:
    """Turn a broll hint into a free-text brief the designer LLM consumes.

    Priority: subject → description → query. We DO NOT invent — the
    designer prompt is strict about not fabricating numbers/entities.
    """
    parts: list[str] = []
    subj = (hint.get("subject") or "").strip()
    if subj:
        parts.append(subj)
    desc = (hint.get("description") or "").strip()
    if desc and desc != subj:
        parts.append(desc)
    if not parts:
        q = (hint.get("query") or "").strip()
        if q:
            parts.append(q)
    return " — ".join(parts) or "abstract card"


def _infer_kind(hint: dict) -> Literal["slide", "mockup"]:
    """Map hint.type → designer kind. Defaults to mockup so any
    unforeseen designed-type lands on the editorial-quote prompt
    (looks better than a stat slide with no metric)."""
    t = (hint.get("type") or "").lower()
    if t == "slide":
        return "slide"
    return "mockup"


def _infer_sub_kind_for_title(hint: dict) -> str:
    """When the LLM emitted `type=title` (a hero text overlay), infer
    a mockup sub-layout from the visible text length:

      • ≤3 words → kicker  (massive 130–180px)
      • else     → thesis  (full sentence, breathes)

    Either prompts the designer to keep the layout simple and centred
    rather than pushing it toward a quote/manifesto frame.
    """
    text = (hint.get("subject") or "").strip()
    if not text:
        # Description starts with PRIMARY:..., so look for the first
        # sentence-ish chunk to count words.
        desc = (hint.get("description") or "").strip()
        # Strip any leading "PRIMARY:" header before counting
        if desc.lower().startswith("primary:"):
            desc = desc[len("primary:"):].strip()
        text = desc.split(".")[0]
    word_count = len(text.split())
    return "kicker" if word_count <= 3 else "thesis"


def _layout_for(hint: dict) -> str:
    """Use the hint's explicit `layout` if the LLM emitted one; else
    fall back to fullscreen (most common — covers the whole video frame)."""
    layout = (hint.get("layout") or "").lower()
    if layout in ("fullscreen", "split_top", "split_bottom"):
        return layout
    return _DEFAULT_LAYOUT


def _duration_for(hint: dict) -> float:
    """The renderer needs a duration; lean on the hint's
    `duration_target_s` when available (the analysis LLM usually sets
    this from beat width), otherwise `_DEFAULT_DURATION_S`."""
    raw = hint.get("duration_target_s")
    try:
        d = float(raw) if raw is not None else _DEFAULT_DURATION_S
    except (TypeError, ValueError):
        d = _DEFAULT_DURATION_S
    # Clamp into a render-friendly window: HyperFrames really doesn't
    # like sub-second renders, and >12s makes the LLM bloat the HTML.
    return max(2.0, min(d, 12.0))


def acquire(hint: dict, slot_dir: Path,
            *, name: str = "card") -> tuple[Path, str, float | None, str, str]:
    """Generate the slide/mockup MP4 for one hint.

    Returns (mp4_path, kind, duration_s, designer_kind, layout).

    Raises any exception bubbled up from the designer or renderer —
    the caller is expected to catch and degrade to text_card.
    """
    from hf_designer import design, render_to_mp4

    designer_kind = _infer_kind(hint)
    layout = _layout_for(hint)
    duration = _duration_for(hint)
    brief = _hint_to_brief(hint)
    palette = hint.get("palette") if isinstance(hint.get("palette"), dict) else None

    # Bias the designer toward the LLM-requested layout sub-kind by
    # appending it to the brief — both prompts route on the semantic
    # shape of the brief, so a leading hint nudges the right layout.
    sub = (hint.get("slide_kind") if designer_kind == "slide"
           else hint.get("mockup_kind"))
    if not sub and (hint.get("type") or "").lower() == "title":
        # The LLM emitted `type=title` (no mockup_kind). Infer
        # kicker vs thesis from the hero text length so the designer
        # uses an appropriate hero layout.
        sub = _infer_sub_kind_for_title(hint)
    if sub:
        brief = f"[layout:{sub}] {brief}"

    log.info("hf_designer kind=%s layout=%s duration=%.1fs brief=%r",
             designer_kind, layout, duration, brief[:80])

    html = design(
        brief=brief, kind=designer_kind,
        layout=layout, duration_s=duration,
        palette=palette,
    )

    slot_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = slot_dir / f"{name}.mp4"
    res = render_to_mp4(html, out_mp4, duration_s=duration)
    if res.get("status") != "ok":
        # Persist the HTML for debugging when the render itself failed
        (slot_dir / f"{name}.html").write_text(html, encoding="utf-8")
        raise RuntimeError(
            f"hf render failed (kind={designer_kind} layout={layout}): "
            f"{res.get('message')}"
        )
    return out_mp4, "video", res.get("duration_s"), designer_kind, layout
