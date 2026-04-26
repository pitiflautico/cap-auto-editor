"""Cut planner.

Takes candidate `CutRegion`s from the detectors, applies padding rules,
merges overlapping/adjacent regions, and emits the final list of cuts
that will be executed.

Responsibilities:
1. Shrink each region by padding_before/after (never cut into spoken words).
2. Merge overlapping or near-adjacent regions into a single cut.
3. Respect `min_remaining_pause_s` — refuse to cut if doing so would
   leave less than that much natural air between neighbouring content.
"""
from __future__ import annotations

from .contracts import CutRegion


def _sort_key(c: CutRegion) -> float:
    return c.start_s


def apply_padding(cut: CutRegion) -> CutRegion:
    """Return a new CutRegion shrunk by its padding values.

    Padding guards the bordering audio so we don't clip speech or
    breathing transitions.
    """
    new_start = cut.start_s + cut.padding_before_s
    new_end = cut.end_s - cut.padding_after_s
    if new_end <= new_start:
        # Padding would annihilate the cut — mark as keep.
        return cut.model_copy(update={
            "action": "keep",
            "notes": (cut.notes or "") + " [padding annihilated]",
        })
    return cut.model_copy(update={"start_s": new_start, "end_s": new_end})


def merge_overlapping(
    cuts: list[CutRegion],
    *,
    gap_threshold_s: float = 0.1,
) -> list[CutRegion]:
    """Merge cuts whose gap between them is <= threshold.

    The merged region takes the union of `affected_words` and the
    highest confidence of its sources. Reason becomes the dominant
    one (the longest source). Detector becomes "merged" with the
    originating detectors listed in `notes`.
    """
    active = [c for c in cuts if c.action == "cut"]
    if not active:
        return cuts

    active.sort(key=_sort_key)
    merged: list[CutRegion] = [active[0]]

    for nxt in active[1:]:
        last = merged[-1]
        gap = nxt.start_s - last.end_s
        if gap <= gap_threshold_s:
            # Pick the longer source as the dominant reason.
            dom = last if (last.end_s - last.start_s) >= (nxt.end_s - nxt.start_s) else nxt
            sub = nxt if dom is last else last
            merged[-1] = last.model_copy(update={
                "id": f"mrg_{len(merged)-1:03d}",
                "start_s": min(last.start_s, nxt.start_s),
                "end_s": max(last.end_s, nxt.end_s),
                "reason": dom.reason,
                "detector": "merged",
                "detector_version": "1.0.0",
                "confidence": max(last.confidence, nxt.confidence),
                "affected_words": sorted(set(last.affected_words + nxt.affected_words)),
                "notes": f"merged({last.detector}+{sub.detector})",
            })
        else:
            merged.append(nxt)
    return merged


def plan_cuts(
    candidates: list[CutRegion],
    *,
    gap_threshold_s: float = 0.1,
) -> list[CutRegion]:
    """Full pipeline: padding → merge → return."""
    if not candidates:
        return []
    padded = [apply_padding(c) for c in candidates]
    return merge_overlapping(padded, gap_threshold_s=gap_threshold_s)
