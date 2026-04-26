"""Universal text normalisation.

Applies language-level rules (punctuation, whitespace, dashes, quotes)
that are "objectively the same text, just better formatted". NEVER
entity-aware. If a rule depends on knowing a brand or product, it does
not belong here — it belongs in project_aliases.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from .contracts import Segment, Transcript, Word

RuleType = Literal["whitespace", "punctuation", "quotes", "dash", "typo"]
RuleScope = Literal["segment_text", "word_text", "both"]


@dataclass(frozen=True)
class NormalizationRule:
    from_: str
    to: str
    type: RuleType
    scope: RuleScope = "segment_text"
    auto_apply: bool = True
    is_regex: bool = False
    notes: str | None = None


@dataclass
class NormalizationPatch:
    """One applied rule occurrence. Goes into transcript_patches.json."""
    layer: str           # "text_normalizer"
    rule_type: RuleType
    from_: str
    to: str
    segment_idx: int | None = None
    word_idx: int | None = None
    occurrences: int = 1


# ── Loader ─────────────────────────────────────────────────────────

def load_rules(path: Path | str) -> list[NormalizationRule]:
    """Read rules from a YAML file and return only auto_apply=true ones."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rules: list[NormalizationRule] = []
    for r in data.get("rules", []):
        if not r.get("auto_apply", True):
            continue
        rules.append(
            NormalizationRule(
                from_=r["from"],
                to=r["to"],
                type=r["type"],
                scope=r.get("scope", "segment_text"),
                auto_apply=True,
                is_regex=r.get("is_regex", False),
                notes=r.get("notes"),
            )
        )
    return rules


# ── Core apply ─────────────────────────────────────────────────────

def _apply_once(
    text: str,
    rule: NormalizationRule,
) -> tuple[str, int]:
    """Return (new_text, num_replacements). Non-regex literal replace."""
    if rule.is_regex:
        import re
        new_text, n = re.subn(rule.from_, rule.to, text)
        return new_text, n
    # Literal substring replace, iterated to convergence
    count = 0
    cur = text
    while True:
        nxt = cur.replace(rule.from_, rule.to)
        if nxt == cur:
            break
        # Count replacements in this pass
        count += (len(cur) - len(nxt)) // max(1, (len(rule.from_) - len(rule.to))) if len(rule.from_) != len(rule.to) else cur.count(rule.from_)
        cur = nxt
    return cur, count


def normalize_text(
    text: str,
    rules: list[NormalizationRule],
) -> tuple[str, list[NormalizationPatch]]:
    """Apply rules in order; return (new_text, patches)."""
    patches: list[NormalizationPatch] = []
    cur = text
    for rule in rules:
        new, n = _apply_once(cur, rule)
        if n > 0 and new != cur:
            patches.append(
                NormalizationPatch(
                    layer="text_normalizer",
                    rule_type=rule.type,
                    from_=rule.from_,
                    to=rule.to,
                    occurrences=n,
                )
            )
            cur = new
    return cur, patches


def normalize_transcript(
    transcript: Transcript,
    rules: list[NormalizationRule],
) -> tuple[Transcript, list[NormalizationPatch]]:
    """Normalise segment.text (and word.text if scope=word_text/both).

    Word timings are preserved. Only textual formatting changes.
    """
    all_patches: list[NormalizationPatch] = []
    new_segments: list[Segment] = []
    for seg_idx, seg in enumerate(transcript.segments):
        seg_rules = [r for r in rules if r.scope in ("segment_text", "both")]
        word_rules = [r for r in rules if r.scope in ("word_text", "both")]

        new_seg_text, seg_patches = normalize_text(seg.text, seg_rules)
        for p in seg_patches:
            p.segment_idx = seg_idx
        all_patches.extend(seg_patches)

        new_words: list[Word] = []
        for w_idx, w in enumerate(seg.words):
            if word_rules:
                new_w_text, w_patches = normalize_text(w.text, word_rules)
                for p in w_patches:
                    p.segment_idx = seg_idx
                    p.word_idx = w_idx
                all_patches.extend(w_patches)
                new_words.append(
                    Word(
                        text=new_w_text,
                        start_s=w.start_s,
                        end_s=w.end_s,
                        probability=w.probability,
                    )
                )
            else:
                new_words.append(w)

        new_segments.append(
            Segment(
                start_s=seg.start_s,
                end_s=seg.end_s,
                text=new_seg_text,
                words=new_words,
                no_speech_prob=seg.no_speech_prob,
            )
        )

    new_transcript = Transcript(
        schema_version=transcript.schema_version,
        language=transcript.language,
        duration_s=transcript.duration_s,
        segments=new_segments,
        model=transcript.model,
    )
    return new_transcript, all_patches
