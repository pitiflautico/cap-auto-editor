"""Analysis phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

ANALYSIS_BIN = "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/analysis/.venv/bin/analysis"


def _analysis_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    transcript = ctx.run_dir / "polish" / "transcript_polished.json"
    capture_manifest = ctx.run_dir / "capture" / "capture_manifest.json"
    return [
        "--transcript", str(transcript),
        "--capture-manifest", str(capture_manifest),
        "--out-dir", str(phase_dir),
    ]


analysis_descriptor = PhaseDescriptor(
    name="analysis",
    display_name="Analysis",
    order=3,
    out_subdir="analysis",
    cli_command=[ANALYSIS_BIN, "run"],
    cli_args=_analysis_args,
    depends_on=["polish"],
    on_failure="abort",
    retry_max=0,
    timeout_s=600,
    render_artifacts=[
        RenderArtifact(
            type="key_value",
            title="Narrativa",
            path="analysis.json",
            options={
                "fields": [
                    {"key": "narrative.video_summary", "label": "Resumen"},
                    {"key": "narrative.narrative_thesis", "label": "Tesis"},
                    {"key": "narrative.audience", "label": "Audiencia"},
                    {"key": "narrative.tone", "label": "Tono"},
                ]
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Arc (actos)",
            path="analysis.json",
            options={
                "root_path": "narrative.arc_acts",
                "columns": [
                    {"field": "name", "label": "Acto", "badge": True},
                    {"field": "start_s", "label": "Start", "format": "seconds"},
                    {"field": "end_s", "label": "End", "format": "seconds"},
                    {"field": "purpose", "label": "Propósito", "truncate": 100},
                    {"field": "topic_focus", "label": "Topic focus", "format": "join_csv"},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Beats",
            path="analysis.json",
            options={
                "root_path": "narrative.beats",
                "columns": [
                    {"field": "beat_id", "label": "ID", "mono": True},
                    {"field": "start_s", "label": "Start", "format": "seconds"},
                    {"field": "end_s", "label": "End", "format": "seconds"},
                    {"field": "editorial_function", "label": "Función", "badge": True},
                    {"field": "energy", "label": "Energía", "badge": True},
                    {"field": "hero_text_candidate", "label": "Hero text"},
                    {"field": "broll_hints", "label": "B-roll #", "format": "list_length"},
                    {"field": "text", "label": "Texto", "truncate": 80},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Topics",
            path="analysis.json",
            options={
                "root_path": "narrative.topics",
                "columns": [
                    {"field": "label", "label": "Topic"},
                    {"field": "role", "label": "Rol", "badge": True},
                    {"field": "kind", "label": "Kind", "badge": True},
                    {"field": "description", "label": "Descripción", "truncate": 120},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Entities",
            path="analysis.json",
            options={
                "root_path": "narrative.entities",
                "columns": [
                    {"field": "canonical", "label": "Canonical", "mono": True},
                    {"field": "kind", "label": "Kind", "badge": True},
                    {"field": "surface_forms", "label": "As heard"},
                    {"field": "official_urls", "label": "URLs"},
                ],
            },
        ),
    ],
)
