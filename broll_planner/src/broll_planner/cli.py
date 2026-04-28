"""CLI for the broll_planner phase."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    from progress import NullEmitter, ProgressEmitter
    from analysis.contracts import AnalysisResult
    from .planner import call_planner_llm, merge_plans_into_analysis, _valid_slugs

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl",
    )
    emitter.emit_run_start(phase="broll_planner", total_steps=3)

    # Step 1 — load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=3, name="load",
                            detail="reading analysis + capture + inventory")
    a_path = Path(args.analysis)
    if not a_path.exists():
        print(f"ERROR: analysis not found: {a_path}", file=sys.stderr)
        emitter.emit_run_done(ok=False, summary={"error": "analysis_not_found"})
        return 1
    analysis = AnalysisResult.model_validate_json(a_path.read_text(encoding="utf-8"))

    cap_path = Path(args.capture_manifest)
    capture_manifest = json.loads(cap_path.read_text(encoding="utf-8"))

    inv_path = Path(args.visual_inventory) if args.visual_inventory else None
    visual_inventory = None
    if inv_path and inv_path.exists():
        visual_inventory = json.loads(inv_path.read_text(encoding="utf-8"))

    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"beats": len(analysis.narrative.beats),
                 "sources": len(capture_manifest.get("results") or []),
                 "has_inventory": bool(visual_inventory)},
    )

    # Step 2 — LLM call
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=3, name="plan",
                            detail="LLM emits broll_hints per beat")
    try:
        plans = call_planner_llm(
            analysis=analysis,
            capture_manifest=capture_manifest,
            visual_inventory=visual_inventory,
            model=args.model,
            timeout_s=args.timeout,
        )
    except Exception as exc:
        print(f"ERROR: planner LLM call failed — {exc}", file=sys.stderr)
        emitter.emit_run_done(ok=False, summary={"error": str(exc)[:200]})
        return 1
    emitter.emit_step_done(
        index=2, name="plan",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"plans": len(plans)},
    )

    # Step 3 — merge + persist
    t0 = time.monotonic()
    emitter.emit_step_start(index=3, total=3, name="merge",
                            detail="validating + merging hints into analysis")
    valid = _valid_slugs(capture_manifest)
    new_analysis, report = merge_plans_into_analysis(
        analysis, plans, valid_slugs=valid,
    )

    out_analysis = out_dir / "analysis_with_broll.json"
    out_report = out_dir / "broll_planner_report.json"
    out_analysis.write_text(
        new_analysis.model_dump_json(indent=2), encoding="utf-8",
    )
    out_report.write_text(
        report.model_dump_json(indent=2), encoding="utf-8",
    )
    emitter.emit_step_done(
        index=3, name="merge",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"hints_emitted": report.hints_emitted,
                 "beats_planned": report.beats_planned,
                 "source_ref_anchors": report.source_ref_anchors,
                 "type_counts": report.type_counts},
    )

    print(f"OK {out_analysis}")
    print(f"  beats        : {report.beats_total}")
    print(f"  required     : {report.beats_required}")
    print(f"  optional     : {report.beats_optional}")
    print(f"  planned      : {report.beats_planned}")
    print(f"  hints        : {report.hints_emitted}")
    print(f"  source_ref   : {report.source_ref_anchors}")
    if report.type_counts:
        print("  type_counts  :", dict(report.type_counts))
    if report.notes:
        print(f"  notes        : {len(report.notes)}")
        for n in report.notes[:8]:
            print(f"    - {n}")

    emitter.emit_run_done(ok=True, summary={
        "hints": report.hints_emitted,
        "source_ref": report.source_ref_anchors,
    })
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(
        prog="broll-planner",
        description="myavatar v6 — second-pass LLM that fills broll_hints",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Plan b-roll for an analysis")
    run_p.add_argument("--analysis", required=True,
                       help="Path to analysis.json")
    run_p.add_argument("--capture-manifest", dest="capture_manifest", required=True,
                       help="Path to capture_manifest.json (with sources + assets)")
    run_p.add_argument("--visual-inventory", dest="visual_inventory", default=None,
                       help="Optional visual_inventory.json (Haiku tags)")
    run_p.add_argument("--out-dir", dest="out_dir", required=True)
    run_p.add_argument("--model", default="sonnet")
    run_p.add_argument("--timeout", type=int, default=300)
    run_p.add_argument("--no-progress", dest="no_progress", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        sys.exit(_cmd_run(args))
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
