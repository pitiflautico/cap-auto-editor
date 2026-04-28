"""broll_planner phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

BP_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "broll_planner/.venv/bin/broll-planner"
)


def _bp_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    # Prefer the most-enriched analysis available upstream.
    super_enriched = ctx.run_dir / "auto_source" / "analysis_super_enriched.json"
    enriched = ctx.run_dir / "entity_enricher" / "analysis_enriched.json"
    plain = ctx.run_dir / "analysis" / "analysis.json"
    analysis = next((p for p in (super_enriched, enriched, plain) if p.exists()),
                     plain)
    cap_enriched = ctx.run_dir / "auto_source" / "capture_manifest_enriched.json"
    cap = cap_enriched if cap_enriched.exists() else (
        ctx.run_dir / "capture" / "capture_manifest.json"
    )
    inv = ctx.run_dir / "visual_inventory" / "visual_inventory.json"
    args = [
        "--analysis", str(analysis),
        "--capture-manifest", str(cap),
        "--out-dir", str(phase_dir),
    ]
    if inv.exists():
        args += ["--visual-inventory", str(inv)]
    return args


broll_planner_descriptor = PhaseDescriptor(
    name="broll_planner",
    display_name="B-roll Planner (LLM)",
    order=7,
    out_subdir="broll_planner",
    cli_command=[BP_BIN, "run"],
    cli_args=_bp_args,
    depends_on=["visual_inventory"],
    on_failure="skip",
    retry_max=0,
    timeout_s=600,
    render_artifacts=[
        RenderArtifact(
            type="key_value",
            title="Resumen planner",
            path="broll_planner_report.json",
            options={
                "fields": [
                    {"key": "beats_total", "label": "Beats"},
                    {"key": "beats_required", "label": "Required"},
                    {"key": "beats_optional", "label": "Optional"},
                    {"key": "beats_planned", "label": "Planned"},
                    {"key": "hints_emitted", "label": "Hints"},
                    {"key": "source_ref_anchors", "label": "Anchored a sources"},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Plan por beat",
            path="broll_planner_report.json",
            options={
                "root_path": "plans",
                "columns": [
                    {"field": "beat_id", "label": "Beat", "mono": True},
                    {"field": "rationale", "label": "Rationale", "truncate": 80},
                ],
            },
        ),
    ],
)
