"""CLI for the storyboard phase."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    from progress import NullEmitter, ProgressEmitter
    from .builder import build_storyboard

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl"
    )
    emitter.emit_run_start(phase="storyboard", total_steps=2)

    # Step 1: load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=2, name="load",
                            detail="reading broll plan + analysis")
    plan_path = Path(args.broll_plan)
    if not plan_path.exists():
        print(f"ERROR: broll plan not found: {plan_path}", file=sys.stderr)
        return 1
    broll_plan = json.loads(plan_path.read_text(encoding="utf-8"))

    duration_s = 0.0
    hero_by_beat: dict[str, str] = {}
    window_by_id: dict[str, tuple[float, float]] = {}
    if args.analysis:
        a_path = Path(args.analysis)
        if a_path.exists():
            data = json.loads(a_path.read_text(encoding="utf-8"))
            duration_s = float(data.get("duration_s") or 0)
            for b in (data.get("narrative") or {}).get("beats") or []:
                bid = b.get("beat_id")
                if bid:
                    hero_by_beat[bid] = b.get("hero_text_candidate") or ""
                    window_by_id[bid] = (
                        float(b.get("start_s") or 0),
                        float(b.get("end_s") or 0),
                    )
    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"resolved_in_plan": len(broll_plan.get("resolved") or []),
                 "duration_s": duration_s},
    )

    # Step 2: build thumbs
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=2, name="thumbs",
                            detail="extracting one thumb per resolved entry")
    sb = build_storyboard(
        broll_plan, duration_s, out_dir,
        hero_text_by_beat=hero_by_beat,
        beat_window_by_id=window_by_id,
    )
    elapsed = int((time.monotonic() - t0) * 1000)
    emitter.emit_step_done(
        index=2, name="thumbs", duration_ms=elapsed,
        summary={"entries": len(sb.entries),
                 "notes": len(sb.notes)},
    )

    (out_dir / "storyboard.json").write_text(
        sb.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )

    print(f"OK {out_dir / 'storyboard.json'}")
    print(f"  entries     : {len(sb.entries)}")
    print(f"  duration    : {sb.duration_s:.1f}s")
    if sb.notes:
        print(f"  notes       : {len(sb.notes)}")
    by_kind: dict[str, int] = {}
    for e in sb.entries:
        by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
    for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"     {k:12} {v}")

    emitter.emit_run_done(ok=True, summary={"entries": len(sb.entries)})
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(prog="storyboard",
                                 description="myavatar v6 — preview thumbs per beat")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Build storyboard from broll plan")
    run_p.add_argument("--broll-plan", dest="broll_plan", required=True,
                       help="Path to broll_plan_complete.json (post-acquisition) "
                            "or broll_plan.json (post-resolver)")
    run_p.add_argument("--analysis", dest="analysis", default=None,
                       help="Path to analysis_balanced.json (for hero_text + beat windows)")
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
