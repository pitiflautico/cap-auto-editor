"""compositor (CapCut export) phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

CO_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "compositor/.venv/bin/compositor"
)

# Default 1080×1920 black PNG that ships with v4. Used as the safe
# background when no operator value is provided.
_DEFAULT_BG = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/"
    "pipeline_v4_frozen_20260423/agent4_builder/assets/colors/black.png"
)


def _co_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    plan = ctx.run_dir / "acquisition" / "broll_plan_complete.json"
    subs = ctx.run_dir / "subtitler" / "subtitle_clips.json"
    planned = ctx.run_dir / "broll_planner" / "analysis_with_broll.json"
    balanced = ctx.run_dir / "script_finalizer" / "analysis_balanced.json"
    analysis = planned if planned.exists() else balanced
    presenter = ctx.run_dir / "video.mp4"
    if not presenter.exists():
        # Fallback to whatever video the user fed the pipeline
        # (the wrapper symlinks it as <run_dir>/video.mp4)
        presenter = ctx.run_dir / "audio.wav"      # silent placeholder
    return [
        "--analysis", str(analysis),
        "--broll-plan", str(plan),
        "--subtitles", str(subs),
        "--presenter", str(presenter),
        "--background", _DEFAULT_BG,
        "--out-dir", str(phase_dir),
    ]


compositor_descriptor = PhaseDescriptor(
    name="compositor",
    display_name="Compositor (CapCut export)",
    order=14,
    out_subdir="compositor",
    cli_command=[CO_BIN, "run"],
    cli_args=_co_args,
    depends_on=["acquisition", "subtitler"],
    on_failure="skip",
    retry_max=0,
    timeout_s=600,
    render_artifacts=[
        RenderArtifact(
            type="key_value",
            title="Resumen compositor",
            path="composition_result.json",
            options={
                "fields": [
                    {"key": "status", "label": "Status"},
                    {"key": "capcut_project_dir", "label": "CapCut project", "mono": True},
                    {"key": "draft_info_path", "label": "draft_info.json", "mono": True},
                    {"key": "duration_us", "label": "Duración (µs)"},
                    {"key": "installed_to", "label": "Instalado en"},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Warnings del builder",
            path="composition_result.json",
            options={
                "root_path": "warnings",
                "columns": [{"field": "self", "label": "Warning"}],
            },
        ),
    ],
)
