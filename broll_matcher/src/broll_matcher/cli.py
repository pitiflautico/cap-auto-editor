"""CLI for the broll_matcher phase."""
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

    from .matcher import match

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl"
    )
    emitter.emit_run_start(phase="broll_matcher", total_steps=2)

    # Step 1: load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=2, name="load",
                            detail="reading balanced analysis + visual_inventory")
    a_path = Path(args.analysis)
    inv_path = Path(args.visual_inventory)
    if not a_path.exists() or not inv_path.exists():
        print("ERROR: analysis or visual_inventory missing", file=sys.stderr)
        return 1
    analysis = AnalysisResult.model_validate(
        json.loads(a_path.read_text(encoding="utf-8"))
    )
    inventory = VisualInventory.model_validate(
        json.loads(inv_path.read_text(encoding="utf-8"))
    )
    n_anchored = sum(
        1 for b in analysis.narrative.beats
        for h in b.broll_hints or []
        if "[@" in (h.description or "")
    )
    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"beats": len(analysis.narrative.beats),
                 "inventory_assets": len(inventory.assets),
                 "anchored_hints": n_anchored},
    )

    # Step 2: match
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=2, name="match",
                            detail=f"Haiku semantic match on {n_anchored} anchored hint(s)")
    new_analysis, report = match(analysis, inventory)
    emitter.emit_step_done(
        index=2, name="match",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={
            "total_anchored": report.total_beats_with_anchor,
            "re_anchored": report.re_anchored_count,
            "kept_deterministic": report.kept_deterministic,
            "fallback": report.fallback_count,
        },
    )

    (out_dir / "analysis_matched.json").write_text(
        new_analysis.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )
    (out_dir / "matcher_report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )

    print(f"OK {out_dir / 'analysis_matched.json'}")
    print(f"  total anchored hints : {report.total_beats_with_anchor}")
    print(f"  re-anchored by LLM   : {report.re_anchored_count}")
    print(f"  kept deterministic   : {report.kept_deterministic}")
    print(f"  fallback (LLM fail)  : {report.fallback_count}")

    emitter.emit_run_done(
        ok=True,
        summary={"re_anchored": report.re_anchored_count},
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(prog="broll-matcher",
                                 description="myavatar v6 — semantic LLM match per anchored hint")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Run semantic matching")
    run_p.add_argument("--analysis", required=True,
                       help="Path to analysis_balanced.json (post-finalizer)")
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
