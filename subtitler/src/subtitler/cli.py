"""CLI for the subtitler phase."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    from progress import NullEmitter, ProgressEmitter
    from .builder import build_clips, render_ass, render_srt

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl"
    )
    emitter.emit_run_start(phase="subtitler", total_steps=3)

    # Step 1: load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=3, name="load",
                            detail="reading polished transcript")
    tp_path = Path(args.transcript)
    if not tp_path.exists():
        print(f"ERROR: transcript not found: {tp_path}", file=sys.stderr)
        emitter.emit_run_done(ok=False, summary={"error": "transcript_not_found"})
        return 1
    transcript = json.loads(tp_path.read_text(encoding="utf-8"))
    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"segments": len(transcript.get("segments") or []),
                 "language": transcript.get("language")},
    )

    # Step 2: build clips
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=3, name="build",
                            detail="flattening words → cues")
    clips = build_clips(transcript)
    emitter.emit_step_done(
        index=2, name="build",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"clips": len(clips.clips), "notes": len(clips.notes)},
    )

    # Step 3: render
    t0 = time.monotonic()
    emitter.emit_step_start(index=3, total=3, name="render",
                            detail="writing srt+ass+json")
    srt_path = out_dir / "subtitles.srt"
    ass_path = out_dir / "subtitles.ass"
    json_path = out_dir / "subtitle_clips.json"
    srt_path.write_text(render_srt(clips), encoding="utf-8")
    ass_path.write_text(render_ass(clips), encoding="utf-8")
    json_path.write_text(clips.model_dump_json(indent=2), encoding="utf-8")
    emitter.emit_step_done(
        index=3, name="render",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"srt_bytes": srt_path.stat().st_size,
                 "ass_bytes": ass_path.stat().st_size,
                 "json_bytes": json_path.stat().st_size},
    )

    print(f"OK {json_path}")
    print(f"  language    : {clips.language}")
    print(f"  duration    : {clips.duration_s:.2f}s")
    print(f"  clips       : {len(clips.clips)}")
    if clips.notes:
        print(f"  notes       : {len(clips.notes)}")

    emitter.emit_run_done(ok=True, summary={"clips": len(clips.clips)})
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(prog="subtitler",
                                 description="myavatar v6 — word-by-word subtitles")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Generate subtitles from a polished transcript")
    run_p.add_argument("--transcript", required=True,
                       help="Path to transcript_polished.json")
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
