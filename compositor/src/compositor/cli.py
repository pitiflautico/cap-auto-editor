"""CLI for the compositor (CapCut export) phase.

    compositor run \\
        --analysis      ~/runs/X/broll_planner/analysis_with_broll.json \\
        --broll-plan    ~/runs/X/acquisition/broll_plan_complete.json \\
        --subtitles     ~/runs/X/subtitler/subtitle_clips.json \\
        --presenter     ~/runs/X/<presenter>.mp4 \\
        --background    /Volumes/.../assets/background_black.png \\
        --out-dir       ~/runs/X/compositor \\
        [--music /path/to/track.mp3] \\
        [--install-to-capcut]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    from progress import NullEmitter, ProgressEmitter
    from .adapter import build_visual_plan
    from .builder import (
        install_to_capcut, run_v4_build, write_visual_plan,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl",
    )
    emitter.emit_run_start(phase="compositor", total_steps=4)

    # Step 1 — load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=4, name="load",
                            detail="reading analysis + broll + subtitles")
    try:
        analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
        broll_plan = json.loads(Path(args.broll_plan).read_text(encoding="utf-8"))
        subtitles = json.loads(Path(args.subtitles).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: load failed — {exc}", file=sys.stderr)
        emitter.emit_run_done(ok=False, summary={"error": str(exc)[:200]})
        return 1
    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={
            "duration_s": float(analysis.get("duration_s") or 0),
            "broll": len(broll_plan.get("resolved") or []),
            "subs": len(subtitles.get("clips") or []),
        },
    )

    # Step 2 — adapt
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=4, name="adapt",
                            detail="v6 → v4 visual_plan_resolved.json")
    visual_plan = build_visual_plan(
        analysis=analysis,
        broll_plan=broll_plan,
        subtitle_clips=subtitles,
        presenter_video_path=args.presenter,
        background_path=args.background,
        music_path=args.music,
        project_name=args.project_name,
    )
    plan_path = write_visual_plan(visual_plan, out_dir)
    n_pres = sum(1 for b in visual_plan["beats"] if b["type"] == "presenter")
    n_broll = sum(1 for b in visual_plan["beats"]
                  if b["type"] in ("broll_image", "broll_video"))
    n_punch = sum(1 for b in visual_plan["beats"] if b.get("punch_text"))
    emitter.emit_step_done(
        index=2, name="adapt",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"presenter_beats": n_pres, "broll_beats": n_broll,
                 "punch_overlays": n_punch,
                 "subtitle_phrases": len(visual_plan["subtitle_cues"])},
    )

    # Step 3 — v4 build
    t0 = time.monotonic()
    emitter.emit_step_start(index=3, total=4, name="capcut_build",
                            detail="agent4_builder → draft_info.json")
    try:
        capcut_dir = out_dir / "capcut_project"
        result = run_v4_build(
            visual_plan_path=plan_path,
            capcut_project_dir=capcut_dir,
            project_name=args.project_name,
        )
    except Exception as exc:
        print(f"ERROR: v4 build crashed — {exc}", file=sys.stderr)
        emitter.emit_run_done(ok=False, summary={"error": str(exc)[:200]})
        return 1
    emitter.emit_step_done(
        index=3, name="capcut_build",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"warnings": len(result.get("warnings") or []),
                 "duration_us": result.get("duration_us")},
    )

    # Step 4 — install (optional)
    installed_dir: Path | None = None
    if args.install_to_capcut:
        t0 = time.monotonic()
        emitter.emit_step_start(index=4, total=4, name="install",
                                detail="copy → CapCut User Data Projects")
        try:
            installed_dir = install_to_capcut(Path(result["project_dir"]))
        except Exception as exc:
            print(f"WARNING: install to CapCut failed — {exc}",
                  file=sys.stderr)
        emitter.emit_step_done(
            index=4, name="install",
            duration_ms=int((time.monotonic() - t0) * 1000),
            summary={"installed_to": str(installed_dir) if installed_dir else None},
        )
    else:
        emitter.emit_step_start(index=4, total=4, name="install",
                                detail="skipped (--install-to-capcut not set)")
        emitter.emit_step_done(
            index=4, name="install", duration_ms=0,
            summary={"installed": False},
        )

    # Persist composition_result.json (parallel to compositor_hf)
    composition_result = {
        "schema_version": "1.0.0",
        "status": "ok",
        "visual_plan": str(plan_path),
        "capcut_project_dir": result["project_dir"],
        "draft_info_path": result["draft_info_path"],
        "duration_us": result["duration_us"],
        "warnings": result["warnings"],
        "installed_to": str(installed_dir) if installed_dir else None,
    }
    (out_dir / "composition_result.json").write_text(
        json.dumps(composition_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"OK {result['project_dir']}")
    print(f"  draft_info : {result['draft_info_path']}")
    print(f"  warnings   : {len(result['warnings'])}")
    if installed_dir:
        print(f"  installed  : {installed_dir}")
    print(f"  visual plan: {plan_path}")

    emitter.emit_run_done(ok=True, summary={
        "presenter_beats": n_pres, "broll_beats": n_broll,
        "punch_overlays": n_punch,
    })
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(
        prog="compositor",
        description="myavatar v6 — compositor (CapCut export via v4 agent4_builder)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Build the CapCut project")
    run_p.add_argument("--analysis", required=True)
    run_p.add_argument("--broll-plan", dest="broll_plan", required=True)
    run_p.add_argument("--subtitles", required=True)
    run_p.add_argument("--presenter", required=True,
                       help="Path to the presenter video (h264 mp4 preferred)")
    run_p.add_argument("--background", required=True,
                       help="Path to a 1080×1920 background PNG")
    run_p.add_argument("--out-dir", dest="out_dir", required=True)
    run_p.add_argument("--music", default=None,
                       help="Optional music track path (mp3/m4a/wav)")
    run_p.add_argument("--project-name", dest="project_name", default=None)
    run_p.add_argument("--install-to-capcut", dest="install_to_capcut",
                       action="store_true",
                       help="Copy the built project into CapCut User Data")
    run_p.add_argument("--no-progress", dest="no_progress", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        sys.exit(_cmd_run(args))
    ap.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
