"""acquisition phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

ACQ_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "acquisition/.venv/bin/acquisition"
)


def _acq_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    return [
        "--pending", str(ctx.run_dir / "broll_resolver" / "pending_acquisition.json"),
        "--broll-plan", str(ctx.run_dir / "broll_resolver" / "broll_plan.json"),
        "--out-dir", str(phase_dir),
    ]


acquisition_descriptor = PhaseDescriptor(
    name="acquisition",
    display_name="Acquisition",
    order=11,
    out_subdir="acquisition",
    cli_command=[ACQ_BIN, "run"],
    cli_args=_acq_args,
    depends_on=["broll_resolver"],
    on_failure="skip",
    retry_max=0,
    timeout_s=600,
    render_artifacts=[
        RenderArtifact(
            type="key_value",
            title="Resumen acquisition",
            path="acquisition_report.json",
            options={
                "fields": [
                    {"key": "pending_total", "label": "Pending total"},
                    {"key": "acquired_count", "label": "Acquired"},
                    {"key": "text_card_fallback", "label": "Text-card fallback"},
                    {"key": "api_errors", "label": "API errors"},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Adquisiciones (pexels / text_card)",
            path="acquisition_report.json",
            options={
                "root_path": "entries",
                "columns": [
                    {"field": "beat_id", "label": "Beat", "mono": True},
                    {"field": "type", "label": "Type", "badge": True},
                    {"field": "kind", "label": "Kind", "badge": True},
                    {"field": "subject", "label": "Subject"},
                    {"field": "final_provider", "label": "Provider", "badge": True},
                    {"field": "abs_path", "label": "Path", "mono": True, "truncate": 50},
                    {"field": "duration_s", "label": "Dur (s)"},
                ],
            },
        ),
    ],
)
