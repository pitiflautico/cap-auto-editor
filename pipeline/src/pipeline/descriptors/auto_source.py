"""auto_source phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

AS_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "auto_source/.venv/bin/auto-source"
)


def _as_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    return [
        "--enriched-analysis", str(ctx.run_dir / "entity_enricher" / "analysis_enriched.json"),
        "--capture-manifest",  str(ctx.run_dir / "capture" / "capture_manifest.json"),
        "--out-dir",           str(phase_dir),
    ]


auto_source_descriptor = PhaseDescriptor(
    name="auto_source",
    display_name="Auto-Source",
    order=5,
    out_subdir="auto_source",
    cli_command=[AS_BIN, "run"],
    cli_args=_as_args,
    depends_on=["entity_enricher"],
    on_failure="skip",   # broll_resolver can still run with original manifest
    retry_max=0,
    timeout_s=900,
    render_artifacts=[
        RenderArtifact(
            type="json_table",
            title="Discovery report (por topic)",
            path="auto_source_report.json",
            options={
                "root_path": "discoveries",
                "columns": [
                    {"field": "topic_label", "label": "Topic"},
                    {"field": "status", "label": "Status", "badge": True},
                    {"field": "chosen_url", "label": "Official URL", "truncate": 60, "mono": True},
                    {"field": "chosen_slug", "label": "Slug", "mono": True},
                    {"field": "duration_ms", "label": "ms"},
                ],
            },
        ),
        RenderArtifact(
            type="key_value",
            title="Resumen",
            path="auto_source_report.json",
            options={
                "fields": [
                    {"key": "topics_total", "label": "Topics total"},
                    {"key": "topics_eligible", "label": "Eligible"},
                    {"key": "topics_resolved", "label": "Resolved"},
                    {"key": "new_captures", "label": "New captures"},
                ],
            },
        ),
    ],
)
