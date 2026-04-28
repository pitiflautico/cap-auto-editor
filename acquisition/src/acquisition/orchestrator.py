"""Acquisition orchestrator: cascade per-type per pending hint."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from .contracts import (
    AcquisitionAttempt,
    AcquisitionEntry,
    AcquisitionReport,
    ProviderName,
)
from .providers import hf, pexels, text_card

log = logging.getLogger("acquisition.orchestrator")


def _query_for(hint: dict) -> str:
    """Compose a search string. Prefer hint.query → subject → description."""
    return (
        (hint.get("query") or "").strip()
        or (hint.get("subject") or "").strip()
        or (hint.get("description") or "").strip()[:80]
        or "abstract"
    )


def _query_chain(hint: dict) -> list[str]:
    """Ordered list of queries to try: primary → fallbacks → subject."""
    out: list[str] = []
    seen: set[str] = set()
    primary = _query_for(hint)
    if primary:
        out.append(primary)
        seen.add(primary.lower())
    for q in (hint.get("queries_fallback") or []):
        q = (q or "").strip()
        if q and q.lower() not in seen:
            out.append(q)
            seen.add(q.lower())
    subj = (hint.get("subject") or "").strip()
    if subj and subj.lower() not in seen:
        out.append(subj)
    return out


# shot_type values that imply MOTION — these hints are best fulfilled by
# Pexels video, with image as a fallback. Static shot_types stay as image.
# Source priority spec: real footage > screenshots > logos > mockups > stock.
_MOTION_SHOT_TYPES = frozenset({
    "screen_recording", "drone_aerial", "wide", "close_up",
    "macro_animation", "portrait",
})
_STATIC_SHOT_TYPES = frozenset({"logo_centered", "abstract"})


def _prefers_video(hint: dict) -> bool:
    """True when the cascade should try Pexels video before image."""
    if hint.get("type") == "video":
        return True
    shot = (hint.get("shot_type") or "").lower()
    if shot in _MOTION_SHOT_TYPES:
        return True
    return False


def _fallback_text(hint: dict) -> str:
    """Text shown on the text_card when nothing else is found."""
    return (
        (hint.get("subject") or "").strip()
        or (hint.get("description") or "").strip()[:60]
        or "•"
    )


def _try_pexels_video(query: str, slot_dir: Path,
                      attempts: list[AcquisitionAttempt]) -> tuple[Path, dict] | None:
    t0 = time.monotonic()
    try:
        result = pexels.search_video(query, slot_dir)
    except Exception as exc:
        attempts.append(AcquisitionAttempt(
            provider="pexels_video", success=False,
            duration_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc)[:200],
        ))
        return None
    elapsed = int((time.monotonic() - t0) * 1000)
    if result is None:
        attempts.append(AcquisitionAttempt(
            provider="pexels_video", success=False, duration_ms=elapsed,
            error="no_match",
        ))
        return None
    path, url, info = result
    attempts.append(AcquisitionAttempt(
        provider="pexels_video", success=True, duration_ms=elapsed,
        chosen_url=url, chosen_id=str(info.get("id")),
    ))
    return path, info


def _try_pexels_image(query: str, slot_dir: Path,
                      attempts: list[AcquisitionAttempt]) -> tuple[Path, dict] | None:
    t0 = time.monotonic()
    try:
        result = pexels.search_image(query, slot_dir)
    except Exception as exc:
        attempts.append(AcquisitionAttempt(
            provider="pexels_image", success=False,
            duration_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc)[:200],
        ))
        return None
    elapsed = int((time.monotonic() - t0) * 1000)
    if result is None:
        attempts.append(AcquisitionAttempt(
            provider="pexels_image", success=False, duration_ms=elapsed,
            error="no_match",
        ))
        return None
    path, url, info = result
    attempts.append(AcquisitionAttempt(
        provider="pexels_image", success=True, duration_ms=elapsed,
        chosen_url=url, chosen_id=str(info.get("id")),
    ))
    return path, info


def _text_card_inputs(hint: dict) -> tuple[str, str, str | None, list[str]]:
    """Map a BrollHint dict to text_card inputs (layout, hero, subtext, bullets).

    The mapping turns the LLM's editorial intent into the right card layout:
      • type=title  → layout=title  : `subject` (or query) as hero text;
                      `description` becomes the subtext line below.
      • type=slide  → layout=slide  : `subject` (or query) as title; the
                      hint's `queries_fallback` (else split description)
                      become bullets — at most three.
      • type=mockup → layout=mockup : `subject` as the product label;
                      `description` as supporting subtext inside the
                      phone frame.
      • everything else falls back to a title layout with the fallback
        text from `_fallback_text(hint)`.
    """
    type_ = (hint.get("type") or "").lower()
    subj = (hint.get("subject") or "").strip()
    desc = (hint.get("description") or "").strip()
    qry = (hint.get("query") or "").strip()
    fallbacks = [s.strip() for s in (hint.get("queries_fallback") or []) if s and s.strip()]

    if type_ == "slide":
        title = subj or qry or "Highlights"
        bullets = fallbacks[:3]
        if not bullets and desc:
            # Greedy split on sentences/commas as a degraded source for bullets
            for sep in (". ", "; ", ", "):
                parts = [p.strip().rstrip(".") for p in desc.split(sep) if p.strip()]
                if len(parts) >= 2:
                    bullets = parts[:3]
                    break
            if not bullets:
                bullets = [desc[:60]]
        return "slide", title, None, bullets

    if type_ == "mockup":
        hero = subj or qry or "(product mockup)"
        return "mockup", hero, desc or None, []

    # default — title layout
    hero = subj or qry or _fallback_text(hint)
    sub = desc if desc and desc != hero else None
    return "title", hero, sub, []


def _try_text_card(hint_or_text, slot_dir: Path, *, as_video: bool,
                   attempts: list[AcquisitionAttempt],
                   duration_s: float = 4.0,
                   ) -> tuple[Path, str, float | None]:
    """Render a text_card slot. `hint_or_text` may be either the full
    hint dict (preferred — picks layout from hint.type) or a bare
    fallback string (legacy path used by Pexels miss → text_card).
    """
    if isinstance(hint_or_text, dict):
        layout, hero, subtext, bullets = _text_card_inputs(hint_or_text)
    else:
        layout, hero, subtext, bullets = "title", str(hint_or_text), None, []
    t0 = time.monotonic()
    try:
        path, kind, duration = text_card.generate(
            hero, slot_dir, name="card",
            layout=layout, subtext=subtext, bullets=bullets,
            as_video=as_video, duration_s=duration_s,
        )
    except Exception as exc:
        attempts.append(AcquisitionAttempt(
            provider="text_card", success=False,
            duration_ms=int((time.monotonic() - t0) * 1000),
            error=str(exc)[:200],
        ))
        raise
    attempts.append(AcquisitionAttempt(
        provider="text_card", success=True,
        duration_ms=int((time.monotonic() - t0) * 1000),
    ))
    return path, kind, duration


def _try_pexels_video_chain(queries: list[str], slot_dir: Path,
                              attempts: list[AcquisitionAttempt]
                              ) -> tuple[Path, dict] | None:
    """Try each query until one returns a Pexels video. Records every
    failed query as a separate AcquisitionAttempt for debuggability.
    """
    for q in queries:
        r = _try_pexels_video(q, slot_dir, attempts)
        if r:
            return r
    return None


def _try_pexels_image_chain(queries: list[str], slot_dir: Path,
                              attempts: list[AcquisitionAttempt]
                              ) -> tuple[Path, dict] | None:
    for q in queries:
        r = _try_pexels_image(q, slot_dir, attempts)
        if r:
            return r
    return None


def _resolve_one(hint: dict, slot_dir: Path) -> AcquisitionEntry:
    """Run the cascade for a single pending hint.

    Cascade respects the editorial source-priority spec (real footage >
    screenshots > logos > mockups > stock) and the type taxonomy:

      • title  / slide  / mockup   → text_card with the matching layout
                                      (no stock — these are *designed*).
      • video                      → Pexels video → text_card title (loop)
      • pexels / photo / web_capture
                                   → motion-aware Pexels (video first if
                                      shot_type suggests movement) →
                                      text_card title fallback.

    Each Pexels search iterates the hint's `query` and `queries_fallback`
    list before declaring failure, so a too-specific primary query
    doesn't silently demote the slot to a text_card.
    """
    type_ = (hint.get("type") or "title").lower()
    queries = _query_chain(hint)
    attempts: list[AcquisitionAttempt] = []
    final_provider: ProviderName | None = None
    abs_path: Path | None = None
    kind: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None

    target_dur = float(hint.get("duration_target_s") or 4.0)

    # ── Designed types: hf_designer (LLM + HyperFrames) → text_card ─
    # `title` joins slide/mockup here because it's a hero text card —
    # the kicker/thesis layouts in the mockup_prompt cover that case
    # animated. PIL text_card stays only as a deterministic fallback
    # if the LLM/render path fails.
    if type_ in ("slide", "mockup", "title"):
        t0 = time.monotonic()
        try:
            mp4_path, hf_kind, hf_dur, designer_kind, _ = hf.acquire(
                hint, slot_dir, name="card",
            )
            abs_path = mp4_path
            kind = hf_kind                 # "video"
            duration = hf_dur
            final_provider = (
                "hf_slide" if designer_kind == "slide" else "hf_mockup"
            )
            attempts.append(AcquisitionAttempt(
                provider=final_provider, success=True,
                duration_ms=int((time.monotonic() - t0) * 1000),
            ))
        except Exception as exc:
            attempts.append(AcquisitionAttempt(
                provider=("hf_slide" if type_ == "slide" else "hf_mockup"),
                success=False,
                duration_ms=int((time.monotonic() - t0) * 1000),
                error=str(exc)[:200],
            ))
            log.warning("hf provider failed for %s/%s: %s — falling back to text_card",
                         hint.get("beat_id"), type_, exc)
            as_video = (type_ in ("slide", "title"))
            p, k, d = _try_text_card(hint, slot_dir,
                                       as_video=as_video, attempts=attempts,
                                       duration_s=target_dur)
            abs_path, kind, duration = p, k, d
            final_provider = "text_card"

    # ── Real footage / stock cascade ────────────────────────────────
    elif type_ in ("video", "pexels", "photo", "web_capture"):
        prefers_video = _prefers_video(hint)
        # Try video first when the hint suggests motion or type=video.
        if prefers_video or type_ == "video":
            r = _try_pexels_video_chain(queries, slot_dir, attempts)
            if r:
                abs_path, info = r
                final_provider = "pexels_video"
                kind = "video"
                duration = info.get("duration_s")
                width, height = info.get("width"), info.get("height")

        # Fall back to Pexels image when the hint is fine with a still.
        if abs_path is None and type_ != "video":
            r = _try_pexels_image_chain(queries, slot_dir, attempts)
            if r:
                abs_path, info = r
                final_provider = "pexels_image"
                kind = "image"
                width, height = info.get("width"), info.get("height")

        if abs_path is None:
            # Last resort: title text_card (looped to mp4 for type=video).
            as_video = (type_ == "video")
            p, k, d = _try_text_card(hint, slot_dir,
                                       as_video=as_video, attempts=attempts,
                                       duration_s=target_dur)
            abs_path, kind, duration = p, k, d
            final_provider = "text_card"

    else:
        # Unknown type — render a title card so the slot is never empty.
        p, k, d = _try_text_card(hint, slot_dir,
                                   as_video=False, attempts=attempts)
        abs_path, kind, duration = p, k, d
        final_provider = "text_card"

    return AcquisitionEntry(
        beat_id=hint.get("beat_id", ""),
        hint_index=int(hint.get("hint_index", 0)),
        type=type_,
        subject=hint.get("subject"),
        abs_path=str(abs_path) if abs_path else None,
        kind=kind,
        duration_s=duration,
        width=width, height=height,
        final_provider=final_provider,
        attempts=attempts,
    )


def acquire(
    pending_payload: dict,
    out_dir: Path,
) -> AcquisitionReport:
    """Walk pending list, run cascade per hint, persist assets under out_dir/assets/."""
    assets_root = out_dir / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    report = AcquisitionReport(created_at=datetime.now(timezone.utc))
    pending = pending_payload.get("pending") or []
    report.pending_total = len(pending)

    for h in pending:
        slot = assets_root / f"{h.get('beat_id','b???')}_{h.get('hint_index',0)}"
        try:
            entry = _resolve_one(h, slot)
        except Exception as exc:                            # pragma: no cover
            log.warning("hint resolution crashed: %s", exc)
            entry = AcquisitionEntry(
                beat_id=h.get("beat_id", ""),
                hint_index=int(h.get("hint_index", 0)),
                type=h.get("type", "title"),
                subject=h.get("subject"),
            )
        report.entries.append(entry)
        if entry.abs_path:
            report.acquired_count += 1
        if entry.final_provider == "text_card":
            report.text_card_fallback += 1
        if entry.final_provider:
            report.provider_counts[entry.final_provider] = (
                report.provider_counts.get(entry.final_provider, 0) + 1
            )
        report.api_errors += sum(
            1 for a in entry.attempts
            if not a.success and a.provider in ("pexels_video", "pexels_image")
            and a.error not in (None, "no_match")
        )

    return report
