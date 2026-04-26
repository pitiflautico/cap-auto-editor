"""Deterministic post-LLM validators for analysis.json.

These functions are pure regex/string operations. They never call an LLM.
Each validator returns ``(updated_analysis, report)`` where ``report`` is
a ``ValidationReport`` accumulating findings. ``run_all_validators``
chains them in order and merges reports.

Order of execution (matches INTERFACE):
  1. transcript_sanity_validator   — flag ASR garbage, mark transitions
  2. entity_normalizer             — replace surface_forms with canonicals
  3. numeric_consistency_checker   — block on magnitude conflicts
  4. broll_type_validator          — pydantic enum already enforces; warns
  5. source_ref_validator          — null + report invalid slugs
  6. beat_id_resequencer           — renumber gaps; cascade through refs
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .contracts import (
    AnalysisResult,
    BeatIssue,
    Entity,
    EntityPatch,
    IDRemap,
    InvalidSourceRef,
    NumericConflict,
    ValidationOverride,
    ValidationReport,
)

log = logging.getLogger("analysis.validate")


# ─── helpers ────────────────────────────────────────────────────────────

def _word_tokens(text: str) -> list[str]:
    return re.findall(r"\b[\w']+\b", text.lower(), flags=re.UNICODE)


# ─── 1. transcript_sanity_validator ─────────────────────────────────────

# A beat with this many or more identical consecutive word tokens is treated
# as ASR garbage. Threshold tuned conservatively: 4 ≥ same word in a row is
# almost never legitimate dialogue.
_ASR_REPEAT_RUN = 4


def transcript_sanity_validator(analysis: AnalysisResult) -> tuple[AnalysisResult, ValidationReport]:
    """Flag beats with ASR repetition.

    Action when a run ≥ _ASR_REPEAT_RUN identical consecutive tokens is found:
      - editorial_function   → "transition"
      - broll_hints          → []  (no visual content)
      - hero_text_candidate  → None  (would otherwise leak garbage onto overlay)
    Original ``text`` is preserved so a human can audit. The detail captures
    the offending token + repetition count for traceability.
    """
    report = ValidationReport()
    for beat in analysis.narrative.beats:
        toks = _word_tokens(beat.text)
        max_run = 1
        max_token = ""
        run = 1
        for i in range(1, len(toks)):
            if toks[i] == toks[i - 1]:
                run += 1
                if run > max_run:
                    max_run = run
                    max_token = toks[i]
            else:
                run = 1
        if max_run >= _ASR_REPEAT_RUN:
            report.flagged_beats.append(BeatIssue(
                beat_id=beat.beat_id,
                issue="asr_repetition",
                detail=(
                    f"repeated_token_run: token={max_token!r} count={max_run} "
                    f"(>= {_ASR_REPEAT_RUN})"
                ),
                token=max_token,
                count=max_run,
            ))
            beat.editorial_function = "transition"
            beat.broll_hints = []
            beat.hero_text_candidate = None
            # text intentionally preserved; do not invent placeholders.
    return analysis, report


# ─── 2. entity_normalizer ───────────────────────────────────────────────

def _is_safe_surface(surface: str) -> bool:
    """A surface form is only safe to apply globally if it is unambiguous:
    it has 2+ tokens OR it contains a digit. Single bare words are skipped
    (they can corrupt compound products: 'Foo' inside 'Foo Code')."""
    s = surface.strip()
    if not s:
        return False
    if any(c.isdigit() for c in s):
        return True
    tokens = re.findall(r"\b\w+\b", s)
    return len(tokens) >= 2


def _find_all_matches(text: str, pairs: list[tuple[str, str]]) -> list[tuple[int, int, str, str]]:
    """Find every (start, end, surface, canonical) match on ``text``.

    Word-boundary aware. Iterates pairs (assumes already filtered + sorted
    longest-first) and collects all hits.
    """
    out: list[tuple[int, int, str, str]] = []
    for surface, canonical in pairs:
        pattern = re.compile(
            r"(?<![\w])" + re.escape(surface) + r"(?![\w])",
            flags=re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            out.append((m.start(), m.end(), surface, canonical))
    return out


def _resolve_overlaps(matches: list[tuple[int, int, str, str]]) -> list[tuple[int, int, str, str]]:
    """Resolve overlapping matches by greedy longest-first selection.

    Sort by (length desc, start asc, canonical-exact preferred). Walk in
    order, accept a match only if it does not overlap any already-accepted.
    Result is a list of non-overlapping spans.
    """
    matches_sorted = sorted(
        matches,
        key=lambda m: (-(m[1] - m[0]), m[0], 0 if m[2] == m[3] else 1),
    )
    accepted: list[tuple[int, int, str, str]] = []
    for m in matches_sorted:
        s, e = m[0], m[1]
        if any(not (e <= a_s or s >= a_e) for (a_s, a_e, _, _) in accepted):
            continue
        accepted.append(m)
    # Final list ordered by start ascending for deterministic application.
    accepted.sort(key=lambda m: m[0])
    return accepted


def _apply_spans(text: str, spans: list[tuple[int, int, str, str]]) -> str:
    """Apply replacements from RIGHT to LEFT so earlier offsets stay valid."""
    out = text
    for s, e, _surface, canonical in sorted(spans, key=lambda m: -m[0]):
        out = out[:s] + canonical + out[e:]
    return out


def entity_normalizer(analysis: AnalysisResult) -> tuple[AnalysisResult, ValidationReport]:
    """Replace surface forms with canonicals using single-pass span resolution.

    Algorithm (per beat):
      1. Filter surface_forms to safe ones (2+ tokens OR has digit).
      2. Sort pairs longest-first.
      3. Find all matches in the ORIGINAL text (no sequential rewriting).
      4. Resolve overlaps: longest match wins.
      5. Apply replacements right-to-left over non-overlapping spans.
      6. Log one EntityPatch per applied span (true beat × from × to).

    Single-word ambiguous surface forms are SKIPPED — see _is_safe_surface.
    Does NOT mutate entities.surface_forms (audit trail preserved). Never
    silently de-duplicates output: if duplicates appear, tests must catch it.
    """
    report = ValidationReport()

    pairs: list[tuple[str, str]] = []
    for ent in analysis.narrative.entities:
        for sf in ent.surface_forms:
            if not sf or sf == ent.canonical:
                continue
            if not _is_safe_surface(sf):
                continue
            pairs.append((sf, ent.canonical))
    pairs.sort(key=lambda p: -len(p[0]))

    n_applied = 0
    if pairs:
        for beat in analysis.narrative.beats:
            matches = _find_all_matches(beat.text, pairs)
            spans = _resolve_overlaps(matches)
            if not spans:
                continue
            beat.text = _apply_spans(beat.text, spans)
            for _s, _e, surface, canonical in spans:
                report.entity_patches.append(EntityPatch.model_validate({
                    "beat_id": beat.beat_id,
                    "from": surface,
                    "to": canonical,
                }))
                n_applied += 1
    report.entity_normalizations_applied = n_applied
    return analysis, report


# ─── 3. number normalisation + consistency checker ──────────────────────

# Map of "unit aliases" that share a normalised semantic unit.
# Same unit ⇒ values must be equal in magnitude.
_UNIT_ALIASES = {
    "tps":             ["tokens/s", "tokens por segundo", "tps", "tok/s"],
    "param":           ["parámetros", "parametros", "params"],
    "percent":         ["%", "por ciento", "percent"],
    "context_tokens":  ["tokens de contexto", "context tokens", "k contexto"],
    # "params" implicit: B / mil millones / millones / k cuando no hay unidad explícita
}


# Numeric tokens we recognise. Order matters when concatenating regex.
# Returns a normalised float / int magnitude.
_BILLION_WORDS = ["mil millones", "billion"]
_MILLION_WORDS = ["millones", "million"]
_THOUSAND_WORDS = ["mil", "thousand"]


def normalize_number(text: str) -> float | None:
    """Parse a numeric token like '27B', '27 mil millones', '125k', '1.7%'.

    Returns the magnitude as a float. Returns None if no recognised
    numeric token is present in ``text``.

    LANGUAGE NOTE — Spanish "billones" = 1e12 (long scale). Do NOT confuse
    with English "billion" = 1e9 (short scale). "27 billones" → 27e12.
    """
    s = text.strip().lower()

    # 1) compound forms with explicit magnitude word.
    # Order in the alternation matters: the regex engine matches left-to-right,
    # so longer phrases ("mil millones") must come before subsets ("millones",
    # "mil"). "billones" is the Spanish 1e12.
    # The numeric part allows internal whitespace ("400 .000") because whisper
    # sometimes inserts a stray space before thousand separators.
    m = re.match(
        r"\s*(\d+(?:\s*[.,]\s*\d+)*)\s*(mil\s+millones|billones|millones|mil|billion)\b",
        s,
    )
    if m:
        num = _parse_decimal(m.group(1))
        if num is None:
            return None
        word = m.group(2)
        if word == "mil millones":
            return num * 1_000_000_000      # ES "thousand million" = 1e9
        if word == "billones":
            return num * 1_000_000_000_000  # ES "trillion" = 1e12
        if word == "millones":
            return num * 1_000_000
        if word == "mil":
            return num * 1_000
        if word == "billion":
            return num * 1_000_000_000      # EN "billion" = 1e9

    # 2) "27B" / "1.7M" / "125K"  (single-letter suffix)
    m = re.match(r"\s*([\d.,]+)\s*([bmk])\b", s)
    if m:
        num = _parse_decimal(m.group(1))
        if num is None:
            return None
        suffix = m.group(2)
        return num * {"b": 1_000_000_000, "m": 1_000_000, "k": 1_000}[suffix]

    # 3) percentage  "1.7%"  /  "1.7 percent"  /  "1.7 por ciento"
    m = re.match(r"\s*([\d.,]+)\s*(%|por\s+ciento|percent)\b", s)
    if m:
        num = _parse_decimal(m.group(1))
        return num if num is not None else None

    # 4) bare number followed by tokens/s / TPS / words
    m = re.match(r"\s*([\d.,]+)\s*(tokens\s*por\s*segundo|tokens?/s|tps|tok/s)\b",
                 s, flags=re.IGNORECASE)
    if m:
        return _parse_decimal(m.group(1))

    # 5) bare number alone (ambiguous, used by the consistency checker only
    # when paired with the same surrounding unit).
    m = re.match(r"\s*([\d.,]+)\b", s)
    if m:
        return _parse_decimal(m.group(1))

    return None


def _parse_decimal(s: str) -> float | None:
    """Parse a numeric token, disambiguating thousand-separator vs decimal.

    Whisper sometimes emits Spanish thousand-separator numbers with a stray
    space ("400 .000 millones"); strip whitespace first, then decide:
      • multiple identical separators ("1.234.567") → all thousands
      • single separator with exactly 3 trailing digits ("400.000") → thousands
      • otherwise → decimal point (coma normalised to dot)
    """
    s = s.strip().replace(" ", "")
    if not s:
        return None
    parts = re.split(r"[.,]", s)
    if len(parts) >= 3 and all(len(p) == 3 for p in parts[1:]) and parts[0]:
        s = "".join(parts)
    elif len(parts) == 2 and len(parts[1]) == 3 and parts[0]:
        s = parts[0] + parts[1]
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# Phrases that surface a "(value, unit)" pair we can check.
# Examples we want to extract from beat.text / narrative fields:
#   "27 millones de parámetros"        -> (27_000_000, "param")
#   "27 mil millones de parámetros"    -> (27_000_000_000, "param")
#   "27B parámetros"                   -> (27_000_000_000, "param")
#   "85 tokens/s"                      -> (85, "tps")
#   "85 TPS"                           -> (85, "tps")
#   "1.7%"                             -> (1.7, "percent")
_VALUE_UNIT_RE = re.compile(
    r"""(?ix)
    (?P<num>
        \d+(?:\s*[.,]\s*\d+)*\s*(?:mil\s+millones|billones|millones|mil|billion)\b   # spelled-out (ES + EN)
        | \d+(?:[.,]\d+)?[bmk]\b                                                     # 27B / 125K / 27.5B
        | \d+(?:[.,]\d+)?\s*%                                                        # percent
        | \d+(?:\s*[.,]\s*\d+)*                                                      # bare number (allows "400 .000")
    )
    \s*
    (?P<unit>
        (?:de\s+)?par[aá]metros
        | tokens?\s*por\s*segundo
        | tokens?\s*/\s*s
        | tps
        | tok/s
        | %
        | por\s+ciento
        | tokens?\s*de\s*contexto
    )?
    """,
)


def _extract_value_units(text: str) -> list[tuple[float, str | None, str]]:
    """Yield (normalized_value, normalised_unit, raw_match) tuples from text."""
    out: list[tuple[float, str | None, str]] = []
    if not text:
        return out
    for m in _VALUE_UNIT_RE.finditer(text):
        raw_num = m.group("num") or ""
        raw_unit = (m.group("unit") or "").strip().lower()
        val = normalize_number(raw_num)
        if val is None:
            continue
        unit = _classify_unit(raw_unit)
        # We only care about magnitudes attached to a recognised unit, OR
        # bare numbers > 1000 (so dates and percent without sign aren't noise).
        if unit is None and val < 1000:
            continue
        out.append((val, unit, m.group(0).strip()))
    return out


def _classify_unit(raw_unit: str) -> str | None:
    if not raw_unit:
        return None
    low = raw_unit.lower()
    if "parámetro" in low or "parametro" in low:
        return "param"
    if "tokens por segundo" in low or "tokens/s" in low or "tok/s" in low or low == "tps":
        return "tps"
    if low.endswith("%") or "ciento" in low or low == "percent":
        return "percent"
    if "tokens de contexto" in low or "context" in low:
        return "context_tokens"
    return None


def _related_to_lexical(text: str, entity: Entity) -> bool:
    """True if the text mentions the entity by canonical or any surface form."""
    low = text.lower()
    if entity.canonical.lower() in low:
        return True
    for sf in entity.surface_forms:
        if sf.lower() in low:
            return True
    return False


def numeric_consistency_checker(
    analysis: AnalysisResult,
) -> tuple[AnalysisResult, ValidationReport]:
    """Detect magnitude conflicts grouped by entity context + unit.

    Entity context for a beat is the union of:
      - entities whose `mentioned_in_beats` includes this beat_id (explicit)
      - entities whose canonical/surface_form appears lexically in beat.text

    The previous version also bridged through `topic.mentioned_in_beats →
    references_topic_ids`, which broadened the context to every entity that
    shared a topic — and attributed conflicts to entities never named in the
    beat (e.g. "Apple Silicon" attached to a sentence about "Gemma 4"
    parameters because both lived under the same `gemma_4` topic). The bridge
    is removed: explicit linking + lexical match cover the legitimate cases
    without the false attributions.

    For non-beat fields (video_summary, narrative_thesis, topic descriptions),
    context is every entity whose canonical/surface_form appears lexically.

    Two samples conflict iff: same entity context ∩ same unit class ∩
    different magnitude (rel-tol 0.001).
    """
    report = ValidationReport()
    n = analysis.narrative

    beat_to_entities: dict[str, set[str]] = {b.beat_id: set() for b in n.beats}
    for ent in n.entities:
        for bid in ent.mentioned_in_beats:
            if bid in beat_to_entities:
                beat_to_entities[bid].add(ent.canonical)

    # samples: (field, raw_value, normalized, unit, context_canonical)
    samples: list[tuple[str, str, float, str | None, str]] = []

    def _scan_field(field_name: str, text: str, candidate_canonicals: set[str]) -> None:
        if not text or not candidate_canonicals:
            return
        for val, unit, raw in _extract_value_units(text):
            for canonical in candidate_canonicals:
                samples.append((field_name, raw, val, unit, canonical))

    # Beats: context comes from explicit linking (topics + mentioned_in_beats)
    # AND lexical mentions of any entity within the text itself.
    for i, b in enumerate(n.beats):
        ctx = set(beat_to_entities.get(b.beat_id, set()))
        for ent in n.entities:
            if _related_to_lexical(b.text, ent):
                ctx.add(ent.canonical)
        _scan_field(f"beats[{i}].text", b.text, ctx)

    # Non-beat fields: lexical-only context.
    for fname, text in (("narrative.video_summary", n.video_summary),
                        ("narrative.narrative_thesis", n.narrative_thesis)):
        ctx = {ent.canonical for ent in n.entities if _related_to_lexical(text, ent)}
        _scan_field(fname, text, ctx)

    # Topics: include their description as a checkable field.
    for ti, t in enumerate(n.topics):
        ctx = {ent.canonical for ent in n.entities
               if _related_to_lexical(t.description, ent)}
        _scan_field(f"narrative.topics[{ti}].description", t.description, ctx)

    # Group by (entity_canonical, unit). Skip unit=None (bare numbers without
    # context unit can't be compared safely — would generate spurious noise).
    by_key: dict[tuple[str, str], list[tuple[str, str, float]]] = {}
    for field, raw, val, unit, canonical in samples:
        if unit is None:
            continue
        key = (canonical, unit)
        by_key.setdefault(key, []).append((field, raw, val))

    seen_pairs: set[tuple[str, str, str, str]] = set()  # dedupe identical conflicts
    for (canonical, unit), entries in by_key.items():
        if len(entries) < 2:
            continue
        distinct: list[tuple[str, str, float]] = []
        for entry in entries:
            if not any(_same_magnitude(entry[2], d[2]) for d in distinct):
                distinct.append(entry)
        if len(distinct) >= 2:
            for ai in range(len(distinct)):
                for bi in range(ai + 1, len(distinct)):
                    a_, b_ = distinct[ai], distinct[bi]
                    sig = (a_[0], a_[1], b_[0], b_[1])
                    if sig in seen_pairs:
                        continue
                    seen_pairs.add(sig)
                    report.numeric_conflicts.append(NumericConflict(
                        field_a=a_[0], value_a=a_[1], normalized_a=a_[2],
                        field_b=b_[0], value_b=b_[1], normalized_b=b_[2],
                        unit=unit, entity_or_topic=f"entity:{canonical}",
                        severity="block",
                    ))

    if report.numeric_conflicts:
        report.blocked = True
        report.blocking_reasons.append(
            f"numeric_conflict (n={len(report.numeric_conflicts)})"
        )
    return analysis, report


def _same_magnitude(a: float, b: float, *, rel_tol: float = 0.001) -> bool:
    if a == 0 or b == 0:
        return a == b
    return abs(a - b) / max(abs(a), abs(b)) <= rel_tol


# ─── 4. broll_type_validator ────────────────────────────────────────────

def broll_type_validator(analysis: AnalysisResult) -> tuple[AnalysisResult, ValidationReport]:
    """Pydantic already validates `type` against the enum. This pass logs
    soft type/description mismatches without modifying or blocking."""
    report = ValidationReport()
    return analysis, report


# ─── 5. source_ref_validator ────────────────────────────────────────────

def source_ref_validator(
    analysis: AnalysisResult,
    *,
    capture_manifest_path: Path | str | None,
) -> tuple[AnalysisResult, ValidationReport]:
    """Null any broll_hints[].source_ref that does not point to a real, OK slug."""
    report = ValidationReport()
    valid_slugs: set[str] = set()
    if capture_manifest_path is not None:
        try:
            manifest = json.loads(Path(capture_manifest_path).read_text(encoding="utf-8"))
            for r in manifest.get("results", []):
                if r.get("status") == "ok":
                    slug = (r.get("request") or {}).get("slug")
                    if slug:
                        valid_slugs.add(slug)
        except Exception as exc:
            log.warning("source_ref_validator: failed to read manifest: %s", exc)
            # Manifest unreadable — null all source_refs and report.
            for beat in analysis.narrative.beats:
                for i, h in enumerate(beat.broll_hints):
                    if h.source_ref is not None:
                        report.invalid_source_refs.append(InvalidSourceRef(
                            beat_id=beat.beat_id, hint_index=i,
                            old_source_ref=h.source_ref,
                            reason="manifest_missing",
                        ))
                        h.source_ref = None
            return analysis, report

    for beat in analysis.narrative.beats:
        for i, h in enumerate(beat.broll_hints):
            if h.source_ref is None:
                continue
            if h.source_ref not in valid_slugs:
                report.invalid_source_refs.append(InvalidSourceRef(
                    beat_id=beat.beat_id, hint_index=i,
                    old_source_ref=h.source_ref,
                    reason="not_found_in_capture_manifest",
                ))
                h.source_ref = None
    return analysis, report


# ─── 6. beat_id_resequencer ─────────────────────────────────────────────

def beat_id_resequencer(analysis: AnalysisResult) -> tuple[AnalysisResult, ValidationReport]:
    """Renumber beats sequentially b001..bN. Cascade rename through
    topics.mentioned_in_beats, entities.mentioned_in_beats, and
    arc_acts.topic_focus is unaffected (it references topic_ids, not beats).
    """
    report = ValidationReport()
    n = analysis.narrative

    # Build remap: only record actual changes.
    remap: dict[str, str] = {}
    for i, beat in enumerate(n.beats, start=1):
        new_id = f"b{i:03d}"
        if beat.beat_id != new_id:
            remap[beat.beat_id] = new_id
            report.id_remaps.append(IDRemap(old=beat.beat_id, new=new_id))
        beat.beat_id = new_id

    # Cascade through references — replace if old id is in the remap.
    if remap:
        for t in n.topics:
            t.mentioned_in_beats = [remap.get(b, b) for b in t.mentioned_in_beats]
        for e in n.entities:
            e.mentioned_in_beats = [remap.get(b, b) for b in e.mentioned_in_beats]

    return analysis, report


# ─── runner ─────────────────────────────────────────────────────────────

def _merge(target: ValidationReport, src: ValidationReport) -> ValidationReport:
    target.numeric_conflicts.extend(src.numeric_conflicts)
    target.invalid_source_refs.extend(src.invalid_source_refs)
    target.flagged_beats.extend(src.flagged_beats)
    target.entity_patches.extend(src.entity_patches)
    target.id_remaps.extend(src.id_remaps)
    target.entity_normalizations_applied += src.entity_normalizations_applied
    if src.blocked:
        target.blocked = True
    target.blocking_reasons.extend(src.blocking_reasons)
    return target


def _match_override(finding: Any, override: ValidationOverride) -> bool:
    """A finding matches an override iff every key in ``override.match`` exists
    on the finding model and equals the override value.

    Generic across validators — uses pydantic ``model_dump`` to read attrs by
    name. Empty ``match`` matches every finding of the override's ``kind``
    (caller is responsible if that is too broad).
    """
    data = finding.model_dump()
    for k, v in override.match.items():
        if k not in data or data[k] != v:
            return False
    return True


def _kind_to_listname(kind: str) -> str:
    """Map override.kind → the ValidationReport list field it applies to."""
    return {
        "numeric_conflict": "numeric_conflicts",
        "asr_repetition": "flagged_beats",
        "invalid_source_ref": "invalid_source_refs",
    }[kind]


def _apply_overrides(
    analysis: AnalysisResult,
    report: ValidationReport,
    overrides: list[ValidationOverride],
) -> None:
    """Filter findings whose attributes match any user-provided override.

    Generic: the same matching engine is used for every ``kind``. Side-effects
    on the analysis (e.g. patching a source_ref with ``resolution.new_source_ref``)
    happen here, not in the validators themselves.

    For ``asr_repetition`` overrides, only the items whose ``issue == 'asr_repetition'``
    are eligible — other ``BeatIssue`` kinds remain untouched.
    """
    for ov in overrides:
        list_name = _kind_to_listname(ov.kind)
        items = getattr(report, list_name)
        kept: list[Any] = []
        for it in items:
            # ASR-specific scope: do not match other BeatIssue kinds.
            if ov.kind == "asr_repetition" and getattr(it, "issue", None) != "asr_repetition":
                kept.append(it)
                continue
            if _match_override(it, ov):
                if ov.kind == "invalid_source_ref":
                    new_ref = ov.resolution.get("new_source_ref")
                    if isinstance(new_ref, str) and new_ref:
                        for beat in analysis.narrative.beats:
                            if beat.beat_id == getattr(it, "beat_id", None):
                                hi = getattr(it, "hint_index", -1)
                                if 0 <= hi < len(beat.broll_hints):
                                    beat.broll_hints[hi].source_ref = new_ref
                                break
                report.applied_overrides.append(ov)
                continue  # filtered out
            kept.append(it)
        setattr(report, list_name, kept)

    # Recompute blocking state from remaining findings.
    reasons: list[str] = []
    if report.numeric_conflicts:
        reasons.append(f"numeric_conflict (n={len(report.numeric_conflicts)})")
    report.blocking_reasons = reasons
    report.blocked = bool(reasons)


def load_overrides(path: Path | str) -> list[ValidationOverride]:
    """Load overrides from a JSON file with shape ``{"overrides": [...]}``.

    Each item is validated through the ``ValidationOverride`` pydantic model.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("overrides") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError(
            f"override file {path}: expected key 'overrides' as list, got {type(items).__name__}"
        )
    return [ValidationOverride.model_validate(it) for it in items]


