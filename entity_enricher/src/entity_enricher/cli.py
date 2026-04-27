"""CLI for entity_enricher.

Usage:
    entity-enricher run \\
        --analysis  /path/to/analysis.json \\
        --capture-manifest /path/to/capture_manifest.json \\
        --out-dir   /path/to/out

Outputs:
    out-dir/analysis_enriched.json
    out-dir/analysis_enrichment_report.json
    out-dir/progress.jsonl

Exit codes:
    0  ok
    1  IO/runtime error
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path


def _gather_sources_urls(capture_manifest_path: Path | None) -> list[str]:
    if capture_manifest_path is None or not capture_manifest_path.exists():
        return []
    try:
        manifest = json.loads(capture_manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    urls: list[str] = []
    for r in manifest.get("results", []):
        req = r.get("request", {})
        url = req.get("normalized_url") or req.get("url")
        if url:
            urls.append(url)
    return urls


def _cmd_run(args: argparse.Namespace) -> int:
    from analysis.contracts import AnalysisResult
    from progress import NullEmitter, ProgressEmitter

    from .enricher import enrich_entities

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    emitter = NullEmitter() if args.no_progress else ProgressEmitter(
        out_dir / "progress.jsonl"
    )
    emitter.emit_run_start(phase="entity_enricher", total_steps=2)

    # Step 1: load
    t0 = time.monotonic()
    emitter.emit_step_start(index=1, total=2, name="load",
                            detail="reading analysis + sources")
    analysis_path = Path(args.analysis)
    if not analysis_path.exists():
        print(f"ERROR: analysis not found: {analysis_path}", file=sys.stderr)
        return 1
    raw = json.loads(analysis_path.read_text(encoding="utf-8"))
    analysis = AnalysisResult.model_validate(raw)
    capture_path = Path(args.capture_manifest) if args.capture_manifest else None
    sources_urls = _gather_sources_urls(capture_path)
    emitter.emit_step_done(
        index=1, name="load",
        duration_ms=int((time.monotonic() - t0) * 1000),
        summary={"entities": len(analysis.narrative.entities),
                 "sources_urls": len(sources_urls)},
    )

    # Step 2: enrich
    t0 = time.monotonic()
    emitter.emit_step_start(index=2, total=2, name="enrich",
                            detail="resolving handles per entity")
    use_browser = not args.no_browser
    enriched, report = enrich_entities(
        analysis,
        sources_urls,
        use_browser=use_browser,
    )
    enrich_ms = int((time.monotonic() - t0) * 1000)
    emitter.emit_step_done(
        index=2, name="enrich", duration_ms=enrich_ms,
        summary={
            "entities_enriched": report.entities_enriched,
            "handles_added": report.handles_added,
            "from_sources": report.handles_from_sources,
            "from_browser": report.handles_from_browser,
            "from_cache": report.handles_from_cache,
        },
    )

    # Outputs
    (out_dir / "analysis_enriched.json").write_text(
        enriched.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )
    (out_dir / "analysis_enrichment_report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )

    print(f"OK {out_dir / 'analysis_enriched.json'}")
    print(f"  entities         : {report.entities_total}")
    print(f"  enriched         : {report.entities_enriched}")
    print(f"  handles total    : {report.handles_added}")
    print(f"    from sources   : {report.handles_from_sources}")
    print(f"    from browser   : {report.handles_from_browser}")
    print(f"    from cache     : {report.handles_from_cache}")
    if report.skipped_entities:
        print(f"  skipped (kind)   : {len(report.skipped_entities)}")
    if report.errors:
        print(f"  errors           : {len(report.errors)}")

    emitter.emit_run_done(
        ok=True,
        summary={"entities_enriched": report.entities_enriched,
                 "handles_added": report.handles_added},
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(prog="entity-enricher",
                                 description="myavatar v6 — entity enrichment phase")
    sub = ap.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run enrichment on an analysis.json")
    run_p.add_argument("--analysis", required=True,
                       help="Path to analysis.json (output of analysis phase)")
    run_p.add_argument("--capture-manifest", dest="capture_manifest", default=None,
                       help="Path to capture_manifest.json (used to derive handles "
                            "from --sources URLs)")
    run_p.add_argument("--out-dir", dest="out_dir", required=True,
                       help="Output directory")
    run_p.add_argument("--no-browser", dest="no_browser", action="store_true",
                       help="Skip browser lookup (sources + cache only)")
    run_p.add_argument("--no-progress", dest="no_progress", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "run":
        sys.exit(_cmd_run(args))
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
