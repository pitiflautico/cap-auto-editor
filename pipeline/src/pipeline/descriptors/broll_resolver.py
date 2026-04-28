"""broll_resolver phase descriptor (MVP)."""
from __future__ import annotations

from pathlib import Path

from pipeline.contracts import PhaseDescriptor, RenderArtifact, RunContext

BR_BIN = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "broll_resolver/.venv/bin/broll-resolver"
)


def _br_args(ctx: RunContext, phase_dir: Path) -> list[str]:
    # Prefer the post-matcher analysis (LLM-refined anchors); fall back to
    # balanced → super_enriched → enriched → raw.
    candidates = [
        ctx.run_dir / "broll_matcher" / "analysis_matched.json",
        ctx.run_dir / "script_finalizer" / "analysis_balanced.json",
        ctx.run_dir / "auto_source" / "analysis_super_enriched.json",
        ctx.run_dir / "entity_enricher" / "analysis_enriched.json",
        ctx.run_dir / "analysis" / "analysis.json",
    ]
    analysis_path = next((p for p in candidates if p.exists()), candidates[-1])

    enriched_manifest = ctx.run_dir / "auto_source" / "capture_manifest_enriched.json"
    raw_manifest = ctx.run_dir / "capture" / "capture_manifest.json"
    manifest = enriched_manifest if enriched_manifest.exists() else raw_manifest

    return [
        "--analysis", str(analysis_path),
        "--capture-manifest", str(manifest),
        "--out-dir", str(phase_dir),
    ]


broll_resolver_descriptor = PhaseDescriptor(
    name="broll_resolver",
    display_name="B-roll Resolver",
    order=10,
    out_subdir="broll_resolver",
    cli_command=[BR_BIN, "run"],
    cli_args=_br_args,
    depends_on=["broll_matcher"],
    on_failure="skip",
    retry_max=0,
    timeout_s=120,
    render_artifacts=[
        RenderArtifact(
            type="key_value",
            title="Resumen",
            path="broll_resolver_report.json",
            options={
                "fields": [
                    {"key": "total_hints", "label": "Total hints"},
                    {"key": "resolved_count", "label": "Resolved"},
                    {"key": "pending_count", "label": "Pending acquisition"},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Resolved (asset on disk)",
            path="broll_plan.json",
            options={
                "root_path": "resolved",
                "columns": [
                    {"field": "beat_id", "label": "Beat", "mono": True},
                    {"field": "type", "label": "Type", "badge": True},
                    {"field": "kind", "label": "Kind", "badge": True},
                    {"field": "source", "label": "Resolution", "badge": True},
                    {"field": "subject", "label": "Subject"},
                    {"field": "slug", "label": "Slug", "mono": True},
                    {"field": "abs_path", "label": "Path", "mono": True, "truncate": 60},
                    {"field": "t_start_s", "label": "t_start", "format": "seconds"},
                    {"field": "t_end_s", "label": "t_end", "format": "seconds"},
                    {"field": "duration_s", "label": "Dur (s)"},
                ],
            },
        ),
        RenderArtifact(
            type="json_table",
            title="Pending acquisition (a buscar)",
            path="pending_acquisition.json",
            options={
                "root_path": "pending",
                "columns": [
                    {"field": "beat_id", "label": "Beat", "mono": True},
                    {"field": "type", "label": "Type", "badge": True},
                    {"field": "subject", "label": "Subject"},
                    {"field": "shot_type", "label": "Shot", "badge": True},
                    {"field": "query", "label": "Query", "truncate": 60},
                    {"field": "queries_fallback", "label": "Fallbacks",
                     "format": "join_csv", "truncate": 60},
                    {"field": "duration_target_s", "label": "Dur target"},
                    {"field": "editorial_function", "label": "Fn", "badge": True},
                    {"field": "reason", "label": "Reason", "truncate": 60},
                ],
            },
        ),
    ],
)