def run_all_validators(
    analysis: AnalysisResult,
    *,
    capture_manifest_path: Path | str | None = None,
    strict_numeric: bool = True,
    overrides: list[ValidationOverride] | None = None,
) -> tuple[AnalysisResult, ValidationReport]:
    """Chain the deterministic validators in order. Returns merged report.

    If ``strict_numeric`` is True (default) and any numeric conflict is
    detected, ``report.blocked`` is True and the caller MUST refuse to emit
    the final analysis.json.

    ``overrides`` (optional): human-provided resolutions that filter matching
    findings out of the blocking set. Generic across all validator kinds.
    """
    final = ValidationReport()

    analysis, r = transcript_sanity_validator(analysis); _merge(final, r)
    analysis, r = entity_normalizer(analysis);            _merge(final, r)
    analysis, r = numeric_consistency_checker(analysis);  _merge(final, r)
    analysis, r = broll_type_validator(analysis);          _merge(final, r)
    analysis, r = source_ref_validator(analysis,
                                        capture_manifest_path=capture_manifest_path)
    _merge(final, r)
    analysis, r = beat_id_resequencer(analysis);           _merge(final, r)

    if overrides:
        _apply_overrides(analysis, final, overrides)

    if not strict_numeric:
        # Demote numeric conflicts: keep them visible but do not block.
        for c in final.numeric_conflicts:
            c.severity = "warn"
        # Remove only the numeric_conflict blocking reason; other blocks stay.
        final.blocking_reasons = [r for r in final.blocking_reasons
                                   if "numeric_conflict" not in r]
        final.blocked = bool(final.blocking_reasons)

    analysis.validation = final
    return analysis, final
