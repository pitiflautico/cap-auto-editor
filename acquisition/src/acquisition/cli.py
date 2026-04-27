"""CLI for the acquisition phase."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    from progress import NullEmitter, ProgressEmitter
    # Load .env for PEXELS_API_KEY (no-op if dotenv missing)
    try:
        from dotenv import load_dotenv     # type: ignore
        for env in (Path(args.pending).parent / ".env",
                    Path.cwd() / ".env",
                    Path(__file__).resolve().parents[5] / ".env"):
            if env.exists():
                load_dotenv(env)
                break
    except ImportError:
        pass

    from .orchestrator import acquire

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl"
    )
    emitter.emit_run_start(phase="acquisition", total_steps=2)

    # Step 1: load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=2, name="load",
                            detail="reading pending_acquisition.json")
    p_path = Path(args.pending)
    if not p_path.exists():
        print(f"ERROR: pending file not found: {p_path}", file=sys.stderr)
        return 1
    pending = json.loads(p_path.read_text(encoding="utf-8"))
    n_pending = len(pending.get("pending") or [])
    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"pending_total": n_pending},
    )

    # Step 2: acquire
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=2, name="acquire",
                            detail=f"cascade per type for {n_pending} pending hint(s)")
    report = acquire(pending, out_dir)
    elapsed = int((time.monotonic() - t0) * 1000)
    emitter.emit_step_done(
        index=2, name="acquire", duration_ms=elapsed,
        summary={
            "pending_total": report.pending_total,
            "acquired": report.acquired_count,
            "text_card_fallback": report.text_card_fallback,
            "api_errors": report.api_errors,
        },
    )

    # Build broll_plan_complete by merging the existing broll_plan with the
    # new entries (simple side-by-side; the compositor consumes both).
    plan_resolved: list[dict] = []
    if args.broll_plan:
        plan_path = Path(args.broll_plan)
        if plan_path.exists():
            plan_resolved = json.loads(plan_path.read_text()).get("resolved") or []

    # Convert AcquisitionEntry → ResolvedAsset-shaped dict for downstream compositor
    extra_resolved = []
    for e in report.entries:
        if not e.abs_path:
            continue
        extra_resolved.append({
            "beat_id": e.beat_id,
            "hint_index": e.hint_index,
            "kind": e.kind or "title",
            "source": e.final_provider or "text_card",
            "abs_path": e.abs_path,
            "slug": None,
            "t_start_s": None,
            "t_end_s": None,
            "duration_s": e.duration_s,
            "width": e.width, "height": e.height,
            "type": e.type_,
            "subject": e.subject,
            "description": "",
            "beat_start_s": 0.0, "beat_end_s": 0.0,
        })

    complete = {
        "schema_version": "1.0.0",
        "created_at": report.created_at.isoformat(),
        "resolved": plan_resolved + extra_resolved,
    }

    (out_dir / "pending_acquired.json").write_text(
        report.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )
    (out_dir / "broll_plan_complete.json").write_text(
        json.dumps(complete, indent=2), encoding="utf-8"
    )
    (out_dir / "acquisition_report.json").write_text(
        report.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )

    print(f"OK {out_dir / 'pending_acquired.json'}")
    print(f"  pending total      : {report.pending_total}")
    print(f"  acquired           : {report.acquired_count}")
    print(f"  text_card fallback : {report.text_card_fallback}")
    print(f"  api errors         : {report.api_errors}")
    if report.provider_counts:
        for k, v in sorted(report.provider_counts.items(), key=lambda kv: -kv[1]):
            print(f"     {k:25}  {v}")

    emitter.emit_run_done(
        ok=True,
        summary={"acquired": report.acquired_count,
                 "text_card_fallback": report.text_card_fallback},
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(prog="acquisition",
                                 description="myavatar v6 — fulfil pending broll hints (Pexels + text_card)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Run acquisition cascade")
    run_p.add_argument("--pending", required=True,
                       help="Path to pending_acquisition.json (from broll_resolver)")
    run_p.add_argument("--broll-plan", dest="broll_plan", default=None,
                       help="Path to broll_plan.json (from broll_resolver) — merged into broll_plan_complete.json")
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
