"""Adaptive balancer: enforce industry baselines + visual_inventory awareness.

Inputs:
  - AnalysisResult (the 'brainstorm' from the analysis phase)
  - VisualInventory (per-asset segments from visual_inventory)
Outputs:
  - balanced AnalysisResult (same narrative, broll_hints anchored or pruned)
  - FinalizerReport with per-element decisions
"""
from __future__ import annotations

from datetime import datetime, timezone

from analysis.contracts import AnalysisResult, Beat, BrollHint
from visual_inventory.contracts import VisualInventory

from .contracts import (
    BeatDecision,
    FinalizerReport,
    HintDecision,
    IndustryBaselines,
)
from .scorer import (
    FILLER_TYPES,
    REAL_FOOTAGE_TYPES,
    adaptive_broll_target,
    best_segment_for_hint,
    compute_material_score,
    downgrade_target,
    material_strength_tier,
)


_ANCHOR_THRESHOLD = 0.45     # below this we don't anchor
_DROP_SUBJECT_THRESHOLD = 0.30  # below + has a subject + no inventory match → drop


def _coverage_pct(beats: list[Beat], duration_s: float) -> float:
    """Approximate broll coverage = sum of hint span / duration. May overcount overlaps."""
    if duration_s <= 0:
        return 0.0
    total = 0.0
    for b in beats:
        bd = max(0.0, b.end_s - b.start_s)
        for h in b.broll_hints or []:
            inp = max(0.0, min(1.0, h.timing.in_pct))
            outp = max(inp, min(1.0, h.timing.out_pct))
            total += bd * (outp - inp)
    return min(1.0, total / duration_s)


def _type_ratios(beats: list[Beat]) -> tuple[float, float, int]:
    total = 0
    real = 0
    filler = 0
    for b in beats:
        for h in b.broll_hints or []:
            total += 1
            if h.type in REAL_FOOTAGE_TYPES:
                real += 1
            elif h.type in FILLER_TYPES:
                filler += 1
    if total == 0:
        return (0.0, 0.0, 0)
    return (real / total, filler / total, total)


def balance(
    analysis: AnalysisResult,
    inventory: VisualInventory,
    *,
    baselines: IndustryBaselines | None = None,
) -> tuple[AnalysisResult, FinalizerReport]:
    baselines = baselines or IndustryBaselines()
    duration = analysis.duration_s or 0.0
    score = compute_material_score(
        inventory.assets, list(analysis.narrative.entities)
    )
    tier = material_strength_tier(score)
    cov_min, cov_max = adaptive_broll_target(score)

    report = FinalizerReport(
        created_at=datetime.now(timezone.utc),
        duration_s=duration,
        material_score=round(score, 3),
        material_strength=tier,             # type: ignore[arg-type]
        broll_target_min=cov_min,
        broll_target_max=cov_max,
        baselines=baselines,
    )

    # Stats before
    real_b, fill_b, hints_b = _type_ratios(analysis.narrative.beats)
    report.beats_before = len(analysis.narrative.beats)
    report.hints_before = hints_b
    report.coverage_pct_before = round(
        100 * _coverage_pct(analysis.narrative.beats, duration), 1
    )
    report.real_footage_ratio_before = round(real_b, 3)
    report.filler_ratio_before = round(fill_b, 3)

    new_beats: list[Beat] = []
    for beat in analysis.narrative.beats:
        new_hints: list[BrollHint] = []
        for hi, hint in enumerate(beat.broll_hints or []):
            best = best_segment_for_hint(
                hint, beat.editorial_function, inventory.assets,
            )
            score_h = best[2] if best else 0.0

            # Decision tree
            if best and score_h >= _ANCHOR_THRESHOLD:
                asset, seg, _ = best
                new_h = hint.model_copy(update={
                    "source_ref": asset.slug,
                    # Embed segment as a sub-document via description suffix —
                    # schema doesn't carry segment_t directly yet (next bump);
                    # for now we leave description with explicit anchor.
                    "description": f"{hint.description}  [@ {asset.asset_path} {seg.t_start_s:.1f}-{seg.t_end_s:.1f}s]",
                })
                new_hints.append(new_h)
                report.hint_decisions.append(HintDecision(
                    beat_id=beat.beat_id, hint_index=hi,
                    action="anchored",
                    rationale=f"strong inventory match (score {score_h:.2f}) on {asset.slug}",
                    chosen_slug=asset.slug,
                    chosen_asset_path=asset.asset_path,
                    chosen_t_start_s=seg.t_start_s,
                    chosen_t_end_s=seg.t_end_s,
                ))
                continue

            # No strong anchor — decide drop / downgrade / keep
            has_subject = bool(hint.subject)
            if has_subject and score_h <= _DROP_SUBJECT_THRESHOLD:
                # Subject named but no visual support → drop instead of stocking
                report.hint_decisions.append(HintDecision(
                    beat_id=beat.beat_id, hint_index=hi,
                    action="dropped",
                    rationale=f"subject {hint.subject!r} has no visual support (score {score_h:.2f})",
                ))
                continue

            # Downgrade if filler is over budget OR thin material tier
            if (tier == "thin" and hint.type in REAL_FOOTAGE_TYPES) \
                or (hint.type in FILLER_TYPES and tier != "rich"):
                old_t = hint.type
                new_t = downgrade_target(hint.type)
                if new_t != old_t:
                    new_h = hint.model_copy(update={"type": new_t})
                    new_hints.append(new_h)
                    report.hint_decisions.append(HintDecision(
                        beat_id=beat.beat_id, hint_index=hi,
                        action="downgraded",
                        rationale=f"no inventory backing for {old_t}; tier={tier}",
                        old_type=old_t, new_type=new_t,
                    ))
                    continue

            # Default: keep as-is
            new_hints.append(hint)
            report.hint_decisions.append(HintDecision(
                beat_id=beat.beat_id, hint_index=hi,
                action="kept",
                rationale=(f"score {score_h:.2f} below anchor threshold "
                           f"but type/tier acceptable"),
            ))

        new_beat = beat.model_copy(update={"broll_hints": new_hints})
        new_beats.append(new_beat)
        report.beat_decisions.append(BeatDecision(
            beat_id=beat.beat_id, action="kept",
            rationale=f"{len(new_hints)} hint(s) after balancing",
        ))

    # Build new analysis
    new_analysis = analysis.model_copy(deep=True)
    new_analysis.narrative.beats = new_beats

    # Stats after
    real_a, fill_a, hints_a = _type_ratios(new_beats)
    report.beats_after = len(new_beats)
    report.hints_after = hints_a
    report.coverage_pct_after = round(
        100 * _coverage_pct(new_beats, duration), 1
    )
    report.real_footage_ratio_after = round(real_a, 3)
    report.filler_ratio_after = round(fill_a, 3)

    # Notes for the operator
    if report.coverage_pct_after / 100 < cov_min:
        report.notes.append(
            f"coverage {report.coverage_pct_after}% below target {cov_min*100:.0f}% — "
            f"capture more official material or accept thin tier"
        )
    if real_a < baselines.real_footage_ratio_min and tier != "thin":
        report.notes.append(
            f"real footage ratio {real_a:.0%} below baseline "
            f"{baselines.real_footage_ratio_min:.0%}"
        )
    if fill_a > baselines.filler_ratio_max:
        report.notes.append(
            f"filler ratio {fill_a:.0%} above baseline "
            f"{baselines.filler_ratio_max:.0%}"
        )

    return new_analysis, report
