"""transcript_patches.json — audit log of every spelling change.

Every normalisation or alias application goes here. Output is a
simple sidecar; downstream (analysis/) never reads it. Its purpose is
forensic: why did my transcript end up with word X? Where did it come
from?
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .text_normalizer import NormalizationPatch


class PatchRecord(BaseModel):
    """Serialisable form of NormalizationPatch."""
    layer: str
    rule_type: str
    from_: str = Field(alias="from")
    to: str
    segment_idx: int | None = None
    word_idx: int | None = None
    occurrences: int = 1

    model_config = {"populate_by_name": True}


class TranscriptPatches(BaseModel):
    schema_version: str = "1.0.0"
    patches: list[PatchRecord] = Field(default_factory=list)


def collect(patches: list[NormalizationPatch]) -> TranscriptPatches:
    """Convert internal dataclasses to the serialisable contract."""
    records = [
        PatchRecord(
            layer=p.layer,
            rule_type=p.rule_type,
            **{"from": p.from_},
            to=p.to,
            segment_idx=p.segment_idx,
            word_idx=p.word_idx,
            occurrences=p.occurrences,
        )
        for p in patches
    ]
    return TranscriptPatches(patches=records)


def summarise_by_layer(tp: TranscriptPatches) -> dict[str, int]:
    """Quick view: total occurrences applied per layer."""
    out: dict[str, int] = {}
    for p in tp.patches:
        out[p.layer] = out.get(p.layer, 0) + p.occurrences
    return out
