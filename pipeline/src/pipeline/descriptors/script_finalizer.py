"""script_finalizer phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

SF_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "script_finalizer/.venv/bin/script-finalizer"
)


def _sf_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    # v2.0: read the planner-merged analysis. The fallbacks cover
    # legacy runs where broll_planner didn't run (analysis_super_enriched
    # already had broll_hints filled by the old single-pass director).
    planned = ctx.run_dir / "broll_planner" / "analysis_with_broll.json"
    super_enriched = ctx.run_dir / "auto_source" / "analysis_super_enriched.json"
    enriched = ctx.run_dir / "entity_enricher" / "analysis_enriched.json"
    if planned.exists():
        analysis_path = planned
    elif super_enriched.exists():
        analysis_path = super_enriched
    elif enriched.exists():
        analysis_path = enriched
    else:
        analysis_path = ctx.run_dir / "analysis" / "analysis.json"

    inventory = ctx.run_dir / "visual_inventory" / "visual_inventory.json"
    return [
        "--analysis", str(analysis_path),
        "--visual-inventory", str(inventory),
        "--out-dir", str(phase_dir),
    ]


script_finalizer_descriptor = PhaseDescriptor(
    name="script_finalizer",
    display_name="Script Finalizer",
    order=8,
    out_subdir="script_finalizer",
    cli_command=[SF_BIN, "run"],
    cli_args=_sf_args,
    depends_on=["broll_planner"],
    on_failure="skip",
    retry_max=0,
    timeout_s=120,
    render_artifacts=[
        RenderArtifact(
            type="key_value",
            title="Material strength + targets",
            path="finalizer_report.json",
            options={
                "fields": [
                    {"key": "material_score", "label": "material score"},
                    {"key": "material_strength", "label": "tier"},
                    {"key": "broll_target_min", "label": "broll target min"},
                    {"key": "broll_target_max", "label": "broll target max"},
                ],
            },
        ),
        RenderArtifact(
            type="key_value",
            title="Before / after",
            path="finalizer_report.json",
            options={
                "fields": [
                    {"key": "beats_before", "label": "beats before"},
                    {"key": "beats_after", "label": "beats after"},
                    {"key": "hints_before", "label": "hints before"},
                    {"key": "hints_after", "label": "hints after"},
                    {"key": "coverage_pct_before", "label": "coverage % before"},
                    {"key": "coverage_pct_after", "label": "coverage % after"},
                    {"key": "real_footage_ratio_before", "label": "real footage ratio before"},
                    {"key": "real_footage_ratio_after", "label": "real footage ratio after"},
                    {"key": "filler_ratio_before", "label": "filler ratio before"},
                    {"key": "filler_ratio_after", "label": "filler ratio after"},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Decisiones por hint",
            path="finalizer_report.json",
            options={
                "root_path": "hint_decisions",
                "columns": [
                    {"field": "beat_id", "label": "Beat", "mono": True},
                    {"field": "hint_index", "label": "#"},
                    {"field": "action", "label": "Acción", "badge": True},
                    {"field": "old_type", "label": "Old type"},
                    {"field": "new_type", "label": "New type"},
                    {"field": "chosen_slug", "label": "Anchored slug", "mono": True},
                    {"field": "chosen_t_start_s", "label": "t_start", "format": "seconds"},
                    {"field": "chosen_t_end_s", "label": "t_end", "format": "seconds"},
                    {"field": "rationale", "label": "Por qué", "truncate": 80},
                ],
            },
        ),
        RenderArtifact(
            type="timeline",
            title="Timeline (post-balancer)",
            path="analysis_balanced.json",
            options={},
        ),
    ],
)
