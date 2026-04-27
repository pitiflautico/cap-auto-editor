"""CLI for auto_source phase."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    from analysis.contracts import AnalysisResult
    from progress import NullEmitter, ProgressEmitter

    from .orchestrator import auto_source

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl"
    )
    emitter.emit_run_start(phase="auto_source", total_steps=2)

    # Step 1: load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=2, name="load",
                            detail="reading enriched analysis + manifest")
    enriched_path = Path(args.enriched_analysis)
    if not enriched_path.exists():
        print(f"ERROR: enriched analysis not found: {enriched_path}", file=sys.stderr)
        return 1
    raw = json.loads(enriched_path.read_text(encoding="utf-8"))
    enriched = AnalysisResult.model_validate(raw)

    capture_path = Path(args.capture_manifest) if args.capture_manifest else None
    capture_manifest = {}
    capture_out_dir = out_dir
    if capture_path and capture_path.exists():
        capture_manifest = json.loads(capture_path.read_text(encoding="utf-8"))
        # captures/ live in the same directory as the manifest
        capture_out_dir = capture_path.parent

    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"topics": len(enriched.narrative.topics),
                 "existing_captures": len(capture_manifest.get("results", []))},
    )

    # Step 2: auto-source
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=2, name="auto_source",
                            detail="searching official URLs + recapture")
    super_enriched, merged_manifest, report = auto_source(
        enriched, capture_manifest, capture_out_dir,
        recapture=not args.no_recapture,
    )
    elapsed = int((time.monotonic() - t0) * 1000)
    emitter.emit_step_done(
        index=2, name="auto_source", duration_ms=elapsed,
        summary={
            "topics_eligible": report.topics_eligible,
            "topics_resolved": report.topics_resolved,
            "new_captures": report.new_captures,
        },
    )

    (out_dir / "analysis_super_enriched.json").write_text(
        super_enriched.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )
    (out_dir / "capture_manifest_enriched.json").write_text(
        json.dumps(merged_manifest, indent=2), encoding="utf-8"
    )
    (out_dir / "auto_source_report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )

    print(f"OK {out_dir / 'analysis_super_enriched.json'}")
    print(f"  topics total      : {report.topics_total}")
    print(f"  topics eligible   : {report.topics_eligible}")
    print(f"  topics resolved   : {report.topics_resolved}")
    print(f"  new captures      : {report.new_captures}")
    if report.errors:
        print(f"  errors            : {len(report.errors)}")

    emitter.emit_run_done(
        ok=True,
        summary={"topics_resolved": report.topics_resolved,
                 "new_captures": report.new_captures},
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(prog="auto-source",
                                 description="myavatar v6 — auto-discover official URLs per topic")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Run auto-source on an enriched analysis")
    run_p.add_argument("--enriched-analysis", dest="enriched_analysis", required=True,
                       help="Path to analysis_enriched.json (output of entity_enricher)")
    run_p.add_argument("--capture-manifest", dest="capture_manifest", default=None,
                       help="Path to current capture_manifest.json")
    run_p.add_argument("--out-dir", dest="out_dir", required=True,
                       help="Output directory (writes super_enriched + merged manifest)")
    run_p.add_argument("--no-recapture", dest="no_recapture", action="store_true",
                       help="Discover URLs but skip the capture subprocess")
    run_p.add_argument("--no-progress", dest="no_progress", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "run":
        sys.exit(_cmd_run(args))
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
