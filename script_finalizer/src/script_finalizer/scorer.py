"""Scoring helpers — pure data, no I/O.

Compute the material_score (does the catalogue have strong visual support
for the topics?) and the per-hint match (does an asset segment fit this
specific beat hint by subject + editorial_function)?
"""
from __future__ import annotations

from typing import Iterable, Optional

from analysis.contracts import BrollHint, Entity, Topic
from visual_inventory.contracts import AssetInventory, Segment


# ── Strength tiers ──────────────────────────────────────────────────

def material_strength_tier(score: float) -> str:
    if score >= 0.8:
        return "rich"
    if score <= 0.4:
        return "thin"
    return "default"


def adaptive_broll_target(score: float) -> tuple[float, float]:
    """Returns (min, max) coverage as a ratio of duration."""
    tier = material_strength_tier(score)
    if tier == "rich":
        return (0.50, 0.65)
    if tier == "thin":
        return (0.25, 0.35)
    return (0.35, 0.50)


# ── material_score ──────────────────────────────────────────────────

def compute_material_score(
    inventory_assets: list[AssetInventory],
    entities: list[Entity],
) -> float:
    """Weighted avg of (overall_quality * peak_subject_match) over assets,
    normalized to 0-1.

    quality is 1-5 (visual_inventory.AssetInventory.overall_quality);
    subject_match is the max subject_match_strength across the asset's
    keyframes (also 0-5). Product / 25 → 0-1 contribution per asset.
    Weight by total segment duration so a 30s rich asset outweighs a 3s
    one.
    """
    if not inventory_assets:
        return 0.0

    canonical_set = {e.canonical.lower() for e in entities}
    total_w = 0.0
    weighted_sum = 0.0

    for a in inventory_assets:
        # Peak subject match across keyframes; bonus if any keyframe
        # subject literally matches a known entity canonical.
        peak_sm = max(
            (k.subject_match_strength for k in a.keyframes), default=0
        )
        if any(s.lower() in canonical_set
               for k in a.keyframes for s in k.subjects):
            peak_sm = max(peak_sm, 4)
        contrib = (a.overall_quality * peak_sm) / 25.0
        weight = sum(max(0.0, s.t_end_s - s.t_start_s)
                     for s in a.best_segments) or (a.duration_s or 1.0)
        weighted_sum += contrib * weight
        total_w += weight

    if total_w <= 0:
        return 0.0
    return min(1.0, max(0.0, weighted_sum / total_w))


# ── per-hint match ──────────────────────────────────────────────────

def best_segment_for_hint(
    hint: BrollHint,
    beat_editorial_function: str,
    inventory_assets: list[AssetInventory],
    *,
    used_assets: dict[str, int] | None = None,
    used_segments: dict[tuple[str, float], int] | None = None,
) -> Optional[tuple[AssetInventory, Segment, float]]:
    """Return (asset, segment, score) where score is 0-1 or None.

    Score combines:
      * subject string overlap between hint.subject and the asset's
        keyframe subjects (0 / 0.5 / 1)
      * shot_type match between hint.shot_type and segment.shot_type
        (0 / 0.5 / 1)
      * editorial_function fit: ANY keyframe of the asset has
        beat_editorial_function in its best_for (0 / 1)
      * raw segment.score (0-1)
    Final score is the average. Threshold of 0.4 should be considered
    minimum to anchor.

    Variety penalty (when ``used_assets`` / ``used_segments`` are passed):
      • -0.15 per previous use of the same asset (rotate between videos)
      • -0.30 per previous use of the same (asset, segment_t_start) pair
        (avoid identical clip even if asset must repeat)
    Encourages spreading the broll across the catalogue.
    """
    used_assets = used_assets or {}
    used_segments = used_segments or {}
    best: Optional[tuple[AssetInventory, Segment, float]] = None

    hint_subj = (hint.subject or "").lower().strip()
    hint_shot = hint.shot_type or ""

    # Trust signal: the LLM may have explicitly mapped this hint to a
    # capture slug via `source_ref`. If that asset exists, we trust the
    # editorial pairing and bypass the subject hard-gate — the LLM has
    # already made the semantic match (e.g. subject="GitHub" → slug
    # "github-com-mirofish" whose keyframe label is just "mirofish").
    pinned_slug = hint.source_ref if hint.source_ref else None

    for asset in inventory_assets:
        # Subject check via keyframe subjects
        kf_subjects: set[str] = set()
        for k in asset.keyframes:
            for s in k.subjects:
                kf_subjects.add(s.lower())
        is_pinned = (pinned_slug == asset.slug)

        # Visual variety guard: a single-segment og:image is one fixed
        # frame. Reusing it across multiple beats produces visually
        # identical thumbs. Cap non-pinned reuse at 1 — anything beyond
        # that should fall through to acquisition (Pexels, text_card)
        # so the editor sees fresh footage instead of stamping the same
        # logo three times.
        already_used = used_assets.get(asset.slug, 0)
        single_segment_asset = len(asset.best_segments) <= 1
        if single_segment_asset and already_used >= 1 and not is_pinned:
            continue

        if hint_subj and not is_pinned:
            if any(hint_subj in s or s in hint_subj for s in kf_subjects):
                subj_score = 1.0
            elif kf_subjects:
                # Hard gate: hint named a subject, asset has labels, none match
                # → NEVER anchor on this asset (would mislead the editor).
                continue
            else:
                subj_score = 0.5      # asset has no labels — neutral
        elif is_pinned:
            subj_score = 1.0          # LLM-trusted pairing
        else:
            subj_score = 0.5

        if is_pinned:
            # When the LLM has explicitly mapped this beat → asset, both
            # the subject and editorial-function fit are already vouched
            # for. Treat the editorial dimension as a match too, so a
            # haiku-vision `best_for` that excludes the beat's ef cannot
            # demote the trusted pairing below the anchor threshold.
            ef_score = 1.0
        else:
            ef_match = any(
                beat_editorial_function in k.best_for for k in asset.keyframes
            )
            ef_score = 1.0 if ef_match else 0.0

        # Static assets (single-keyframe og:images) have only one segment
        # in best_segments. Reusing the asset == reusing that segment, so
        # stacking both penalties (-0.15 + -0.40 = -0.55) effectively
        # blocks any reuse even when there's no other anchor candidate.
        # Apply the per-segment penalty only when the asset offers more
        # than one segment to choose from.
        single_segment = len(asset.best_segments) <= 1

        for seg in asset.best_segments:
            shot_score = 1.0 if (hint_shot and seg.shot_type == hint_shot) else (
                0.5 if not hint_shot else 0.0
            )
            combined = (subj_score + shot_score + ef_score + seg.score) / 4.0
            # Variety penalty
            asset_uses = used_assets.get(asset.slug, 0)
            seg_uses = used_segments.get((asset.slug, seg.t_start_s), 0)
            seg_penalty = 0.0 if single_segment else 0.40 * seg_uses
            penalty = 0.15 * asset_uses + seg_penalty
            adjusted = max(0.0, combined - penalty)
            if best is None or adjusted > best[2]:
                best = (asset, seg, adjusted)

    return best


# ── hint type categorisation ────────────────────────────────────────

REAL_FOOTAGE_TYPES = {"video", "web_capture", "photo"}
FILLER_TYPES = {"slide", "title"}


def downgrade_target(current_type: str) -> str:
    """When a hint can't find inventory backing, soften its type."""
    if current_type == "video":
        return "photo"
    if current_type == "slide":
        return "title"
    if current_type == "mockup":
        return "title"
    if current_type == "pexels":
        return "title"
    return current_type
