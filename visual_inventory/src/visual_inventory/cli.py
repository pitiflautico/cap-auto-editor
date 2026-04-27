"""CLI for visual_inventory phase."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    from progress import NullEmitter, ProgressEmitter
    from .inventory import build_inventory

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl"
    )
    emitter.emit_run_start(phase="visual_inventory", total_steps=2)

    # Step 1: load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=2, name="load",
                            detail="reading capture manifest")
    capture_path = Path(args.capture_manifest)
    if not capture_path.exists():
        print(f"ERROR: capture manifest not found: {capture_path}", file=sys.stderr)
        return 1
    capture_manifest = json.loads(capture_path.read_text(encoding="utf-8"))
    # Prefer the manifest's own `out_dir` (the recapture step keeps files in
    # the original capture/ dir even when the enriched manifest is written
    # under auto_source/). Falls back to the manifest's own dir.
    out_dir_field = capture_manifest.get("out_dir")
    captures_root = Path(out_dir_field).resolve() if out_dir_field else capture_path.parent
    n_video_assets = sum(
        1 for r in capture_manifest.get("results", [])
        for a in (r.get("artifacts") or {}).get("assets", [])
        if a.get("kind") in {"video", "og_image", "gif"}
    )
    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"video_assets": n_video_assets},
    )

    # Step 2: inventory
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=2, name="inventory",
                            detail=f"keyframes + vision on {n_video_assets} video assets")
    inv = build_inventory(
        capture_manifest, captures_root, out_dir,
        start_s=args.start_s, step_s=args.step_s, max_s=args.max_s,
    )
    emitter.emit_step_done(
        index=2, name="inventory",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={
            "assets": len(inv.assets),
            "skipped": len(inv.skipped),
            "errors": len(inv.errors),
        },
    )

    out_path = out_dir / "visual_inventory.json"
    out_path.write_text(inv.model_dump_json(indent=2, by_alias=True),
                        encoding="utf-8")

    print(f"OK {out_path}")
    print(f"  video assets analyzed : {len(inv.assets)}")
    print(f"  skipped               : {len(inv.skipped)}")
    print(f"  errors                : {len(inv.errors)}")
    for a in inv.assets:
        sf = ", ".join(a.shot_types_seen) or "—"
        dur = f"{a.duration_s:.1f}s" if a.duration_s is not None else "image"
        print(f"  - {a.slug}/{Path(a.asset_path).name}  ({dur}, q={a.overall_quality}, shots=[{sf}], segments={len(a.best_segments)})")

    emitter.emit_run_done(
        ok=True,
        summary={"assets": len(inv.assets)},
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(prog="visual-inventory",
                                 description="myavatar v6 — vision LLM inventory of captured video assets")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Run inventory")
    run_p.add_argument("--capture-manifest", dest="capture_manifest", required=True,
                       help="Path to capture_manifest.json (or capture_manifest_enriched.json)")
    run_p.add_argument("--out-dir", dest="out_dir", required=True)
    run_p.add_argument("--start-s", dest="start_s", type=float, default=1.0,
                       help="First keyframe timestamp in seconds (default 1)")
    run_p.add_argument("--step-s", dest="step_s", type=float, default=5.0,
                       help="Step between keyframes (default 5)")
    run_p.add_argument("--max-s", dest="max_s", type=float, default=40.0,
                       help="Stop sampling past this timestamp (default 40)")
    run_p.add_argument("--no-progress", dest="no_progress", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        sys.exit(_cmd_run(args))
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
