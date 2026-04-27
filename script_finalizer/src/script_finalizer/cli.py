"""CLI for script_finalizer phase."""
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
    from visual_inventory.contracts import VisualInventory

    from .balancer import balance

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl"
    )
    emitter.emit_run_start(phase="script_finalizer", total_steps=2)

    # Step 1: load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=2, name="load",
                            detail="reading analysis + visual_inventory")
    analysis_path = Path(args.analysis)
    inventory_path = Path(args.visual_inventory)
    if not analysis_path.exists():
        print(f"ERROR: analysis not found: {analysis_path}", file=sys.stderr)
        return 1
    analysis = AnalysisResult.model_validate(
        json.loads(analysis_path.read_text(encoding="utf-8"))
    )
    if inventory_path.exists():
        inventory = VisualInventory.model_validate(
            json.loads(inventory_path.read_text(encoding="utf-8"))
        )
    else:
        # Empty inventory → tier=thin, conservative balancing
        from datetime import datetime, timezone
        inventory = VisualInventory(
            created_at=datetime.now(timezone.utc),
            capture_root=str(inventory_path.parent),
        )
    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"beats": len(analysis.narrative.beats),
                 "inventory_assets": len(inventory.assets)},
    )

    # Step 2: balance
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=2, name="balance",
                            detail="adaptive industry baselines")
    balanced, report = balance(analysis, inventory)
    emitter.emit_step_done(
        index=2, name="balance",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={
            "material_score": report.material_score,
            "material_strength": report.material_strength,
            "hints_before": report.hints_before,
            "hints_after": report.hints_after,
            "coverage_before_pct": report.coverage_pct_before,
            "coverage_after_pct": report.coverage_pct_after,
        },
    )

    (out_dir / "analysis_balanced.json").write_text(
        balanced.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )
    (out_dir / "finalizer_report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )

    print(f"OK {out_dir / 'analysis_balanced.json'}")
    print(f"  material_score    : {report.material_score} ({report.material_strength})")
    print(f"  broll target      : {report.broll_target_min*100:.0f}-{report.broll_target_max*100:.0f}%")
    print(f"  beats             : {report.beats_before} → {report.beats_after}")
    print(f"  hints             : {report.hints_before} → {report.hints_after}")
    print(f"  coverage          : {report.coverage_pct_before}% → {report.coverage_pct_after}%")
    print(f"  real footage      : {report.real_footage_ratio_before:.0%} → {report.real_footage_ratio_after:.0%}")
    print(f"  filler            : {report.filler_ratio_before:.0%} → {report.filler_ratio_after:.0%}")
    if report.notes:
        print("\n  notes:")
        for n in report.notes:
            print(f"    - {n}")

    emitter.emit_run_done(
        ok=True,
        summary={"hints_after": report.hints_after,
                 "coverage_pct_after": report.coverage_pct_after,
                 "material_strength": report.material_strength},
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(prog="script-finalizer",
                                 description="myavatar v6 — adaptive broll balancer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Run balancer")
    run_p.add_argument("--analysis", required=True,
                       help="Path to analysis.json (post-analysis or post-auto_source)")
    run_p.add_argument("--visual-inventory", dest="visual_inventory", required=True,
                       help="Path to visual_inventory.json")
    run_p.add_argument("--out-dir", dest="out_dir", required=True)
    run_p.add_argument("--no-progress", dest="no_progress", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        sys.exit(_cmd_run(args))
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
