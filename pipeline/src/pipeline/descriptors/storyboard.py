"""storyboard phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

SB_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "storyboard/.venv/bin/storyboard"
)


def _sb_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    # Prefer post-acquisition plan; fall back to resolver-only.
    complete = ctx.run_dir / "acquisition" / "broll_plan_complete.json"
    raw = ctx.run_dir / "broll_resolver" / "broll_plan.json"
    plan_path = complete if complete.exists() else raw
    return [
        "--broll-plan", str(plan_path),
        "--analysis", str(ctx.run_dir / "script_finalizer" / "analysis_balanced.json"),
        "--out-dir", str(phase_dir),
    ]


storyboard_descriptor = PhaseDescriptor(
    name="storyboard",
    display_name="Storyboard",
    order=11,
    out_subdir="storyboard",
    cli_command=[SB_BIN, "run"],
    cli_args=_sb_args,
    depends_on=["acquisition"],
    on_failure="skip",
    retry_max=0,
    timeout_s=300,
    render_artifacts=[
        RenderArtifact(
            type="json_table",
            title="Storyboard (preview por beat)",
            path="storyboard.json",
            options={
                "root_path": "entries",
                "columns": [
                    {"field": "beat_id", "label": "Beat", "mono": True},
                    {"field": "type", "label": "Type", "badge": True},
                    {"field": "kind", "label": "Kind", "badge": True},
                    {"field": "subject", "label": "Subject"},
                    {"field": "hero_text", "label": "Hero text", "truncate": 40},
                    {"field": "asset_provider", "label": "Provider", "badge": True},
                    {"field": "thumb_path", "label": "Thumb", "mono": True, "truncate": 30},
                ],
            },
        ),
        RenderArtifact(
            type="image_gallery",
            title="Thumbnails generados",
            path_pattern="thumbs/*.jpg",
        ),
    ],
)
