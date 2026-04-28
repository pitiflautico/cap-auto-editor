"""planner.py — orchestration for the broll_planner phase.

Responsibilities:
  1. Build context blocks from analysis + capture_manifest + (optional)
     visual_inventory.
  2. Run the LLM (Sonnet via the v6.llm pool) with the planner prompt.
  3. Validate the LLM JSON, drop bogus source_ref values, merge plans
     into a copy of the analysis (each beat's broll_hints filled in).
  4. Return the merged AnalysisResult + a PlannerReport.

Pure-text helpers (block builders, source_ref validator, merge) are
deterministic and unit-tested without hitting the LLM.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from analysis.contracts import AnalysisResult, BrollHint

from .contracts import BeatPlan, PlannerReport
from .prompts import build_planner_prompt

log = logging.getLogger("broll_planner")


# ── Context-block builders (deterministic) ──────────────────────────


def build_beats_block(analysis: AnalysisResult) -> str:
    """One line per beat with the planner-relevant fields. Compact JSON
    so the LLM sees structure without the full 50-field beat record.
    """
    lines: list[str] = []
    for b in analysis.narrative.beats:
        lines.append(json.dumps({
            "beat_id": b.beat_id,
            "start_s": round(b.start_s, 2),
            "end_s": round(b.end_s, 2),
            "ef": b.editorial_function,
            "energy": b.energy,
            "text": b.text,
            "hero": b.hero_text_candidate,
            "visual_need": getattr(b, "visual_need", "none"),
            "visual_anchor_type": getattr(b, "visual_anchor_type", None),
            "visual_subject": getattr(b, "visual_subject", None),
        }, ensure_ascii=False))
    return "\n".join(lines)


def build_entities_block(analysis: AnalysisResult) -> str:
    lines: list[str] = []
    for e in analysis.narrative.entities:
        lines.append(json.dumps({
            "canonical": e.canonical,
            "kind": e.kind,
            "official_urls": list(e.official_urls or []),
        }, ensure_ascii=False))
    return "\n".join(lines)


def build_sources_block(capture_manifest: dict) -> str:
    """Each capture entry → one JSON line with `slug`, `url`, `title`,
    `text_preview` (≤180 chars), and `assets` (list of relative
    paths). The planner uses this to pick `source_ref` byte-exact.
    """
    lines: list[str] = []
    for r in (capture_manifest.get("results") or []):
        if r.get("status") != "ok":
            continue
        req = r.get("request") or {}
        slug = req.get("slug") or ""
        url = req.get("url") or ""
        title = (r.get("title") or "").strip()[:120]
        text_prev = (r.get("text_preview") or "").strip().replace("\n", " ")[:180]
        artifacts = r.get("artifacts") or {}
        assets = []
        for a in (artifacts.get("assets") or []):
            assets.append({
                "kind": a.get("kind"),
                "path": a.get("path"),
                "width": a.get("width"),
                "height": a.get("height"),
            })
        lines.append(json.dumps({
            "slug": slug, "url": url, "title": title,
            "text_preview": text_prev, "assets": assets,
        }, ensure_ascii=False))
    return "\n".join(lines)


def build_inventory_block(visual_inventory: dict | None) -> str | None:
    """Optional Haiku-vision tags per asset. Empty/missing → None."""
    if not visual_inventory:
        return None
    assets = visual_inventory.get("assets") or []
    if not assets:
        return None
    lines: list[str] = []
    for a in assets:
        kfs = a.get("keyframes") or []
        kf = kfs[0] if kfs else {}
        lines.append(json.dumps({
            "slug": a.get("slug"),
            "asset_path": a.get("asset_path"),
            "shot_types": list(a.get("shot_types_seen") or []),
            "subjects": list((kf.get("subjects") or [])),
            "best_for": list((kf.get("best_for") or [])),
            "quality": a.get("overall_quality"),
        }, ensure_ascii=False))
    return "\n".join(lines)


# ── LLM JSON extraction + validation ────────────────────────────────


_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL,
)


def extract_json(raw: str) -> dict:
    """Pull the first JSON object out of an LLM response. Tolerates
    ```json fences and prose before/after.
    """
    raw = raw.strip()
    m = _JSON_FENCE_RE.search(raw)
    if m:
        return json.loads(m.group(1))
    # Fallback: grab the first { ... } that parses
    start = raw.find("{")
    if start < 0:
        raise ValueError("no JSON object found in LLM response")
    depth = 0
    for i in range(start, len(raw)):
        c = raw[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                chunk = raw[start:i + 1]
                return json.loads(chunk)
    raise ValueError("unbalanced braces in LLM response")


def _valid_slugs(capture_manifest: dict) -> set[str]:
    out: set[str] = set()
    for r in (capture_manifest.get("results") or []):
        slug = (r.get("request") or {}).get("slug")
        if slug:
            out.add(slug)
    return out


def sanitize_hint_dict(
    h: dict, *, valid_slugs: set[str], notes: list[str], beat_id: str,
) -> dict:
    """Coerce a raw LLM hint dict into something `BrollHint` can
    validate.

    Two classes of cleanup:
      • Stringly-typed nulls. The LLM (especially when reading the
        prompt's enum spec literally as text) sometimes emits the
        string ``"null"`` instead of JSON ``null`` on optional Literal
        fields. This used to drop 5/6 of an otherwise valid plan.
        Coerce ``"null"`` → ``None`` on every field that accepts None.
      • Bogus source_ref slugs. A hallucinated slug would mis-anchor
        the hint to nothing. Drop it (set to None) and log a note.
        Designed types (title/slide/mockup) MUST have source_ref=None
        regardless of what the LLM emitted — they are generated, not
        anchored.
    """
    out = dict(h)

    # Coerce stringly-typed nulls on all known optional fields.
    NULLABLE_FIELDS = (
        "capcut_effect", "source_ref", "query", "subject",
        "shot_type", "duration_target_s", "slide_kind",
        "mockup_kind", "layout", "palette",
    )
    for f in NULLABLE_FIELDS:
        v = out.get(f)
        if isinstance(v, str) and v.strip().lower() == "null":
            out[f] = None

    sr = out.get("source_ref")
    if sr and sr not in valid_slugs:
        notes.append(
            f"{beat_id}: dropped invalid source_ref {sr!r} "
            f"(not in <sources>)"
        )
        out["source_ref"] = None
    if out.get("type") in ("title", "slide", "mockup"):
        out["source_ref"] = None
    return out


# ── Merge plans into the analysis ───────────────────────────────────


def merge_plans_into_analysis(
    analysis: AnalysisResult,
    plans: list[BeatPlan],
    *,
    valid_slugs: set[str],
) -> tuple[AnalysisResult, PlannerReport]:
    """Apply each BeatPlan to the matching beat. Hints are validated
    by `BrollHint.model_validate` — any hint that fails validation is
    dropped and noted in the report.
    """
    plans_by_id = {p.beat_id: p for p in plans}
    notes: list[str] = []
    type_counts: dict[str, int] = {}
    source_ref_anchors = 0
    hints_emitted = 0
    beats_planned = 0

    new_beats = []
    for beat in analysis.narrative.beats:
        plan = plans_by_id.get(beat.beat_id)
        new_hints: list[BrollHint] = []
        if plan:
            for raw in plan.hints:
                clean = sanitize_hint_dict(
                    raw, valid_slugs=valid_slugs, notes=notes,
                    beat_id=beat.beat_id,
                )
                try:
                    hint = BrollHint.model_validate(clean)
                except Exception as exc:
                    notes.append(
                        f"{beat.beat_id}: dropped invalid hint — {exc}"
                    )
                    continue
                new_hints.append(hint)
                type_counts[hint.type] = type_counts.get(hint.type, 0) + 1
                if hint.source_ref:
                    source_ref_anchors += 1
                hints_emitted += 1
            if new_hints:
                beats_planned += 1
        new_beats.append(beat.model_copy(update={"broll_hints": new_hints}))

    new_analysis = analysis.model_copy(deep=True)
    new_analysis.narrative.beats = new_beats

    beats_required = sum(
        1 for b in analysis.narrative.beats
        if getattr(b, "visual_need", "none") == "required"
    )
    beats_optional = sum(
        1 for b in analysis.narrative.beats
        if getattr(b, "visual_need", "none") == "optional"
    )

    report = PlannerReport(
        created_at=datetime.now(timezone.utc),
        beats_total=len(analysis.narrative.beats),
        beats_required=beats_required,
        beats_optional=beats_optional,
        beats_planned=beats_planned,
        hints_emitted=hints_emitted,
        type_counts=type_counts,
        source_ref_anchors=source_ref_anchors,
        notes=notes,
        plans=list(plans),
    )
    return new_analysis, report


# ── LLM call ────────────────────────────────────────────────────────


def call_planner_llm(
    *,
    analysis: AnalysisResult,
    capture_manifest: dict,
    visual_inventory: dict | None,
    model: str = "sonnet",
    timeout_s: int = 300,
) -> list[BeatPlan]:
    """Build the prompt, call Sonnet, return parsed plans.

    Lazy-imports the LLM pool so unit tests that monkeypatch the
    module don't pull the SDK transitively.
    """
    from llm.claude_pool import run_sync

    prompt = build_planner_prompt(
        duration_s=analysis.duration_s or 0.0,
        language=analysis.language or "en",
        beats_block=build_beats_block(analysis),
        entities_block=build_entities_block(analysis),
        sources_block=build_sources_block(capture_manifest),
        inventory_block=build_inventory_block(visual_inventory),
    )

    res = run_sync(
        prompt,
        allowed_tools=[],
        model=model,
        timeout_s=timeout_s,
        max_turns=1,
    )
    if not res.success:
        raise RuntimeError(
            f"broll_planner LLM call failed (exit_code={res.exit_code}, "
            f"duration_ms={res.duration_ms}): {res.output[:300]!r}"
        )
    payload = extract_json(res.output)
    raw_plans = payload.get("plans") or []
    plans: list[BeatPlan] = []
    for p in raw_plans:
        plans.append(BeatPlan.model_validate(p))
    return plans
