"""Phase registry — the single place to add a new phase."""
from __future__ import annotations

from pipeline.contracts import PhaseDescriptor
from pipeline.descriptors import capture_descriptor, polish_descriptor, analysis_descriptor

PIPELINE_PHASES: list[PhaseDescriptor] = [
    capture_descriptor,
    polish_descriptor,
    analysis_descriptor,
    # broll_plan_descriptor,   # future
    # builder_descriptor,      # future
]
