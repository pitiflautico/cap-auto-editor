"""CLI for the compositor phase.

    compositor run \\
        --broll-plan  ~/runs/X/acquisition/broll_plan_complete.json \\
        --subtitles   ~/runs/X/subtitler/subtitle_clips.json \\
        --analysis    ~/runs/X/broll_planner/analysis_with_broll.json \\
        --audio       ~/runs/X/audio.wav \\
        --out-dir     ~/runs/X/compositor

Writes:
  • <out-dir>/composition_plan.json — the timed layer graph
  • <out-dir>/index.html             — the HyperFrames input
  • <out-dir>/hyperframes.json       — minimal HF scaffold
  • <out-dir>/final.mp4              — rendered video
  • <out-dir>/composition_result.json — status / sha256 / duration
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    from progress import NullEmitter, ProgressEmitter
    from .builder import beat_windows_from_analysis, build_plan, stage_assets
    from .contracts import CompositionResult
    from .html import render_html
    from .render import render_to_mp4, write_project

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl",
    )
    emitter.emit_run_start(phase="compositor", total_steps=4)

    # Step 1 — load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=4, name="load",
                            detail="reading plan + subtitles + analysis")
    try:
        broll_plan = json.loads(Path(args.broll_plan).read_text(encoding="utf-8"))
        subtitles = json.loads(Path(args.subtitles).read_text(encoding="utf-8"))
        analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: input read failed — {exc}", file=sys.stderr)
        emitter.emit_run_done(ok=False, summary={"error": str(exc)[:200]})
        return 1
    duration_s = float(analysis.get("duration_s") or subtitles.get("duration_s") or 0.0)
    if duration_s <= 0:
        print("ERROR: cannot infer duration_s from analysis or subtitles",
              file=sys.stderr)
        emitter.emit_run_done(ok=False, summary={"error": "no_duration"})
        return 1
    audio_abs = Path(args.audio) if args.audio else None
    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"duration_s": round(duration_s, 1),
                 "broll": len(broll_plan.get("resolved") or []),
                 "subs": len(subtitles.get("clips") or [])},
    )

    # Step 2 — build composition plan (after staging assets locally so
    # HyperFrames' headless Chromium loads them as same-origin URLs).
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=4, name="plan",
                            detail="staging assets + materialising layer graph")
    staged_plan, staged_audio = stage_assets(
        broll_plan=broll_plan,
        audio_abs_path=audio_abs,
        project_root=out_dir,
    )
    plan = build_plan(
        broll_plan=staged_plan,
        subtitle_clips=subtitles,
        duration_s=duration_s,
        beat_window_by_id=beat_windows_from_analysis(analysis),
        project_root=out_dir,
        audio_abs_path=staged_audio,
        width=args.width, height=args.height, fps=args.fps,
    )
    plan_path = out_dir / "composition_plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    n_broll = sum(1 for l in plan.layers if l.kind == "broll")
    n_sub = sum(1 for l in plan.layers if l.kind == "subtitle")
    emitter.emit_step_done(
        index=2, name="plan",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"broll_layers": n_broll, "subtitle_layers": n_sub,
                 "audio": bool(plan.audio_rel)},
    )

    # Step 3 — write index.html
    t0 = time.monotonic()
    emitter.emit_step_start(index=3, total=4, name="html",
                            detail="emitting HTML+GSAP")
    html = render_html(plan)
    write_project(out_dir, html)
    emitter.emit_step_done(
        index=3, name="html",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"html_bytes": len(html)},
    )

    # Step 4 — render
    out_mp4 = out_dir / "final.mp4"
    t0 = time.monotonic()
    emitter.emit_step_start(index=4, total=4, name="render",
                            detail="npx hyperframes render")
    res = render_to_mp4(project_dir=out_dir, out_mp4=out_mp4,
                         fps=args.fps, quality=args.quality,
                         timeout_s=args.timeout)
    elapsed = int((time.monotonic() - t0) * 1000)
    if res["status"] == "ok":
        result = CompositionResult(
            created_at=datetime.now(timezone.utc),
            status="ok",
            out_mp4=str(out_mp4),
            duration_s=res.get("duration_s"),
            sha256=res.get("sha256"),
            layer_counts={"broll": n_broll, "subtitle": n_sub},
        )
        (out_dir / "composition_result.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8",
        )
        emitter.emit_step_done(
            index=4, name="render", duration_ms=elapsed,
            summary={"mp4_bytes": out_mp4.stat().st_size},
        )
        print(f"OK {out_mp4}")
        print(f"  duration : {res.get('duration_s'):.2f}s" if res.get("duration_s") else "")
        print(f"  layers   : broll={n_broll} subtitle={n_sub} audio={bool(plan.audio_rel)}")
        print(f"  sha256   : {res.get('sha256','?')[:16]}…")
        emitter.emit_run_done(ok=True, summary={"layers": len(plan.layers)})
        return 0

    result = CompositionResult(
        created_at=datetime.now(timezone.utc),
        status="failed",
        message=res.get("message"),
    )
    (out_dir / "composition_result.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8",
    )
    emitter.emit_step_done(
        index=4, name="render", duration_ms=elapsed,
        summary={"error": (res.get("message") or "")[:200]},
    )
    print(f"ERROR: render failed — {res.get('message')}", file=sys.stderr)
    emitter.emit_run_done(ok=False, summary={"error": (res.get("message") or "")[:200]})
    return 1


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(
        prog="compositor",
        description="myavatar v6 — final 1080×1920 MP4 from broll + subtitles + audio",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Compose final video")
    run_p.add_argument("--broll-plan", dest="broll_plan", required=True)
    run_p.add_argument("--subtitles", required=True)
    run_p.add_argument("--analysis", required=True,
                       help="Analysis JSON to read beat windows from")
    run_p.add_argument("--audio", default=None,
                       help="Path to audio.wav (default: <out-dir>/audio.wav)")
    run_p.add_argument("--out-dir", dest="out_dir", required=True)
    run_p.add_argument("--width", type=int, default=1080)
    run_p.add_argument("--height", type=int, default=1920)
    run_p.add_argument("--fps", type=int, default=30)
    run_p.add_argument("--quality", default="draft", choices=["draft", "high"])
    run_p.add_argument("--timeout", type=int, default=1200)
    run_p.add_argument("--no-progress", dest="no_progress", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        sys.exit(_cmd_run(args))
    ap.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
