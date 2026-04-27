"""LLM-based semantic matching of beats to inventory segments.

Reuses the existing ClaudePool (Haiku default). Calls are independent —
parallelised with a ThreadPoolExecutor (8 workers).
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from analysis.contracts import AnalysisResult, Beat, BrollHint
from visual_inventory.contracts import AssetInventory, VisualInventory

from .contracts import (
    BeatDecision,
    CandidateRow,
    MatcherReport,
)

log = logging.getLogger("broll_matcher")


# Window: candidates within this score gap from the best are sent to the LLM.
_CANDIDATE_SCORE_WINDOW = 0.20
_MAX_CANDIDATES = 6
_MIN_CANDIDATES_FOR_LLM = 2     # if only 1 candidate, no need to call LLM


_PROMPT = """\
You are a senior short-form video editor. For one beat of a video,
choose which inventory segment best illustrates what the speaker is
saying in that beat.

BEAT TEXT (literal transcript):
{beat_text}

EDITORIAL FUNCTION: {editorial_function}

CANDIDATE SEGMENTS (numbered):
{candidates_block}

Pick the candidate whose visual content most directly supports the spoken
words. Prefer literal illustration over thematic mood. Reply with JSON only:

{{"chosen_idx": <0-based index>, "rationale": "<one short sentence>"}}
"""


@dataclass
class _CandWithSeg:
    asset: AssetInventory
    seg: any         # visual_inventory.contracts.Segment
    det_score: float


# ── Anchor parsing — same regex as broll_resolver ──────────────────

_ANCHOR_RE = re.compile(
    r"\[@\s*(?P<path>[^\s]+)\s+(?P<t1>\d+(?:\.\d+)?)-(?P<t2>\d+(?:\.\d+)?)s\s*\]"
)


def _parse_anchor(description: str) -> tuple[str, float, float] | None:
    m = _ANCHOR_RE.search(description or "")
    if not m:
        return None
    return m.group("path"), float(m.group("t1")), float(m.group("t2"))


def _replace_anchor(description: str, asset_path: str,
                    t1: float, t2: float) -> str:
    new_anchor = f"[@ {asset_path} {t1:.1f}-{t2:.1f}s]"
    if _ANCHOR_RE.search(description or ""):
        return _ANCHOR_RE.sub(new_anchor, description, count=1)
    return f"{description}  {new_anchor}"


# ── Score parity with script_finalizer.scorer ──────────────────────
# Kept as a small local helper so we can rank candidates independently
# from script_finalizer (avoids a hard dep cycle).

def _det_score(hint: BrollHint, ef: str, asset: AssetInventory, seg) -> float:
    """Mirrors script_finalizer.scorer.best_segment_for_hint without penalty."""
    hint_subj = (hint.subject or "").lower().strip()
    hint_shot = hint.shot_type or ""

    kf_subjects: set[str] = set()
    for k in asset.keyframes:
        for s in k.subjects:
            kf_subjects.add(s.lower())
    if hint_subj:
        if any(hint_subj in s or s in hint_subj for s in kf_subjects):
            subj_score = 1.0
        elif kf_subjects:
            return 0.0   # hard gate
        else:
            subj_score = 0.5
    else:
        subj_score = 0.5

    ef_match = any(ef in k.best_for for k in asset.keyframes)
    ef_score = 1.0 if ef_match else 0.0
    shot_score = 1.0 if (hint_shot and seg.shot_type == hint_shot) else (
        0.5 if not hint_shot else 0.0
    )
    return (subj_score + shot_score + ef_score + seg.score) / 4.0


def _candidates_for_hint(
    hint: BrollHint, ef: str, inventory: VisualInventory,
) -> list[_CandWithSeg]:
    """All (asset, seg) above 0 score, sorted desc by deterministic score."""
    out: list[_CandWithSeg] = []
    for a in inventory.assets:
        for s in a.best_segments:
            sc = _det_score(hint, ef, a, s)
            if sc > 0:
                out.append(_CandWithSeg(asset=a, seg=s, det_score=sc))
    out.sort(key=lambda c: -c.det_score)
    if not out:
        return []
    top = out[0].det_score
    return [c for c in out if c.det_score >= top - _CANDIDATE_SCORE_WINDOW][:_MAX_CANDIDATES]


# ── LLM call ───────────────────────────────────────────────────────

def _build_prompt(beat: Beat, candidates: list[_CandWithSeg]) -> str:
    lines = []
    for i, c in enumerate(candidates):
        lines.append(
            f"[{i}] {c.asset.slug}/{c.asset.asset_path} ({c.seg.t_start_s:.1f}-{c.seg.t_end_s:.1f}s)\n"
            f"     shot_type={c.seg.shot_type or '-'}, q={c.seg.quality}\n"
            f"     description: {(c.seg.description or '')[:180]}"
        )
    return _PROMPT.format(
        beat_text=(beat.text or "")[:500],
        editorial_function=beat.editorial_function or "-",
        candidates_block="\n\n".join(lines),
    )


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


def _llm_pick(beat: Beat, candidates: list[_CandWithSeg],
              *, run_fn=None, model: str = "haiku",
              timeout_s: int = 60) -> tuple[int | None, str]:
    """Returns (chosen_idx, rationale). chosen_idx None on any failure."""
    if run_fn is None:
        try:
            from llm import run_sync as _real     # type: ignore

            def run_fn(prompt, **kw):              # type: ignore[no-redef]
                kw.setdefault("model", model)
                kw.setdefault("allowed_tools", [])
                kw.setdefault("max_turns", 1)
                return _real(prompt, **kw)
        except ImportError:
            return None, "llm.run_sync not importable"

    try:
        resp = run_fn(_build_prompt(beat, candidates), timeout_s=timeout_s)
    except Exception as exc:
        return None, f"llm call failed: {exc}"

    text = (getattr(resp, "output", None) or getattr(resp, "text", None)
            or (resp if isinstance(resp, str) else ""))
    data = _extract_json(text)
    if not isinstance(data, dict):
        return None, "malformed JSON"
    idx = data.get("chosen_idx")
    if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
        return None, f"invalid chosen_idx {idx!r}"
    return idx, str(data.get("rationale") or "")[:200]


# ── Orchestration ─────────────────────────────────────────────────

def match(
    analysis: AnalysisResult,
    inventory: VisualInventory,
    *,
    run_fn: Callable | None = None,
    parallel_workers: int = 8,
) -> tuple[AnalysisResult, MatcherReport]:
    """For every beat with an anchored broll_hint, ask the LLM to pick
    among the top candidates.

    Returns the (possibly rewritten) analysis + a report.
    """
    report = MatcherReport(created_at=datetime.now(timezone.utc))
    new_beats = []

    # Collect all hints that need a decision (parallel-friendly)
    work_items: list[tuple[int, int, Beat, BrollHint, list[_CandWithSeg]]] = []
    for bi, beat in enumerate(analysis.narrative.beats):
        new_hints = list(beat.broll_hints or [])
        for hi, hint in enumerate(new_hints):
            anchor = _parse_anchor(hint.description or "")
            if anchor is None:
                continue   # not anchored — nothing to match
            cands = _candidates_for_hint(hint, beat.editorial_function, inventory)
            report.total_beats_with_anchor += 1
            if len(cands) < _MIN_CANDIDATES_FOR_LLM:
                # Trivially keep the deterministic pick
                report.kept_deterministic += 1
                report.decisions.append(BeatDecision(
                    beat_id=beat.beat_id, hint_index=hi,
                    beat_text=(beat.text or "")[:200],
                    editorial_function=beat.editorial_function,
                    n_candidates=len(cands),
                    chosen_idx=0 if cands else None,
                    rationale="single candidate — kept deterministic",
                ))
                continue
            work_items.append((bi, hi, beat, hint, cands))

    # Run LLM picks in parallel
    def _work(item):
        bi, hi, beat, hint, cands = item
        idx, rat = _llm_pick(beat, cands, run_fn=run_fn)
        return (bi, hi, beat, hint, cands, idx, rat)

    with ThreadPoolExecutor(max_workers=max(1, parallel_workers)) as ex:
        results = list(ex.map(_work, work_items))

    # Apply decisions back to the analysis
    rewrites: dict[tuple[int, int], tuple[str, float, float]] = {}
    for bi, hi, beat, hint, cands, idx, rat in results:
        if idx is None:
            # Fallback — keep deterministic top
            report.fallback_count += 1
            chosen = cands[0]
            chosen_idx_used = 0
        else:
            chosen = cands[idx]
            chosen_idx_used = idx

        # Only rewrite if LLM picked a DIFFERENT (asset, t_start) than the
        # deterministic top
        det_top = cands[0]
        is_re_anchored = (
            chosen.asset.slug != det_top.asset.slug
            or abs(chosen.seg.t_start_s - det_top.seg.t_start_s) > 0.01
        )
        if is_re_anchored:
            report.re_anchored_count += 1
        else:
            report.kept_deterministic += 1

        rewrites[(bi, hi)] = (
            chosen.asset.asset_path,
            chosen.seg.t_start_s,
            chosen.seg.t_end_s,
        )

        rows = [CandidateRow(
            slug=c.asset.slug, asset_path=c.asset.asset_path,
            t_start_s=c.seg.t_start_s, t_end_s=c.seg.t_end_s,
            description=(c.seg.description or "")[:300],
            deterministic_score=round(c.det_score, 3),
            chosen=(j == chosen_idx_used),
        ) for j, c in enumerate(cands)]
        report.decisions.append(BeatDecision(
            beat_id=beat.beat_id, hint_index=hi,
            beat_text=(beat.text or "")[:200],
            editorial_function=beat.editorial_function,
            n_candidates=len(cands),
            chosen_idx=chosen_idx_used,
            rationale=rat,
            fallback_used=(idx is None),
            candidates=rows,
        ))

    # Build new analysis with rewritten descriptions
    for bi, beat in enumerate(analysis.narrative.beats):
        new_hints: list[BrollHint] = []
        for hi, hint in enumerate(beat.broll_hints or []):
            if (bi, hi) in rewrites:
                ap, t1, t2 = rewrites[(bi, hi)]
                new_desc = _replace_anchor(hint.description, ap, t1, t2)
                new_hints.append(hint.model_copy(update={"description": new_desc}))
            else:
                new_hints.append(hint)
        new_beats.append(beat.model_copy(update={"broll_hints": new_hints}))

    new_analysis = analysis.model_copy(deep=True)
    new_analysis.narrative.beats = new_beats
    return new_analysis, report
