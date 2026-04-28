"""analyzer.py — Orchestrator for the analysis phase.

Entry point: run(transcript_path, out_dir, ...)
  1. load   — read transcript + optional sources
  2. prompt — build the LLM prompt
  3. llm_call — call llm.complete(); retry once on validation error
  4. validate — AnalysisResult.model_validate(...)
  5. postprocess — split_long_beats, close_beat_gaps, consolidate_duplicates
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .contracts import AnalysisResult, Beat, Narrative, ValidationOverride
from .postprocess import (
    close_beat_gaps,
    consolidate_consecutive_duplicates,
    split_long_beats,
)
from .prompts import build_analysis_prompt

log = logging.getLogger("analysis.analyzer")

# ─── editorial_function remapping (handles LLM drift) ─────────────────────────
_ENUM_MAP: dict[str, str] = {
    "context": "transition", "insight": "thesis",
    "setup": "hook", "intro": "hook", "outro": "payoff",
    "cta": "payoff", "call_to_action": "payoff",
    "explanation": "proof", "detail": "proof",
    "narration": "transition", "bridge": "transition",
    "summary": "thesis", "conclusion": "thesis",
    "benefit": "value", "feature": "value",
    "problem": "pain", "question": "thesis",
}
_VALID_EF = frozenset(
    {"hook", "pain", "solution", "proof", "value", "how_to",
     "thesis", "payoff", "transition"}
)


def _remap_editorial_functions(narrative_dict: dict) -> dict:
    """Normalise unknown editorial_function values in beats before validation."""
    beats = narrative_dict.get("beats") or []
    for b in beats:
        ef = (b.get("editorial_function") or "").lower()
        if ef and ef not in _VALID_EF:
            mapped = _ENUM_MAP.get(ef, "transition")
            log.info("remap editorial_function %r → %r on %s",
                     ef, mapped, b.get("beat_id", "?"))
            b["editorial_function"] = mapped
    return narrative_dict


_VALID_CAPCUT = frozenset({
    "zoom_in_punch", "glitch_rgb", "logo_reveal", "velocity_edit",
    "mask_reveal", "split_screen", "slow_motion", "flicker",
})
_NULL_LIKE = frozenset({"null", "none", "n/a", "na", ""})


def _remap_broll_hints(narrative_dict: dict) -> dict:
    """Normalise broll_hints fields before validation.

    LLMs return many variants for "no value": "null", "None", "Null",
    "n/a", empty string. Pydantic literal validation rejects any of
    these. We coerce all non-canonical values to None.

    Also normalises the v2.0 visual_* fields on each beat — same
    failure mode (LLM emits "null" string) on visual_anchor_type /
    visual_subject / hero_text_candidate.
    """
    beats = narrative_dict.get("beats") or []
    for b in beats:
        # v2.0 visual_need brief
        for fld in ("visual_anchor_type", "visual_subject",
                    "hero_text_candidate"):
            v = b.get(fld)
            if v is not None and isinstance(v, str) \
                    and v.strip().lower() in _NULL_LIKE:
                b[fld] = None
        # visual_need is REQUIRED by the schema as a literal — accept
        # the string "none" verbatim (it's a valid value), but coerce
        # other null-likes / unknown values to "none" so the run
        # doesn't die on a typo.
        vn = b.get("visual_need")
        if vn is None or (isinstance(vn, str)
                          and vn.strip().lower() in {"null", "n/a", ""}):
            b["visual_need"] = "none"
        hints = b.get("broll_hints") or []
        for h in hints:
            # capcut_effect: must be in the literal enum or None.
            ce = h.get("capcut_effect")
            if ce is not None and (
                not isinstance(ce, str)
                or ce.strip().lower() in _NULL_LIKE
                or ce not in _VALID_CAPCUT
            ):
                log.info("remap capcut_effect %r → None on hint in %s",
                         ce, b.get("beat_id", "?"))
                h["capcut_effect"] = None

            # source_ref: optional string, anything null-like → None.
            sr = h.get("source_ref")
            if sr is not None and (
                not isinstance(sr, str)
                or sr.strip().lower() in _NULL_LIKE
            ):
                h["source_ref"] = None

            # timing: object with in_pct/out_pct ∈ [0,1]. Default if missing/invalid.
            timing = h.get("timing")
            if not isinstance(timing, dict):
                h["timing"] = {"in_pct": 0.0, "out_pct": 1.0}
            else:
                for k, default in (("in_pct", 0.0), ("out_pct", 1.0)):
                    v = timing.get(k)
                    if not isinstance(v, (int, float)) or v < 0 or v > 1:
                        timing[k] = default

            # type / energy_match: leave validation to Pydantic — the prompt
            # gives a closed enum; if LLM hallucinates, we want to know
            # via the retry mechanism, not silently coerce.
    return narrative_dict


# ─── source loading ────────────────────────────────────────────────────────────

def _load_sources(
    capture_manifest_path: Path,
    max_chars_per_source: int = 1500,
) -> list[dict]:
    """Read capture_manifest.json and load first max_chars of each text.txt."""
    manifest = json.loads(capture_manifest_path.read_text(encoding="utf-8"))
    out_dir = Path(manifest.get("out_dir", capture_manifest_path.parent))
    sources: list[dict] = []

    for result in manifest.get("results", []):
        if result.get("status") != "ok":
            continue
        req = result.get("request", {})
        slug = req.get("slug", "")
        url = req.get("normalized_url") or req.get("url") or ""
        artifacts = result.get("artifacts") or {}
        text_rel = artifacts.get("text_path")
        if not text_rel:
            continue
        text_path = out_dir / "captures" / slug / text_rel
        if not text_path.exists():
            continue

        raw = text_path.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        title = lines[0].strip() if lines else slug
        preview = raw[:max_chars_per_source]

        sources.append({"slug": slug, "url": url, "title": title,
                        "text_preview": preview})

    return sources


# ─── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Extract a JSON object from LLM output.

    Three layers of tolerance, applied in order:
      1. Strip ``` markdown fences if present.
      2. Try strict `json.loads` on the stripped text.
      3. Try strict `json.loads` on the slice between the first `{`
         and the last `}` (drops any trailing prose / `}\n```` etc.).
      4. Repair-parse: walk the slice and find the rightmost `}`
         that yields a balanced object; strip trailing commas before
         `]` / `}` (a recurring DeepSeek failure mode on long outputs);
         retry json.loads on that.

    Raises the last JSONDecodeError if every layer fails so the caller
    can persist the raw text for human inspection.
    """
    import re
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s.rstrip())
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    start = s.find("{")
    end = s.rfind("}")
    if start < 0 or end <= start:
        raise json.JSONDecodeError("no JSON object delimiters found",
                                    s, 0)

    snippet = s[start:end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError as first_err:
        # Layer 4 — repair-parse. DeepSeek-v4-flash sometimes truncates
        # mid-object on long outputs and the very last brace it emits
        # is unbalanced; we look for the rightmost `}` whose prefix
        # has matched braces and strip trailing commas.
        repaired = _repair_truncated_json(snippet)
        if repaired is None:
            raise first_err
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            raise first_err


def _repair_truncated_json(snippet: str) -> str | None:
    """Best-effort repair of a JSON object that:
      • has trailing commas before `]` or `}` (LLM artefact), and/or
      • is truncated past the last balanced closing `}`.

    Returns the repaired snippet, or None if no balanced prefix exists.
    """
    import re
    # Strip trailing commas (`,]` and `,}`) — common LLM tic on lists.
    cleaned = re.sub(r",(\s*[}\]])", r"\1", snippet)

    # Walk forward, track depth; remember the position right after each
    # closing `}` that brings depth back to 0. The rightmost such
    # position is the largest balanced JSON object the LLM produced.
    depth = 0
    in_string = False
    escape = False
    last_balanced_end = -1
    for i, ch in enumerate(cleaned):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_balanced_end = i + 1
            elif depth < 0:
                return None
    if last_balanced_end < 0:
        return None
    return cleaned[:last_balanced_end]


# ─── Main run ──────────────────────────────────────────────────────────────────

def run(
    transcript_path: Path,
    out_dir: Path,
    *,
    capture_manifest_path: Path | None = None,
    language: str = "es",
    llm_provider: str = "claude_pool",
    llm_model: str = "sonnet",
    no_sources: bool = False,
    strict_numeric: bool = True,
    overrides: list[ValidationOverride] | None = None,
    _emitter: Any = None,  # ProgressEmitter | NullEmitter
) -> AnalysisResult:
    """Run the full analysis phase.

    Steps (emitted as progress events):
      1 load        — read transcript + sources
      2 prompt      — build the LLM prompt
      3 llm_call    — call llm.complete(); retry once on failure
      4 validate    — AnalysisResult.model_validate(...)
      5 postprocess — split_long_beats, close_beat_gaps, consolidate
    """
    from llm import complete
    from progress import ProgressEmitter, NullEmitter

    out_dir.mkdir(parents=True, exist_ok=True)
    progress_path = out_dir / "progress.jsonl"

    if _emitter is None:
        _emitter = ProgressEmitter(progress_path)
    _emitter.emit_run_start(phase="analysis", total_steps=5)

    TOTAL = 5

    # ── Step 1: load ──────────────────────────────────────────────────────────
    t0 = time.monotonic()
    _emitter.emit_step_start(index=1, total=TOTAL, name="load",
                             detail="reading transcript + sources")

    transcript_data = json.loads(transcript_path.read_text(encoding="utf-8"))
    segments: list[dict] = transcript_data.get("segments", [])
    duration_s: float = float(transcript_data.get("duration_s", 0.0))
    # Language priority: transcript.language > explicit `language` argument
    # (unless 'auto') > fallback "es". Forcing the wrong code here makes the
    # LLM emit Spanish prose over an English transcript (or vice versa).
    transcript_lang = transcript_data.get("language")
    if transcript_lang and transcript_lang != "unknown":
        detected_language = transcript_lang
    elif language and language != "auto":
        detected_language = language
    else:
        detected_language = "es"

    sources: list[dict] = []
    if capture_manifest_path and not no_sources:
        try:
            sources = _load_sources(capture_manifest_path)
        except Exception as e:
            log.warning("Could not load sources from capture manifest: %s", e)

    load_ms = int((time.monotonic() - t0) * 1000)
    _emitter.emit_step_done(
        index=1, name="load", duration_ms=load_ms,
        summary={
            "segments": len(segments),
            "duration_s": duration_s,
            "sources_loaded": len(sources),
        },
    )

    # ── Step 2: prompt ────────────────────────────────────────────────────────
    t0 = time.monotonic()
    _emitter.emit_step_start(index=2, total=TOTAL, name="prompt",
                             detail="building LLM prompt")

    prompt = build_analysis_prompt(
        transcript_segments=segments,
        duration_s=duration_s,
        language=detected_language,
        sources=sources if sources else None,
    )

    prompt_ms = int((time.monotonic() - t0) * 1000)
    _emitter.emit_step_done(
        index=2, name="prompt", duration_ms=prompt_ms,
        summary={"prompt_chars": len(prompt), "sources_in_prompt": len(sources)},
    )

    # ── Step 3: llm_call ──────────────────────────────────────────────────────
    t0 = time.monotonic()
    _emitter.emit_step_start(index=3, total=TOTAL, name="llm_call",
                             detail=f"calling {llm_provider}/{llm_model}")

    # Streaming: print chunks to stderr so the operator sees progress live.
    import sys
    _seen_chars = {"n": 0}
    def _on_text(chunk: str) -> None:
        _seen_chars["n"] += len(chunk)
        sys.stderr.write(chunk)
        sys.stderr.flush()
    def _on_thinking(chunk: str) -> None:
        # Distinguish thinking from final output visually.
        sys.stderr.write(f"\n\033[2m[thinking]\033[0m {chunk}\n")
        sys.stderr.flush()

    # Retry loop: claude_pool can hit rate limits that cause [TIMEOUT].
    # On timeout, wait and retry with exponential backoff (max 3 attempts).
    resp = None
    last_error: str = ""
    MAX_ATTEMPTS = 2  # was 3 — long timeouts × 3 = unbearable wall time
    for attempt in range(MAX_ATTEMPTS):
        if attempt > 0:
            wait_s = 15
            log.warning(
                "LLM call timed out (attempt %d/%d); waiting %ds before retry",
                attempt, MAX_ATTEMPTS, wait_s,
            )
            time.sleep(wait_s)

        sys.stderr.write(f"\n--- LLM stream (attempt {attempt+1}/3) ---\n")
        sys.stderr.flush()
        resp = complete(
            prompt,
            provider=llm_provider,
            model=llm_model,
            as_json=True,
            timeout_s=300,
            max_turns=1,
            allowed_tools=[],  # pure-text task: no Read/Bash/Grep — forces direct JSON output
            on_text=_on_text,
            on_thinking=_on_thinking,
        )
        sys.stderr.write(f"\n--- end stream (chars={_seen_chars['n']}) ---\n")
        sys.stderr.flush()

        if resp.success or not resp.text.endswith("[TIMEOUT]"):
            break
        last_error = resp.text

    llm_ms = int((time.monotonic() - t0) * 1000)

    if not resp.success:
        raise RuntimeError(
            f"LLM call failed after 3 attempts (provider={llm_provider}, model={llm_model}): "
            f"{resp.text[:200]}"
        )

    # Always persist the LLM raw output — when JSON parsing fails
    # the only way to debug is to look at what came back.
    try:
        (out_dir / "llm_raw.txt").write_text(resp.text or "", encoding="utf-8")
    except Exception:
        pass

    raw_data: dict | None = resp.json_data
    if raw_data is None:
        try:
            raw_data = _extract_json(resp.text)
        except Exception as e:
            raise RuntimeError(
                f"Could not extract JSON from LLM response: {e}\n"
                f"Raw saved to: {out_dir / 'llm_raw.txt'}\n"
                f"Response preview: {resp.text[:500]}"
            ) from e

    _emitter.emit_step_done(
        index=3, name="llm_call", duration_ms=llm_ms,
        summary={"provider": llm_provider, "model": llm_model},
    )

    # ── Step 4: validate ──────────────────────────────────────────────────────
    t0 = time.monotonic()
    _emitter.emit_step_start(index=4, total=TOTAL, name="validate",
                             detail="validating LLM output against schema")

    narrative_dict = raw_data.get("narrative", raw_data)
    narrative_dict = _remap_editorial_functions(narrative_dict)
    narrative_dict = _remap_broll_hints(narrative_dict)

    validation_errors: list[str] = []
    try:
        narrative = Narrative.model_validate(narrative_dict)
    except ValidationError as e:
        validation_errors = [str(err) for err in e.errors()]
        log.warning("Validation failed (%d errors); retrying with reminder",
                    len(validation_errors))

        # One retry with reminder
        reminder = (
            "Previous output had these validation errors:\n"
            + "\n".join(f"- {err}" for err in validation_errors[:10])
            + "\n\nFix them and re-emit JSON only, no prose."
        )
        retry_prompt = prompt + "\n\n" + reminder
        retry_resp = complete(
            retry_prompt,
            provider=llm_provider,
            model=llm_model,
            as_json=True,
            timeout_s=300,
            max_turns=1,
            allowed_tools=[],
        )

        try:
            (out_dir / "llm_raw_retry.txt").write_text(
                retry_resp.text or "", encoding="utf-8"
            )
        except Exception:
            pass
        retry_data = retry_resp.json_data
        if retry_data is None:
            try:
                retry_data = _extract_json(retry_resp.text)
            except Exception as e2:
                raise RuntimeError(
                    f"Retry also failed to produce valid JSON: {e2}\n"
                    f"Raw saved to: {out_dir / 'llm_raw_retry.txt'}"
                ) from e2

        narrative_dict2 = retry_data.get("narrative", retry_data)
        narrative_dict2 = _remap_editorial_functions(narrative_dict2)
        narrative_dict2 = _remap_broll_hints(narrative_dict2)
        try:
            narrative = Narrative.model_validate(narrative_dict2)
        except ValidationError as e3:
            raise RuntimeError(
                f"LLM output invalid after retry. Errors:\n{e3}"
            ) from e3

    validate_ms = int((time.monotonic() - t0) * 1000)
    _emitter.emit_step_done(
        index=4, name="validate", duration_ms=validate_ms,
        summary={
            "arc_acts": len(narrative.arc_acts),
            "beats": len(narrative.beats),
            "topics": len(narrative.topics),
            "entities": len(narrative.entities),
            "validation_errors": len(validation_errors),
        },
    )

    # ── Step 5: postprocess ───────────────────────────────────────────────────
    t0 = time.monotonic()
    _emitter.emit_step_start(index=5, total=TOTAL, name="postprocess",
                             detail="split_long_beats, close_gaps, consolidate")

    beats: list[Beat] = list(narrative.beats)
    pp_details: list[str] = []

    before = len(beats)
    beats = split_long_beats(beats, max_s=12.0, segments=segments)
    if len(beats) != before:
        pp_details.append(f"split {len(beats) - before} long beats")

    beats = close_beat_gaps(beats, tolerance_s=0.15)
    pp_details.append("close_beat_gaps done")

    before = len(beats)
    beats = consolidate_consecutive_duplicates(beats, threshold=0.75)
    if len(beats) != before:
        pp_details.append(f"consolidated {before - len(beats)} duplicate beats")

    narrative = narrative.model_copy(update={"beats": beats})

    pp_ms = int((time.monotonic() - t0) * 1000)
    _emitter.emit_step_done(
        index=5, name="postprocess", duration_ms=pp_ms,
        summary={
            "beats_final": len(beats),
            "details": pp_details,
        },
    )

    # ── Assemble (unvalidated) ─────────────────────────────────────────────────
    result = AnalysisResult(
        created_at=datetime.now(timezone.utc),
        transcript_ref=str(transcript_path),
        capture_manifest_ref=str(capture_manifest_path) if capture_manifest_path else None,
        language=detected_language,
        duration_s=duration_s,
        llm_provider=llm_provider,
        llm_model=llm_model,
        narrative=narrative,
    )

    # Always emit the unvalidated snapshot for human inspection / debugging.
    unvalidated_path = out_dir / "analysis_unvalidated.json"
    unvalidated_path.write_text(result.model_dump_json(indent=2, by_alias=True),
                                encoding="utf-8")

    # ── Run deterministic post-LLM validators ─────────────────────────────────
    from .validate import run_all_validators

    result, validation_report = run_all_validators(
        result,
        capture_manifest_path=capture_manifest_path,
        strict_numeric=strict_numeric,
        overrides=overrides,
    )

    # Always emit the validation report for auditing.
    report_path = out_dir / "analysis_validation_report.json"
    report_path.write_text(
        validation_report.model_dump_json(indent=2, by_alias=True),
        encoding="utf-8",
    )

    if validation_report.blocked:
        # Production gate: do NOT emit analysis.json. Caller decides exit code.
        log.warning(
            "analysis BLOCKED — reasons: %s. Wrote %s + %s but NOT analysis.json.",
            ", ".join(validation_report.blocking_reasons),
            unvalidated_path.name, report_path.name,
        )
        _emitter.emit_run_done(
            ok=False,
            summary={
                "blocked": True,
                "blocking_reasons": validation_report.blocking_reasons,
                "numeric_conflicts": len(validation_report.numeric_conflicts),
                "invalid_source_refs": len(validation_report.invalid_source_refs),
                "flagged_beats": len(validation_report.flagged_beats),
            },
        )
        # Raise so the CLI can map to exit code 2.
        raise BlockingValidationError(
            blocking_reasons=validation_report.blocking_reasons,
            report_path=report_path,
            unvalidated_path=unvalidated_path,
        )

    analysis_path = out_dir / "analysis.json"
    analysis_path.write_text(
        result.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )
    log.info(
        "wrote %s  (arc_acts=%d, beats=%d, topics=%d, entities=%d, "
        "asr_flagged=%d, entity_patches=%d, source_refs_nullified=%d, id_remaps=%d)",
        analysis_path, len(narrative.arc_acts), len(beats),
        len(narrative.topics), len(narrative.entities),
        len(validation_report.flagged_beats),
        len(validation_report.entity_patches),
        len(validation_report.invalid_source_refs),
        len(validation_report.id_remaps),
    )

    _emitter.emit_run_done(
        ok=True,
        summary={
            "arc_acts": len(narrative.arc_acts),
            "beats": len(beats),
            "topics_main": sum(1 for t in narrative.topics if t.role == "main"),
            "topics_supporting": sum(1 for t in narrative.topics if t.role == "supporting"),
            "entities": len(narrative.entities),
            "asr_flagged": len(validation_report.flagged_beats),
            "entity_patches": len(validation_report.entity_patches),
            "source_refs_nullified": len(validation_report.invalid_source_refs),
            "id_remaps": len(validation_report.id_remaps),
        },
    )

    return result


class BlockingValidationError(RuntimeError):
    """Raised when run_all_validators finds blocking issues (e.g. numeric_conflict)."""

    def __init__(self, *, blocking_reasons: list[str],
                 report_path: Path, unvalidated_path: Path) -> None:
        self.blocking_reasons = blocking_reasons
        self.report_path = report_path
        self.unvalidated_path = unvalidated_path
        super().__init__(
            "analysis blocked: " + "; ".join(blocking_reasons)
            + f" (see {report_path.name} and {unvalidated_path.name})"
        )
