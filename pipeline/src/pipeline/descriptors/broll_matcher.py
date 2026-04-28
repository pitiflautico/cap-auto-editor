"""broll_matcher phase descriptor."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

BM_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "broll_matcher/.venv/bin/broll-matcher"
)


def _bm_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    return [
        "--analysis", str(ctx.run_dir / "script_finalizer" / "analysis_balanced.json"),
        "--visual-inventory", str(ctx.run_dir / "visual_inventory" / "visual_inventory.json"),
        "--out-dir", str(phase_dir),
    ]


broll_matcher_descriptor = PhaseDescriptor(
    name="broll_matcher",
    display_name="B-roll Matcher (LLM)",
    order=9,
    out_subdir="broll_matcher",
    cli_command=[BM_BIN, "run"],
    cli_args=_bm_args,
    depends_on=["script_finalizer"],
    on_failure="skip",
    retry_max=0,
    timeout_s=600,
    render_artifacts=[
        RenderArtifact(
            type="key_value",
            title="Resumen matcher",
            path="matcher_report.json",
            options={
                "fields": [
                    {"key": "total_beats_with_anchor", "label": "Beats anchored"},
                    {"key": "re_anchored_count", "label": "Re-anchored por LLM"},
                    {"key": "kept_deterministic", "label": "Mantuvo determinista"},
                    {"key": "fallback_count", "label": "LLM fallback"},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Decisiones por beat",
            path="matcher_report.json",
            options={
                "root_path": "decisions",
                "columns": [
                    {"field": "beat_id", "label": "Beat", "mono": True},
                    {"field": "editorial_function", "label": "EF", "badge": True},
                    {"field": "n_candidates", "label": "Cands"},
                    {"field": "chosen_idx", "label": "Pick"},
                    {"field": "fallback_used", "label": "Fallback?"},
                    {"field": "beat_text", "label": "Beat", "truncate": 60},
                    {"field": "rationale", "label": "Rationale", "truncate": 80},
                ],
            },
        ),
    ],
)
