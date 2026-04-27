"""CLI for broll_resolver phase (MVP)."""
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

    from .resolver import resolve

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl"
    )
    emitter.emit_run_start(phase="broll_resolver", total_steps=2)

    # Step 1: load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=2, name="load",
                            detail="reading balanced analysis + manifest")
    a_path = Path(args.analysis)
    m_path = Path(args.capture_manifest)
    if not a_path.exists() or not m_path.exists():
        print("ERROR: analysis or manifest missing", file=sys.stderr)
        return 1
    analysis = AnalysisResult.model_validate(
        json.loads(a_path.read_text(encoding="utf-8"))
    )
    manifest = json.loads(m_path.read_text(encoding="utf-8"))
    captures_root = m_path.parent
    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"beats": len(analysis.narrative.beats),
                 "captures": len(manifest.get("results", []))},
    )

    # Step 2: resolve
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=2, name="resolve",
                            detail="cascade: anchor → source_ref → screenshot → title → pending")
    plan, pending, report = resolve(analysis, manifest, captures_root)
    emitter.emit_step_done(
        index=2, name="resolve",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"resolved": report.resolved_count,
                 "pending": report.pending_count},
    )

    (out_dir / "broll_plan.json").write_text(
        plan.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )
    (out_dir / "pending_acquisition.json").write_text(
        pending.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )
    (out_dir / "broll_resolver_report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )

    print(f"OK {out_dir / 'broll_plan.json'}")
    print(f"  total hints     : {report.total_hints}")
    print(f"  resolved        : {report.resolved_count}")
    for k, v in sorted(report.resolved_by_source.items(), key=lambda kv: -kv[1]):
        print(f"     {k:30}  {v}")
    print(f"  pending         : {report.pending_count}")
    for k, v in sorted(report.pending_by_type.items(), key=lambda kv: -kv[1]):
        print(f"     {k:30}  {v}")

    emitter.emit_run_done(
        ok=True,
        summary={"resolved": report.resolved_count,
                 "pending": report.pending_count},
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(prog="broll-resolver",
                                 description="myavatar v6 — resolve broll hints to abs paths or pending acquisitions")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Run resolver")
    run_p.add_argument("--analysis", required=True,
                       help="Path to analysis_balanced.json (or analysis.json)")
    run_p.add_argument("--capture-manifest", dest="capture_manifest", required=True,
                       help="Path to capture_manifest_enriched.json (or capture_manifest.json)")
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
