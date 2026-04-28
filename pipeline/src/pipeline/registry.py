"""Phase registry — the single place to add a new phase."""
from __future__ import annotations

from pipeline.contracts import PhaseDescriptor
from pipeline.descriptors import (
    acquisition_descriptor,
    analysis_descriptor,
    auto_source_descriptor,
    broll_matcher_descriptor,
    broll_planner_descriptor,
    broll_resolver_descriptor,
    capture_descriptor,
    compositor_descriptor,
    compositor_hf_descriptor,
    entity_enricher_descriptor,
    polish_descriptor,
    script_finalizer_descriptor,
    storyboard_descriptor,
    subtitler_descriptor,
    visual_inventory_descriptor,
)

PIPELINE_PHASES: list[PhaseDescriptor] = [
    capture_descriptor,
    polish_descriptor,
    analysis_descriptor,
    entity_enricher_descriptor,
    auto_source_descriptor,
    visual_inventory_descriptor,
    broll_planner_descriptor,
    script_finalizer_descriptor,
    broll_matcher_descriptor,
    broll_resolver_descriptor,
    acquisition_descriptor,
    storyboard_descriptor,
    subtitler_descriptor,
    compositor_descriptor,
    compositor_hf_descriptor,
]
