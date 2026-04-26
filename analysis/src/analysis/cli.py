"""cli.py — CLI for the analysis phase.

Usage:
    analysis run --transcript PATH --out-dir PATH [--capture-manifest PATH]
                 [--language es] [--llm-provider claude_pool]
                 [--llm-model sonnet] [--no-sources] [--dry-run]

--dry-run: prints the prompt and exits without calling the LLM.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    from .prompts import build_analysis_prompt
    import json

    transcript_path = Path(args.transcript)
    out_dir = Path(args.out_dir)
    capture_manifest_path = Path(args.capture_manifest) if args.capture_manifest else None

    if not transcript_path.exists():
        print(f"ERROR: transcript not found: {transcript_path}", file=sys.stderr)
        return 1

    if args.dry_run:
        # Load transcript and sources, build prompt, print and exit
        transcript_data = json.loads(transcript_path.read_text(encoding="utf-8"))
        segments = transcript_data.get("segments", [])
        duration_s = float(transcript_data.get("duration_s", 0.0))
        language = transcript_data.get("language", args.language)

        sources = []
        if capture_manifest_path and not args.no_sources:
            from .analyzer import _load_sources
            try:
                sources = _load_sources(capture_manifest_path)
            except Exception as e:
                print(f"WARNING: could not load sources: {e}", file=sys.stderr)

        prompt = build_analysis_prompt(
            transcript_segments=segments,
            duration_s=duration_s,
            language=language,
            sources=sources if sources else None,
        )
        print("=== DRY RUN — PROMPT BELOW ===")
        print(prompt)
        print(f"\n--- Config ---")
        print(f"  language     : {language}")
        print(f"  duration_s   : {duration_s:.1f}s")
        print(f"  segments     : {len(segments)}")
        print(f"  sources      : {len(sources)}")
        print(f"  llm_provider : {args.llm_provider}")
        print(f"  llm_model    : {args.llm_model}")
        return 0

    from .analyzer import run, BlockingValidationError

    overrides = None
    if args.validation_override:
        from .validate import load_overrides
        override_path = Path(args.validation_override)
        if not override_path.exists():
            print(f"ERROR: validation-override not found: {override_path}", file=sys.stderr)
            return 1
        overrides = load_overrides(override_path)

    try:
        result = run(
            transcript_path=transcript_path,
            out_dir=out_dir,
            capture_manifest_path=capture_manifest_path,
            language=args.language,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            no_sources=args.no_sources,
            strict_numeric=args.strict_numeric,
            overrides=overrides,
        )
    except BlockingValidationError as exc:
        print(
            f"\nBLOCKED: {exc}\n"
            f"  unvalidated  : {exc.unvalidated_path}\n"
            f"  report       : {exc.report_path}\n"
            f"  reasons      : {', '.join(exc.blocking_reasons)}\n"
            f"  (analysis.json NOT written; rerun with --no-strict-numeric to "
            f"emit anyway)",
            file=sys.stderr,
        )
        return 2  # exit 2 = blocking validation failure

    narrative = result.narrative
    v = result.validation
    print(f"\nOK {out_dir / 'analysis.json'}")
    print(f"  arc_acts            : {len(narrative.arc_acts)}")
    print(f"  beats               : {len(narrative.beats)}")
    print(f"  topics (main)       : {sum(1 for t in narrative.topics if t.role == 'main')}")
    print(f"  topics (supp)       : {sum(1 for t in narrative.topics if t.role == 'supporting')}")
    print(f"  entities            : {len(narrative.entities)}")
    print(f"  asr_flagged_beats   : {len(v.flagged_beats)}")
    print(f"  entity_patches      : {len(v.entity_patches)}")
    print(f"  source_refs_nullified: {len(v.invalid_source_refs)}")
    print(f"  id_remaps           : {len(v.id_remaps)}")
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ap = argparse.ArgumentParser(
        prog="analysis",
        description="myavatar v6 — editorial analysis phase",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run analysis on a polished transcript")
    run_p.add_argument("--transcript", required=True, help="Path to transcript_polished.json")
    run_p.add_argument("--out-dir", required=True, dest="out_dir",
                       help="Output directory (analysis.json + progress.jsonl)")
    run_p.add_argument("--capture-manifest", dest="capture_manifest", default=None,
                       help="Path to capture_manifest.json (optional, for source context)")
    run_p.add_argument("--language", default="auto",
                       help="Language code or 'auto' (default). 'auto' picks the "
                            "ISO code from transcript.language; if missing, falls "
                            "back to 'es'. Pass an explicit code only to override.")
    run_p.add_argument("--llm-provider", dest="llm_provider", default="deepseek",
                       choices=["claude_pool", "anthropic_api", "gemini", "openai", "deepseek"],
                       help="LLM provider (default: deepseek — fastest, equivalent quality to claude sonnet)")
    run_p.add_argument("--llm-model", dest="llm_model", default="deepseek-v4-flash",
                       help="Model name within provider (default: deepseek-v4-flash)")
    run_p.add_argument("--no-sources", dest="no_sources", action="store_true",
                       help="Ignore source context even if capture manifest is provided")
    run_p.add_argument("--no-strict-numeric", dest="strict_numeric",
                       action="store_false", default=True,
                       help="Demote numeric_conflict from blocking to warning (debug/CI only)")
    run_p.add_argument("--validation-override", dest="validation_override",
                       default=None,
                       help="Path to JSON file with {'overrides':[...]} of human-resolved findings")
    run_p.add_argument("--dry-run", dest="dry_run", action="store_true",
                       help="Print the prompt and exit without calling the LLM")

    args = ap.parse_args(argv)

    if args.command == "run":
        sys.exit(_cmd_run(args))
    else:
        ap.print_help()
        sys.exit(1)
