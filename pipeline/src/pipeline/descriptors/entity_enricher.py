"""Entity enricher phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

ENRICHER_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "entity_enricher/.venv/bin/entity-enricher"
)


def _enricher_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    analysis_path = ctx.run_dir / "analysis" / "analysis.json"
    capture_manifest = ctx.run_dir / "capture" / "capture_manifest.json"
    return [
        "--analysis", str(analysis_path),
        "--capture-manifest", str(capture_manifest),
        "--out-dir", str(phase_dir),
    ]


entity_enricher_descriptor = PhaseDescriptor(
    name="entity_enricher",
    display_name="Entity Enricher",
    order=4,
    out_subdir="entity_enricher",
    cli_command=[ENRICHER_BIN, "run"],
    cli_args=_enricher_args,
    depends_on=["analysis"],
    on_failure="skip",   # broll_resolver can still run with empty handles
    retry_max=0,
    timeout_s=600,
    render_artifacts=[
        RenderArtifact(
            type="json_table",
            title="Entities (con handles oficiales)",
            path="analysis_enriched.json",
            options={
                "root_path": "narrative.entities",
                "columns": [
                    {"field": "canonical", "label": "Canonical", "mono": True},
                    {"field": "kind", "label": "Kind", "badge": True},
                    {"field": "official_urls", "label": "URLs"},
                    {"field": "official_handles", "label": "Handles"},
                ],
            },
        ),
        RenderArtifact(
            type="key_value",
            title="Resumen",
            path="analysis_enrichment_report.json",
            options={
                "fields": [
                    {"key": "entities_total", "label": "Entities total"},
                    {"key": "entities_enriched", "label": "Enriched"},
                    {"key": "handles_added", "label": "Handles added"},
                    {"key": "handles_from_sources", "label": "From sources"},
                    {"key": "handles_from_browser", "label": "From browser"},
                    {"key": "handles_from_cache", "label": "From cache"},
                ],
            },
        ),
    ],
)
