"""project_aliases — per-project substitutions (optional).

Applied AFTER the universal text_normalizer. These are specific to a
user's content (brand names, model names, recurring typos they know
Whisper makes). Loaded only when the user passes the yaml path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from .contracts import Segment, Transcript, Word
from .text_normalizer import NormalizationPatch

AliasType = Literal["entity", "typo", "formatting"]


@dataclass(frozen=True)
class ProjectAlias:
    from_: str
    to: str
    type: AliasType
    auto_apply: bool
    case_sensitive: bool = True
    notes: str | None = None


def load_project_aliases(path: Path | str | None) -> list[ProjectAlias]:
    """Return auto_apply aliases only. None/missing path returns []."""
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: list[ProjectAlias] = []
    for a in data.get("aliases", []):
        if not a.get("auto_apply", False):
            continue
        out.append(
            ProjectAlias(
                from_=a["from"],
                to=a["to"],
                type=a["type"],
                auto_apply=True,
                case_sensitive=a.get("case_sensitive", True),
                notes=a.get("notes"),
            )
        )
    return out


def _apply_alias(text: str, alias: ProjectAlias) -> tuple[str, int]:
    flags = 0 if alias.case_sensitive else re.IGNORECASE
    # Use word-boundary when both from_ and to are alphanumeric-ish.
    # Otherwise (e.g. an alias whose `from_` contains spaces or hyphens)
    # fall back to literal escape.
    pattern = re.escape(alias.from_)
    new_text, n = re.subn(pattern, alias.to, text, flags=flags)
    return new_text, n


def apply_project_aliases(
    transcript: Transcript,
    aliases: list[ProjectAlias],
) -> tuple[Transcript, list[NormalizationPatch]]:
    """Apply project aliases to segment.text (words preserved)."""
    if not aliases:
        return transcript, []

    patches: list[NormalizationPatch] = []
    new_segments: list[Segment] = []

    for seg_idx, seg in enumerate(transcript.segments):
        cur = seg.text
        for alias in aliases:
            new, n = _apply_alias(cur, alias)
            if n > 0 and new != cur:
                patches.append(
                    NormalizationPatch(
                        layer=f"project_aliases/{alias.type}",
                        rule_type="typo" if alias.type == "typo" else "punctuation",
                        from_=alias.from_,
                        to=alias.to,
                        segment_idx=seg_idx,
                        occurrences=n,
                    )
                )
                cur = new
        new_segments.append(
            Segment(
                start_s=seg.start_s,
                end_s=seg.end_s,
                text=cur,
                words=seg.words,
                no_speech_prob=seg.no_speech_prob,
            )
        )

    return (
        Transcript(
            schema_version=transcript.schema_version,
            language=transcript.language,
            duration_s=transcript.duration_s,
            segments=new_segments,
            model=transcript.model,
        ),
        patches,
    )
