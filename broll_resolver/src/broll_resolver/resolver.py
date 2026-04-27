"""Resolver orchestrator — turn balanced broll_hints into ResolvedAsset rows.

Strategy (MVP):
    1) Look at hint.description for an inventory anchor written by the
       script_finalizer ('[@ media/foo.mp4 1.0-13.3s]'). When found,
       resolve to abs_path inside the slug's capture dir.
    2) Else, if hint.source_ref points at a captured slug, take that slug's
       first video asset.
    3) Else, if hint.source_ref points at a slug with only a screenshot,
       resolve as a screenshot ResolvedAsset (broll_analyzer can later
       turn it into a Ken Burns clip).
    4) Else, if hint.type == 'title', emit a title-fallback resolution
       (no media file — renderer generates kinetic typography from
       hint.description).
    5) Else, the hint becomes a PendingHint for acquisition.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from analysis.contracts import AnalysisResult, Beat, BrollHint
from .contracts import (
    BrollPlan,
    PendingAcquisitions,
    PendingHint,
    ResolvedAsset,
    ResolverReport,
)


# Anchor pattern written by script_finalizer:
#   "<original desc>  [@ media/video_01.mp4 1.0-13.3s]"
_ANCHOR_RE = re.compile(
    r"\[@\s*(?P<path>[^\s]+)\s+(?P<t1>\d+(?:\.\d+)?)-(?P<t2>\d+(?:\.\d+)?)s\s*\]"
)


def _find_capture_root(captures_root: Path, manifest: dict) -> Path:
    """Manifest's `out_dir` field wins — it points at the original
    capture/ even if the manifest itself lives in auto_source/."""
    out_dir = manifest.get("out_dir")
    if out_dir and Path(out_dir).exists():
        return Path(out_dir)
    return captures_root


def _slug_index(manifest: dict) -> dict[str, dict]:
    """slug -> result dict for fast lookup."""
    return {
        (r.get("request") or {}).get("slug"): r
        for r in manifest.get("results", [])
        if r.get("status") == "ok"
    }


def _first_video_asset(result: dict) -> dict | None:
    for a in (result.get("artifacts") or {}).get("assets", []) or []:
        if a.get("kind") == "video":
            return a
    return None


def _screenshot_path(result: dict) -> str | None:
    return (result.get("artifacts") or {}).get("screenshot_path")


def _abs(captures_root: Path, slug: str, rel_path: str) -> Path:
    return captures_root / "captures" / slug / rel_path


def _resolve_one(
    beat: Beat,
    hi: int,
    hint: BrollHint,
    captures_root: Path,
    slug_idx: dict[str, dict],
) -> ResolvedAsset | PendingHint:
    """Apply the cascade for a single hint."""
    common_kwargs = dict(
        beat_id=beat.beat_id, hint_index=hi,
        subject=hint.subject, description=hint.description,
        beat_start_s=beat.start_s, beat_end_s=beat.end_s,
    )

    # 1) Inventory anchor written by finalizer
    m = _ANCHOR_RE.search(hint.description or "")
    if m and hint.source_ref and hint.source_ref in slug_idx:
        slug = hint.source_ref
        rel_path = m.group("path")
        t1 = float(m.group("t1"))
        t2 = float(m.group("t2"))
        abs_p = _abs(captures_root, slug, rel_path)
        if abs_p.exists():
            return ResolvedAsset(
                **common_kwargs, type=hint.type,
                kind="video", source="anchor_in_inventory",
                abs_path=str(abs_p), slug=slug,
                t_start_s=t1, t_end_s=t2,
                duration_s=round(max(0.0, t2 - t1), 2),
            )

    # 2) source_ref → first video asset
    if hint.source_ref and hint.source_ref in slug_idx:
        result = slug_idx[hint.source_ref]
        v = _first_video_asset(result)
        if v:
            abs_p = _abs(captures_root, hint.source_ref, v.get("path", ""))
            if abs_p.exists():
                return ResolvedAsset(
                    **common_kwargs, type=hint.type,
                    kind="video", source="source_ref_first_video",
                    abs_path=str(abs_p), slug=hint.source_ref,
                    t_start_s=0.0,
                    t_end_s=float(v.get("duration_s") or 0.0) or None,  # type: ignore[arg-type]
                    duration_s=v.get("duration_s"),
                    width=v.get("width"), height=v.get("height"),
                )
        # 3) screenshot fallback
        ss = _screenshot_path(result)
        if ss:
            abs_p = _abs(captures_root, hint.source_ref, ss)
            if abs_p.exists():
                return ResolvedAsset(
                    **common_kwargs, type=hint.type,
                    kind="screenshot", source="source_ref_screenshot",
                    abs_path=str(abs_p), slug=hint.source_ref,
                )

    # 4) title fallback (no asset needed)
    if hint.type == "title":
        return ResolvedAsset(
            **common_kwargs, type=hint.type,
            kind="title", source="title_fallback",
        )

    # 5) Pending — needs acquisition
    return PendingHint(
        beat_id=beat.beat_id, hint_index=hi, type=hint.type,
        subject=hint.subject, query=hint.query,
        queries_fallback=list(hint.queries_fallback or []),
        shot_type=hint.shot_type,
        duration_target_s=hint.duration_target_s,
        description=hint.description,
        editorial_function=beat.editorial_function,
        beat_start_s=beat.start_s, beat_end_s=beat.end_s,
        reason="no local material; needs acquisition (Pexels/yt-dlp/text_card)",
    )


def resolve(
    analysis: AnalysisResult,
    capture_manifest: dict,
    captures_root: Path,
) -> tuple[BrollPlan, PendingAcquisitions, ResolverReport]:
    """Walk every broll_hint and split into resolved + pending lists."""
    cap_root = _find_capture_root(captures_root, capture_manifest)
    slug_idx = _slug_index(capture_manifest)

    now = datetime.now(timezone.utc)
    plan = BrollPlan(created_at=now)
    pending = PendingAcquisitions(created_at=now)
    report = ResolverReport(created_at=now)

    for beat in analysis.narrative.beats:
        for hi, hint in enumerate(beat.broll_hints or []):
            report.total_hints += 1
            result = _resolve_one(beat, hi, hint, cap_root, slug_idx)
            if isinstance(result, ResolvedAsset):
                plan.resolved.append(result)
                report.resolved_count += 1
                report.resolved_by_source[result.source] = (
                    report.resolved_by_source.get(result.source, 0) + 1
                )
            else:
                pending.pending.append(result)
                report.pending_count += 1
                t = result.type_
                report.pending_by_type[t] = report.pending_by_type.get(t, 0) + 1

    return plan, pending, report
