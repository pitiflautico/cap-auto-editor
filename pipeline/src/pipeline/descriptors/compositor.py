"""compositor phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

CO_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "compositor/.venv/bin/compositor"
)


def _co_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    plan = ctx.run_dir / "acquisition" / "broll_plan_complete.json"
    subs = ctx.run_dir / "subtitler" / "subtitle_clips.json"
    # Prefer the planner-merged analysis, fall back to balanced.
    planned = ctx.run_dir / "broll_planner" / "analysis_with_broll.json"
    balanced = ctx.run_dir / "script_finalizer" / "analysis_balanced.json"
    analysis = planned if planned.exists() else balanced
    audio = ctx.run_dir / "audio.wav"
    return [
        "--broll-plan", str(plan),
        "--subtitles", str(subs),
        "--analysis", str(analysis),
        "--audio", str(audio),
        "--out-dir", str(phase_dir),
    ]


compositor_descriptor = PhaseDescriptor(
    name="compositor",
    display_name="Compositor (HyperFrames)",
    order=14,
    out_subdir="compositor",
    cli_command=[CO_BIN, "run"],
    cli_args=_co_args,
    depends_on=["acquisition", "subtitler"],
    on_failure="skip",
    retry_max=0,
    timeout_s=1800,         # 30 min — full HF render of a 50s video
    render_artifacts=[
        RenderArtifact(
            type="key_value",
            title="Resumen compositor",
            path="composition_result.json",
            options={
                "fields": [
                    {"key": "status", "label": "Status"},
                    {"key": "duration_s", "label": "Duración (s)"},
                    {"key": "out_mp4", "label": "MP4", "mono": True},
                    {"key": "sha256", "label": "SHA256"},
                    {"key": "message", "label": "Mensaje"},
                ],
            },
        ),
    ],
)
