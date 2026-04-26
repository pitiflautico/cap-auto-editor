"""pipeline CLI — `pipeline run`, `pipeline list`, `pipeline show`."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _default_run_name() -> str:
    return "run_" + datetime.now(tz=timezone.utc).strftime("%y%m%d_%H%M%S")


def _discover_runs(out_root: Path) -> list[Path]:
    """Find run dirs (those with pipeline_manifest.json)."""
    return sorted(out_root.glob("*/pipeline_manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def cmd_run(args) -> None:
    from pipeline import orchestrator

    video = Path(args.video).resolve() if args.video else None
    sources = Path(args.sources).resolve() if args.sources else None
    out_root = Path(args.out_root).resolve()
    run_name = args.name or _default_run_name()
    run_dir = out_root / run_name

    if run_dir.exists() and not getattr(args, "force", False):
        print(f"[pipeline] Error: run_dir already exists: {run_dir}", file=sys.stderr)
        print("[pipeline] Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    run_dir.mkdir(parents=True, exist_ok=True)

    phases_filter = None
    if args.phases:
        phases_filter = [p.strip() for p in args.phases.split(",")]

    # Start viewer unless --no-open
    port = args.port
    if not args.no_open:
        try:
            from viewer.launcher import open_pipeline
            open_pipeline(run_name, port=port)
        except Exception as exc:
            print(f"[pipeline] Warning: could not open viewer: {exc}", file=sys.stderr)
    else:
        # Still ensure viewer is running (no browser open)
        try:
            from viewer.launcher import ensure_running
            ensure_running(port=port)
        except Exception as exc:
            print(f"[pipeline] Warning: could not start viewer: {exc}", file=sys.stderr)

    result = orchestrator.run(
        run_dir=run_dir,
        run_name=run_name,
        video=video,
        sources=sources,
        phases_filter=phases_filter,
    )

    if result.ok:
        print(f"[pipeline] Run complete: {run_dir}")
    else:
        failed = [p.name for p in result.phases if not p.ok]
        print(f"[pipeline] Run finished with failures: {failed}", file=sys.stderr)
        sys.exit(1)


def cmd_list(args) -> None:
    out_root = Path(args.out_root).resolve()
    manifests = _discover_runs(out_root)
    if not manifests:
        print("No pipeline runs found under", out_root)
        return
    for mf in manifests:
        run_dir = mf.parent
        try:
            data = json.loads(mf.read_text())
            created = data.get("created_at", "?")[:19]
            phases = [p["name"] for p in data.get("phases", [])]
            print(f"  {run_dir.name}  {created}  phases={phases}")
        except Exception:
            print(f"  {run_dir.name}  (manifest unreadable)")


def cmd_show(args) -> None:
    out_root = Path(args.out_root).resolve()
    run_dir = out_root / args.run_name
    if not run_dir.exists():
        print(f"Run not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    tracer_path = run_dir / "orchestrator.jsonl"
    if tracer_path.exists():
        print("=== orchestrator.jsonl ===")
        print(tracer_path.read_text())
    else:
        print("(no orchestrator.jsonl)")

    # Per-phase summary
    mf_path = run_dir / "pipeline_manifest.json"
    if mf_path.exists():
        data = json.loads(mf_path.read_text())
        for ph in data.get("phases", []):
            phase_dir = run_dir / ph["out_subdir"]
            stdout_log = phase_dir / "stdout.log"
            stderr_log = phase_dir / "stderr.log"
            print(f"\n=== Phase: {ph['name']} ===")
            if stdout_log.exists():
                print("--- stdout (tail 20) ---")
                lines = stdout_log.read_text().splitlines()
                print("\n".join(lines[-20:]))
            if stderr_log.exists():
                stderr_lines = stderr_log.read_text().splitlines()
                if stderr_lines:
                    print("--- stderr (tail 10) ---")
                    print("\n".join(stderr_lines[-10:]))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="pipeline", description="myavatar v6 pipeline orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    # pipeline run
    p_run = sub.add_parser("run", help="Execute the full pipeline")
    p_run.add_argument("--video", required=False, help="Path to input video (.webm/.mp4)")
    p_run.add_argument("--sources", required=False, help="Path to sources.txt (one URL per line)")
    p_run.add_argument("--out-root",
                       default=os.environ.get("MYAVATAR_RUNS",
                                              str(Path.home() / "myavatar" / "runs")),
                       help="Root directory for run dirs (default: $MYAVATAR_RUNS or ~/myavatar/runs)")
    p_run.add_argument("--name", default=None, help="Run name (default: run_<timestamp>)")
    p_run.add_argument("--phases", default=None, help="Comma-separated phase names to run")
    p_run.add_argument("--no-open", action="store_true", help="Do not open browser")
    p_run.add_argument("--port", type=int, default=8765, help="Viewer port")
    p_run.add_argument("--force", action="store_true", help="Overwrite existing run dir")
    p_run.set_defaults(func=cmd_run)

    # pipeline list
    p_list = sub.add_parser("list", help="List pipeline runs")
    p_list.add_argument("--out-root",
                        default=os.environ.get("MYAVATAR_RUNS",
                                               str(Path.home() / "myavatar" / "runs")),
                        help="Root directory to scan")
    p_list.set_defaults(func=cmd_list)

    # pipeline show
    p_show = sub.add_parser("show", help="Show a specific run")
    p_show.add_argument("run_name", help="Run name")
    p_show.add_argument("--out-root",
                        default=os.environ.get("MYAVATAR_RUNS",
                                               str(Path.home() / "myavatar" / "runs")),
                        help="Root directory")
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
