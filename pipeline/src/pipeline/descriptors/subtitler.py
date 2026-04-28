"""subtitler phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

SUB_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "subtitler/.venv/bin/subtitler"
)


def _sub_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    return [
        "--transcript", str(ctx.run_dir / "polish" / "transcript_polished.json"),
        "--out-dir", str(phase_dir),
    ]


subtitler_descriptor = PhaseDescriptor(
    name="subtitler",
    display_name="Subtitler (word-by-word)",
    order=13,
    out_subdir="subtitler",
    cli_command=[SUB_BIN, "run"],
    cli_args=_sub_args,
    depends_on=["polish"],
    on_failure="skip",
    retry_max=0,
    timeout_s=120,
    render_artifacts=[
        RenderArtifact(
            type="key_value",
            title="Resumen subtítulos",
            path="subtitle_clips.json",
            options={
                "fields": [
                    {"key": "language", "label": "Lang"},
                    {"key": "duration_s", "label": "Duración (s)"},
                    {"key": "schema_version", "label": "Schema"},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Clips word-by-word",
            path="subtitle_clips.json",
            options={
                "root_path": "clips",
                "columns": [
                    {"field": "index", "label": "#", "mono": True},
                    {"field": "start_s", "label": "Start"},
                    {"field": "end_s", "label": "End"},
                    {"field": "text", "label": "Word", "mono": True},
                    {"field": "segment_index", "label": "Seg"},
                ],
            },
        ),
    ],
)
