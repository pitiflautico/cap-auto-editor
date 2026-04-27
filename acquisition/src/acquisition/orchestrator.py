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
from .providers import pexels, text_card

log = logging.getLogger("acquisition.orchestrator")


def _query_for(hint: dict) -> str:
    """Compose a search string. Prefer hint.query → subject → description."""
    return (
        (hint.get("query") or "").strip()
        or (hint.get("subject") or "").strip()
        or (hint.get("description") or "").strip()[:80]
        or "abstract"
    )


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


def _try_text_card(text: str, slot_dir: Path, *, as_video: bool,
                   attempts: list[AcquisitionAttempt]
                   ) -> tuple[Path, str, float | None]:
    t0 = time.monotonic()
    try:
        path, kind, duration = text_card.generate(
            text, slot_dir, name="card", as_video=as_video,
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


def _resolve_one(hint: dict, slot_dir: Path) -> AcquisitionEntry:
    """Run the cascade for a single pending hint."""
    type_ = hint.get("type") or "title"
    query = _query_for(hint)
    attempts: list[AcquisitionAttempt] = []
    final_provider: ProviderName | None = None
    abs_path: Path | None = None
    kind: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None

    # ── Cascade per type ────────────────────────────────────────────
    if type_ == "video":
        # Pexels video → text_card video
        r = _try_pexels_video(query, slot_dir, attempts)
        if r:
            abs_path, info = r
            final_provider = "pexels_video"
            kind = "video"
            duration = info.get("duration_s")
            width, height = info.get("width"), info.get("height")
        if abs_path is None:
            target_s = float(hint.get("duration_target_s") or 4.0)
            p, k, d = _try_text_card(_fallback_text(hint), slot_dir,
                                       as_video=True, attempts=attempts)
            abs_path, kind, duration = p, k, d
            final_provider = "text_card"

    elif type_ in ("photo", "web_capture", "mockup", "pexels"):
        r = _try_pexels_image(query, slot_dir, attempts)
        if r:
            abs_path, info = r
            final_provider = "pexels_image"
            kind = "image"
            width, height = info.get("width"), info.get("height")
        if abs_path is None:
            p, k, d = _try_text_card(_fallback_text(hint), slot_dir,
                                       as_video=False, attempts=attempts)
            abs_path, kind, duration = p, k, d
            final_provider = "text_card"

    else:
        # slide / title — text_card directly
        as_video = (type_ == "slide")
        p, k, d = _try_text_card(_fallback_text(hint), slot_dir,
                                   as_video=as_video, attempts=attempts)
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
