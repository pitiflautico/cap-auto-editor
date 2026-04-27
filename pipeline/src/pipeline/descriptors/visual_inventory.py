"""visual_inventory phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

VI_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "visual_inventory/.venv/bin/visual-inventory"
)


def _vi_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    # Prefer the enriched manifest from auto_source if present.
    enriched = ctx.run_dir / "auto_source" / "capture_manifest_enriched.json"
    if enriched.exists():
        manifest = enriched
    else:
        manifest = ctx.run_dir / "capture" / "capture_manifest.json"
    return [
        "--capture-manifest", str(manifest),
        "--out-dir",          str(phase_dir),
    ]


visual_inventory_descriptor = PhaseDescriptor(
    name="visual_inventory",
    display_name="Visual Inventory",
    order=6,
    out_subdir="visual_inventory",
    cli_command=[VI_BIN, "run"],
    cli_args=_vi_args,
    depends_on=["auto_source"],
    on_failure="skip",
    retry_max=0,
    timeout_s=1800,    # 30 min: vision LLM × N keyframes × M videos
    render_artifacts=[
        RenderArtifact(
            type="json_table",
            title="Inventario visual (por asset)",
            path="visual_inventory.json",
            options={
                "root_path": "assets",
                "columns": [
                    {"field": "slug", "label": "Slug", "mono": True},
                    {"field": "asset_path", "label": "Asset", "mono": True, "truncate": 40},
                    {"field": "duration_s", "label": "Dur (s)"},
                    {"field": "shot_types_seen", "label": "Shots"},
                    {"field": "overall_quality", "label": "Q"},
                    {"field": "has_any_baked_text", "label": "Baked text"},
                    {"field": "summary", "label": "Resumen", "truncate": 80},
                    {"field": "best_segments", "label": "Segmentos", "format": "list_length"},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Best segments (anclas para broll planner)",
            path="visual_inventory.json",
            options={
                "root_path": "assets",
                "flatten_field": "best_segments",
                "inherit_fields": ["slug", "asset_path"],
                "columns": [
                    {"field": "slug", "label": "Slug", "mono": True},
                    {"field": "asset_path", "label": "Asset", "mono": True, "truncate": 30},
                    {"field": "t_start_s", "label": "Start", "format": "seconds"},
                    {"field": "t_end_s", "label": "End", "format": "seconds"},
                    {"field": "shot_type", "label": "Shot", "badge": True},
                    {"field": "quality", "label": "Q"},
                    {"field": "score", "label": "Score"},
                    {"field": "description", "label": "Descripción", "truncate": 80},
                ],
            },
        ),
    ],
)
