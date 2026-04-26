"""Polish phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

POLISH_PYTHON = "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/polish/.venv/bin/python"
POLISH_SCRIPT = "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/polish/scripts/phase2b_demo.py"


def _polish_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    capture_manifest = ctx.run_dir / "capture" / "capture_manifest.json"
    args = [
        "--out-dir", str(phase_dir),
        "--capture-manifest", str(capture_manifest),
    ]
    if ctx.audio_wav is not None:
        args = ["--audio", str(ctx.audio_wav)] + args
    return args


polish_descriptor = PhaseDescriptor(
    name="polish",
    display_name="Polish",
    order=2,
    out_subdir="polish",
    cli_command=[POLISH_PYTHON, POLISH_SCRIPT],
    cli_args=_polish_args,
    depends_on=["capture"],
    on_failure="abort",
    retry_max=0,
    timeout_s=900,
    render_artifacts=[
        RenderArtifact(
            type="transcript",
            title="Transcripción polished",
            path="transcript_polished.json",
        ),
        RenderArtifact(
            type="json_table",
            title="Correcciones aplicadas",
            path="transcript_patches.json",
            options={
                "root_key": "patches",
                "columns": [
                    {"field": "surface_form_to_canonical", "label": "surface_form → canonical", "mono": True, "composed": ["surface_form", "canonical"]},
                    {"field": "layer", "label": "layer", "badge": True},
                    {"field": "occurrences", "label": "occurrences"},
                    {"field": "confidence", "label": "confidence", "format": "percent"},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Resolución de entidades",
            path="entity_resolutions.json",
            options={
                "root_key": "resolutions",
                "columns": [
                    {"field": "surface_form", "label": "surface_form"},
                    {"field": "decision", "label": "decision", "badge": True, "badge_colors": {"canonical": "green", "unresolved": "grey"}},
                    {"field": "canonical", "label": "canonical"},
                    {"field": "confidence", "label": "confidence", "format": "percent"},
                    {"field": "reasoning", "label": "reasoning", "truncate": 80},
                ],
            },
        ),
        RenderArtifact(
            type="key_value",
            title="Summary",
            path="summary.json",
            options={
                "fields": [
                    {"key": "pct_saved", "label": "% saved"},
                    {"key": "edited_duration_s", "label": "edited duration (s)"},
                    {"key": "active_cuts", "label": "active cuts"},
                    {"key": "entity_candidates", "label": "entity candidates"},
                    {"key": "words_polished", "label": "words polished"},
                ],
            },
        ),
    ],
)
