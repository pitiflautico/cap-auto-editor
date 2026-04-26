"""capture CLI.

`capture run --sources <path> --out <dir>` captures every URL in the
sources file and writes a CaptureManifest to ``out/capture_manifest.json``.

Use ``--dry-run`` to only emit the planned slugs without running any
backend — handy for QA.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from capture import __version__
from capture.contracts import CaptureManifest, CaptureRequest, CaptureResult
from capture.orchestrator import Orchestrator
from progress import ProgressEmitter
from capture.url_normalizer import derive_slug, normalize_url


def _read_sources(sources_file: Path) -> list[str]:
    urls: list[str] = []
    for raw in sources_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def _build_requests(urls: list[str]) -> list[CaptureRequest]:
    seen_slugs: dict[str, int] = {}
    requests: list[CaptureRequest] = []
    for i, url in enumerate(urls):
        norm = normalize_url(url)
        base_slug = derive_slug(norm)
        n = seen_slugs.get(base_slug, 0)
        slug = base_slug if n == 0 else f"{base_slug}-{n + 1}"
        seen_slugs[base_slug] = n + 1
        requests.append(CaptureRequest(
            url=url,
            normalized_url=norm,
            slug=slug,
            priority=i,
        ))
    return requests


def _dry_run_results(requests: list[CaptureRequest]) -> list[CaptureResult]:
    now = datetime.now(timezone.utc)
    return [
        CaptureResult(
            request=req,
            status="failed",
            backend="browser_sdk",
            captured_at=now,
            duration_ms=0,
            attempts=0,
            error="dry-run: no backend executed",
            error_class="unknown",
        )
        for req in requests
    ]


def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.sources:
        sources_file = Path(args.sources).expanduser().resolve()
        urls = _read_sources(sources_file)
    else:
        # No sources provided: emit an empty manifest so downstream phases
        # (polish/analysis) can proceed without web grounding.
        sources_file = None
        urls = []
    requests = _build_requests(urls)

    if args.dry_run:
        manifest = CaptureManifest(
            created_at=datetime.now(timezone.utc),
            sources_file=str(sources_file) if sources_file else "",
            out_dir=str(out_dir),
            backend_default="browser_sdk",
            config_snapshot={
                "capture_version": __version__,
                "dry_run": True,
            },
            results=_dry_run_results(requests),
        )
    else:
        progress = ProgressEmitter(out_dir / "progress.jsonl")
        orch = Orchestrator.build_default(
            out_dir=out_dir,
            profile=args.profile,
            viewport_w=args.viewport_w,
            viewport_h=args.viewport_h,
            save_raw_html=args.save_raw_html,
            progress=progress,
        )
        results = orch.run(requests)
        manifest = orch.build_manifest(
            results,
            sources_file=str(sources_file) if sources_file else "",
            config_snapshot={
                "profile": args.profile,
                "viewport": [args.viewport_w, args.viewport_h],
                "save_raw_html": args.save_raw_html,
            },
        )

    manifest_path = out_dir / "capture_manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )

    ok = sum(1 for r in manifest.results if r.status == "ok")
    failed = sum(1 for r in manifest.results if r.status == "failed")
    cached = sum(1 for r in manifest.results if r.status == "skipped_cache")

    print(f"wrote {manifest_path}")
    print(f"  urls: {len(urls)}")
    print(f"  ok: {ok}  failed: {failed}  cached: {cached}")
    if args.dry_run:
        for r in requests:
            print(f"  - {r.slug}  ←  {r.normalized_url}")
    else:
        for r in manifest.results:
            marker = "+" if r.status == "ok" else ("~" if r.status == "skipped_cache" else "-")
            extra = ""
            if r.status == "failed":
                extra = f"  [{r.error_class}] {r.error}"
            print(f"  {marker} {r.request.slug}  ({r.backend}){extra}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="capture",
        description="Phase -1 of myavatar v6 — capture source URLs.",
    )
    parser.add_argument("-V", "--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Capture URLs listed in a file.")
    run.add_argument("--sources", default=None,
                     help="Path to .txt with URLs (optional — if absent, manifest is empty).")
    run.add_argument("--out", required=True, help="Output directory.")
    run.add_argument(
        "--backend",
        default="browser_sdk",
        choices=["browser_sdk", "mcp_stdio", "claude_orchestrated", "auto"],
    )
    run.add_argument("--profile", default="default", help="Browser profile.")
    run.add_argument("--viewport-w", dest="viewport_w", type=int, default=1280)
    run.add_argument("--viewport-h", dest="viewport_h", type=int, default=1600)
    run.add_argument("--save-raw-html", dest="save_raw_html", action="store_true")
    run.add_argument("--cache", action="store_true", default=True)
    run.add_argument("--no-cache", dest="cache", action="store_false")
    run.add_argument("--verbose", "-v", action="store_true")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Emit a manifest with planned slugs without running any backend.",
    )
    run.set_defaults(func=_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
