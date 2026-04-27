"""Vision LLM call per keyframe.

Reuses the existing claude_pool.run_vision_sync from v6/llm/. Each frame
gets a tight JSON-schema-constrained prompt — same pattern v4 used in
broll_analyzer.py.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .contracts import EditorialFunction, FreeZone, Keyframe, ShotType

log = logging.getLogger("visual_inventory.vision")


_SHOT_TYPES: tuple[str, ...] = (
    "close_up", "wide", "macro_animation", "screen_recording",
    "logo_centered", "portrait", "drone_aerial", "abstract", "other",
)


_SYSTEM_PROMPT = """\
You are a senior short-form video editor (TikTok/Reels/Shorts) doing visual
analysis of one b-roll keyframe at a time. Your job is dual:

A) Describe FACTUALLY what is in the image (descriptive layer).
B) Recommend EDITORIALLY where this frame fits in a tech/AI explainer narrative
   broken into beats (editorial layer).

Output a JSON object with these exact fields:

{
  // ── Descriptive layer ──────────────────────────────────────────────
  "description":     "<one factual sentence — what is shown>",
  "shot_type":       "close_up|wide|macro_animation|screen_recording|logo_centered|portrait|drone_aerial|abstract|other",
  "has_baked_text":  <true if image was DESIGNED to display text — slides,
                     infographics, kinetic typography. False for natural
                     footage or app screenshots where text is incidental>,
  "free_zones":      [<zones with no important subject — for overlay
                     placement, from {top, bottom, left, right, center,
                     top_left, top_right, bottom_left, bottom_right}>],
  "luminosity":      "dark|light|mixed",
  "quality":         <1-5 — 1=blurry/placeholder, 3=acceptable, 5=hero>,
  "subjects":        [<short tokens identifying named entities visible:
                     product names, logos, people. [] if generic>],

  // ── Editorial layer ────────────────────────────────────────────────
  "best_for":        [<beat editorial_functions this frame would serve well,
                     pick 1-3 from {hook, pain, solution, proof, value,
                     how_to, thesis, payoff, transition}>],
  "editorial_brief": "<one sentence: 'ideal for X because Y' — concrete,
                     actionable. Bad: 'good visual'. Good: 'use as the
                     INTRODUCTION beat for Gemma 4 — clean logo on dark bg
                     leaves bottom free for hero_text'>",
  "subject_match_strength": <0-5 — how clearly this frame depicts the named
                            subject of the surrounding beat. 0 = subject
                            absent or unclear, 5 = subject fully on-screen
                            and identifiable>
}

Editorial guidance for `best_for`:
  - logo_centered + clean composition         → hook, payoff
  - screen_recording / UI demo                → solution, how_to, proof
  - chart, infographic, data visualization    → proof, value
  - portrait of speaker / talking head        → transition (avoid for b-roll)
  - drone aerial, wide cinematic              → hook, payoff, thesis
  - mid-shot of product in real context       → solution, value
  - close-up of product detail                → value, proof
  - abstract / mood                           → transition only

Output JSON ONLY. No prose, no markdown fences.
"""


def _extract_json(text: str) -> dict | None:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s.rstrip())
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        a = s.find("{")
        b = s.rfind("}")
        if a >= 0 and b > a:
            try:
                return json.loads(s[a:b+1])
            except json.JSONDecodeError:
                return None
        return None


def _coerce_shot_type(v: Any) -> ShotType | None:
    if isinstance(v, str) and v in _SHOT_TYPES:
        return v  # type: ignore[return-value]
    return None


def _coerce_free_zones(v: Any) -> list[FreeZone]:
    valid = {"top", "bottom", "left", "right", "center",
             "top_left", "top_right", "bottom_left", "bottom_right"}
    if not isinstance(v, list):
        return []
    out: list[FreeZone] = []
    for x in v:
        if isinstance(x, str) and x in valid:
            out.append(x)  # type: ignore[arg-type]
    return out


_VALID_EFS: tuple[str, ...] = (
    "hook", "pain", "solution", "proof", "value", "how_to",
    "thesis", "payoff", "transition",
)


def _coerce_best_for(v: Any) -> list[EditorialFunction]:
    if not isinstance(v, list):
        return []
    out: list[EditorialFunction] = []
    for x in v:
        if isinstance(x, str) and x in _VALID_EFS and x not in out:
            out.append(x)  # type: ignore[arg-type]
    return out[:3]   # cap at 3 (matches v4 spec — 1-3 functions)


def analyze_frame(
    thumb_path: Path,
    t_s: float,
    *,
    vision_fn=None,            # injected for tests; default = claude_pool
    model: str = "haiku",      # haiku is ~5× cheaper, equivalent quality
    timeout_s: int = 90,
) -> Keyframe:
    """Send one keyframe to the vision LLM and parse the answer.

    Default model is Haiku — bench (Apr 2026) shows wall-time parity in
    parallel mode and equivalent or better shot_type categorisation, at
    1/5 the cost of Sonnet.

    On any failure (LLM down, malformed JSON), returns a Keyframe with
    description="(vision unavailable)" and quality=3 — never crashes the
    inventory run.
    """
    fallback = Keyframe(
        t_s=t_s,
        thumb_path=str(thumb_path.name),
        description="(vision unavailable)",
        quality=3,
    )
    if vision_fn is None:
        try:
            from llm import run_vision_sync as _real  # type: ignore

            def vision_fn(image_path, prompt, **kw):     # type: ignore[no-redef]
                kw.setdefault("model", model)
                return _real(image_path, prompt, **kw)
        except ImportError:
            log.warning("llm.run_vision_sync not importable")
            return fallback

    try:
        resp = vision_fn(
            str(thumb_path),
            _SYSTEM_PROMPT,
            timeout_s=timeout_s,
        )
    except Exception as exc:
        log.warning("vision call failed for %s: %s", thumb_path, exc)
        return fallback

    # claude_pool's RunResult exposes the LLM body as `.output`; other
    # provider wrappers may use `.text`. Try both, then fall through to a
    # bare string (used in unit tests with fake objects).
    text = (getattr(resp, "output", None)
            or getattr(resp, "text", None)
            or (resp if isinstance(resp, str) else ""))
    data = _extract_json(text)
    if not isinstance(data, dict):
        return fallback

    sm = data.get("subject_match_strength")
    sm_int = max(0, min(5, int(sm))) if isinstance(sm, (int, float)) else 0

    return Keyframe(
        t_s=t_s,
        thumb_path=str(thumb_path.name),
        description=str(data.get("description") or "")[:300] or "(empty)",
        shot_type=_coerce_shot_type(data.get("shot_type")),
        has_baked_text=bool(data.get("has_baked_text", False)),
        free_zones=_coerce_free_zones(data.get("free_zones")),
        luminosity=data.get("luminosity") if data.get("luminosity") in ("dark","light","mixed") else None,
        quality=max(1, min(5, int(data.get("quality") or 3))) if isinstance(data.get("quality"), (int, float)) else 3,
        subjects=[s for s in (data.get("subjects") or []) if isinstance(s, str)][:8],
        best_for=_coerce_best_for(data.get("best_for")),
        editorial_brief=str(data.get("editorial_brief") or "")[:300],
        subject_match_strength=sm_int,
    )
