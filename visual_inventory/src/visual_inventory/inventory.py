"""Build a visual inventory for every video asset in a capture_manifest.

Pure orchestration: reads the manifest, walks captures/<slug>/media/*.mp4,
extracts keyframes, calls the vision analyzer (in parallel via a thread
pool — Claude API requests are I/O bound so threads work fine), derives
shot_type distribution, and groups consecutive same-shot keyframes into
segments.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .contracts import (
    AssetInventory,
    Keyframe,
    Segment,
    ShotType,
    VisualInventory,
)
from .keyframe_extractor import extract_initial, probe_video
from .vision_analyzer import analyze_frame

log = logging.getLogger("visual_inventory.inventory")


_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv"}


def _segments_from_keyframes(kfs: list[Keyframe], duration_s: float) -> list[Segment]:
    """Group consecutive keyframes with the same shot_type into segments.

    A segment spans from the first keyframe of the run to the next
    keyframe of a different type (or end of clip). Quality = max of the
    keyframes' qualities. Score = quality/5 — broll planner can later
    weight by `subject_match` etc.
    """
    if not kfs:
        return []
    out: list[Segment] = []
    cur_start_idx = 0
    for i in range(1, len(kfs) + 1):
        prev_shot = kfs[cur_start_idx].shot_type
        if i == len(kfs) or kfs[i].shot_type != prev_shot:
            block = kfs[cur_start_idx:i]
            t_start = block[0].t_s
            t_end = kfs[i].t_s if i < len(kfs) else duration_s
            quality = max((k.quality for k in block), default=3)
            description = block[0].description
            shot_type: ShotType | None = block[0].shot_type
            out.append(Segment(
                t_start_s=round(max(0.0, t_start), 3),
                t_end_s=round(min(duration_s, t_end), 3),
                shot_type=shot_type,
                description=description,
                quality=quality,
                score=round(quality / 5.0, 2),
            ))
            cur_start_idx = i
    return out


def inventory_asset(
    asset_path: Path,
    slug: str,
    relative_to: Path,
    out_thumb_dir: Path,
    *,
    start_s: float = 1.0,
    step_s: float = 5.0,
    max_s: float = 40.0,
    vision_fn: Callable | None = None,
    parallel_workers: int = 8,
) -> AssetInventory | None:
    """Inventory a single video asset. Returns None if the asset is unusable.

    Default keyframe strategy: front-loaded sample t=1, 6, 11, …, max 40s.
    Editorial cap: official b-roll videos pack the value in the first 30-40s.
    """
    if not asset_path.exists():
        return None

    info = probe_video(asset_path)
    duration = info.get("duration_s") or 0.0
    if duration <= 0:
        return None

    out_thumb_dir.mkdir(parents=True, exist_ok=True)
    frames = extract_initial(
        asset_path, out_thumb_dir,
        start_s=start_s, step_s=step_s, max_s=max_s,
        duration_s=duration,
    )
    if not frames:
        return AssetInventory(
            slug=slug,
            asset_path=str(asset_path.relative_to(relative_to)),
            duration_s=duration,
            width=info.get("width"),
            height=info.get("height"),
            keyframes=[],
            summary="(no keyframes extracted)",
        )

    # Vision LLM calls are independent, I/O-bound HTTP requests — run them
    # in parallel through a thread pool. With Haiku + 8 workers, 8 frames
    # complete in ~15-20s wall-time vs ~120s sequential.
    kfs: list[Keyframe] = [None] * len(frames)  # type: ignore[list-item]

    def _work(idx_t_p):
        idx, (t, p) = idx_t_p
        return idx, analyze_frame(p, t, vision_fn=vision_fn)

    with ThreadPoolExecutor(max_workers=max(1, parallel_workers)) as ex:
        for idx, k in ex.map(_work, enumerate(frames)):
            kfs[idx] = k
    shot_types_seen: list[ShotType] = []
    seen: set[str] = set()
    for k in kfs:
        if k.shot_type and k.shot_type not in seen:
            seen.add(k.shot_type)
            shot_types_seen.append(k.shot_type)

    overall_q = round(sum(k.quality for k in kfs) / len(kfs))
    has_baked = any(k.has_baked_text for k in kfs)
    descriptions = [k.description for k in kfs if k.description and k.description != "(empty)"]
    summary = (descriptions[0] if descriptions else "")
    segments = _segments_from_keyframes(kfs, duration)

    return AssetInventory(
        slug=slug,
        asset_path=str(asset_path.relative_to(relative_to)),
        duration_s=duration,
        width=info.get("width"),
        height=info.get("height"),
        keyframes=kfs,
        shot_types_seen=shot_types_seen,
        has_any_baked_text=has_baked,
        overall_quality=overall_q,
        summary=summary,
        best_segments=segments,
    )


def build_inventory(
    capture_manifest: dict,
    captures_root: Path,
    out_dir: Path,
    *,
    start_s: float = 1.0,
    step_s: float = 5.0,
    max_s: float = 40.0,
    vision_fn: Callable | None = None,
    parallel_workers: int = 8,
) -> VisualInventory:
    """Walk the manifest, inventory every video asset.

    Args:
        capture_manifest: parsed capture_manifest.json (or *_enriched.json).
        captures_root:    dir that contains captures/<slug>/...
        out_dir:          where this phase writes its sidecar (thumbs land
                          inside captures/<slug>/thumbs/ to keep them with
                          the asset).
    """
    inv = VisualInventory(
        created_at=datetime.now(timezone.utc),
        capture_root=str(captures_root),
    )

    for r in capture_manifest.get("results", []):
        if r.get("status") != "ok":
            continue
        slug = (r.get("request") or {}).get("slug") or ""
        artifacts = r.get("artifacts") or {}
        for asset in artifacts.get("assets") or []:
            kind = asset.get("kind")
            rel_path = asset.get("path") or ""
            if kind != "video":
                continue
            asset_path = captures_root / "captures" / slug / rel_path
            if asset_path.suffix.lower() not in _VIDEO_EXTS:
                inv.skipped.append({"path": str(asset_path), "reason": "non_video_ext"})
                continue
            # Thumbs go INSIDE the phase out_dir so the viewer can serve them
            # via a simple path_pattern image_gallery — no extra endpoint
            # needed. Path: <out_dir>/thumbs/<slug>/<asset_stem>/kf_*.jpg.
            thumb_dir = out_dir / "thumbs" / slug / asset_path.stem
            asset_inv = inventory_asset(
                asset_path, slug, captures_root, thumb_dir,
                start_s=start_s, step_s=step_s, max_s=max_s,
                vision_fn=vision_fn,
                parallel_workers=parallel_workers,
            )
            if asset_inv is None:
                inv.skipped.append({"path": str(asset_path), "reason": "probe_failed"})
                continue
            inv.assets.append(asset_inv)

    return inv
