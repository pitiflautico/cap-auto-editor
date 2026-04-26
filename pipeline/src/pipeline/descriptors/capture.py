"""Capture phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

CAPTURE_CLI = "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/capture/.venv/bin/capture"


def _capture_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    args = ["--out", str(phase_dir)]
    if ctx.sources is not None:
        args = ["--sources", str(ctx.sources)] + args
    return args


capture_descriptor = PhaseDescriptor(
    name="capture",
    display_name="Capture",
    order=1,
    out_subdir="capture",
    cli_command=[CAPTURE_CLI, "run"],
    cli_args=_capture_args,
    depends_on=[],
    on_failure="abort",
    retry_max=0,
    timeout_s=600,
    render_artifacts=[
        RenderArtifact(
            type="json_table",
            title="URLs",
            path="capture_manifest.json",
            options={
                "root_key": "results",
                "columns": [
                    {"field": "request.slug", "label": "slug", "mono": True},
                    {"field": "request.url", "label": "url", "truncate": 60},
                    {"field": "status", "label": "status", "badge": True},
                    {"field": "backend", "label": "backend", "badge": True},
                    {"field": "duration_ms", "label": "duration", "format": "ms_to_s"},
                    {"field": "image_info.content_type", "label": "content_type"},
                ],
            },
        ),
        RenderArtifact(
            type="image_gallery",
            title="Screenshots",
            path_pattern="captures/*/screenshot.png",
        ),
        RenderArtifact(
            type="text_preview",
            title="Transcript preview",
            path_pattern="captures/*/text.txt",
            options={"max_chars": 400},
        ),
    ],
)
