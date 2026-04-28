"""CLI for hf_designer: design + render a single card from a brief.

Examples:

    hf-designer run --kind slide --brief "$4 million in 24 hours" \\
                    --layout fullscreen --duration 5 --out /tmp/card.mp4

    hf-designer run --kind mockup --brief "It hit GitHub trending in days" \\
                    --kind mockup --duration 4 --out /tmp/quote.mp4 \\
                    --save-html /tmp/quote.html
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    from .designer import design
    from .render import render_to_mp4

    palette = json.loads(args.palette) if args.palette else None

    t0 = time.monotonic()
    try:
        html = design(
            brief=args.brief, kind=args.kind,
            layout=args.layout, duration_s=args.duration,
            palette=palette,
            model=args.model,
            timeout_s=args.timeout,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: design failed — {exc}", file=sys.stderr)
        return 1
    print(f"  designer HTML: {len(html)} chars in {time.monotonic() - t0:.1f}s",
          file=sys.stderr)

    if args.save_html:
        args.save_html.parent.mkdir(parents=True, exist_ok=True)
        args.save_html.write_text(html, encoding="utf-8")
        print(f"  HTML → {args.save_html}", file=sys.stderr)

    t1 = time.monotonic()
    res = render_to_mp4(html, args.out, duration_s=args.duration,
                         fps=args.fps, quality=args.quality)
    print(f"  hyperframes render {res['status']} in {time.monotonic() - t1:.1f}s",
          file=sys.stderr)
    if res["status"] != "ok":
        print(f"ERROR: render failed — {res.get('message')}", file=sys.stderr)
        return 1

    if args.frame:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", "2",
             "-i", str(args.out), "-vframes", "1", str(args.frame)],
            check=False,
        )

    print(f"OK {args.out}")
    print(f"  duration : {res['duration_s']:.2f}s")
    print(f"  sha256   : {res['sha256'][:16]}…")
    if args.frame:
        print(f"  frame    : {args.frame}")
    if args.save_html:
        print(f"  html     : {args.save_html}")
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(prog="hf-designer",
                                 description="myavatar v6 — slide / mockup designer + HF render")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="Design + render one card")
    run_p.add_argument("--kind", choices=["slide", "mockup"], required=True)
    run_p.add_argument("--brief", required=True,
                       help="Free-text describing what the card should show")
    run_p.add_argument("--layout", default="fullscreen",
                       choices=["fullscreen", "split_top", "split_bottom"])
    run_p.add_argument("--duration", type=float, default=6.0)
    run_p.add_argument("--out", type=Path, required=True,
                       help="MP4 output path")
    run_p.add_argument("--save-html", dest="save_html", type=Path, default=None,
                       help="Also save the raw HTML for inspection")
    run_p.add_argument("--frame", type=Path, default=None,
                       help="If set, extract a still PNG at t=2s from the MP4")
    run_p.add_argument("--model", default="sonnet")
    run_p.add_argument("--fps", type=int, default=24)
    run_p.add_argument("--quality", default="draft", choices=["draft", "high"])
    run_p.add_argument("--timeout", type=int, default=240)
    run_p.add_argument("--palette", default=None,
                       help="JSON dict palette override (bg/fg/accent/subtle)")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        sys.exit(_cmd_run(args))
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
