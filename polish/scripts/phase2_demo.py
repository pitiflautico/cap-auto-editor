"""End-to-end Phase 2 demo: video → transcript → detectors → plan → remap.

Runs the deterministic pipeline (no LLMs yet, Phase 4 adds those).
Dumps canonical-ish JSONs to --out-dir for inspection.

Usage:
    python scripts/phase2_demo.py \\
        --audio /path/to/audio.wav \\
        --out-dir /path/to/out \\
        --initial-prompt "Optional bias text for the Whisper decoder"
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from polish.contracts import CutRegion, KeepSegment, TimelineMap
from polish.cut_planner import plan_cuts
from polish.detectors.filler import detect_fillers
from polish.detectors.silence import detect_silences
from polish.remap import remap_transcript
from polish.transcribe import transcribe


DEFAULT_FILLERS = [
    "eh", "um", "este", "osea", "o sea", "pues", "vale",
    "como que", "tipo", "sabes", "digamos",
]


def _build_keeps_from_cuts(
    cuts: list[CutRegion],
    total_duration_s: float,
) -> tuple[list[KeepSegment], float]:
    """Derive keep segments from sorted cuts. Returns (keeps, edited_duration)."""
    cut_ids_acc: list[str] = []
    keeps: list[KeepSegment] = []
    edited_cursor = 0.0
    original_cursor = 0.0

    for c in sorted(cuts, key=lambda x: x.start_s):
        if c.start_s > original_cursor:
            span = c.start_s - original_cursor
            keeps.append(
                KeepSegment(
                    original_start_s=original_cursor,
                    original_end_s=c.start_s,
                    edited_start_s=edited_cursor,
                    edited_end_s=edited_cursor + span,
                    source_cut_ids_before=list(cut_ids_acc),
                )
            )
            edited_cursor += span
        original_cursor = max(original_cursor, c.end_s)
        cut_ids_acc.append(c.id)

    # Tail segment after the last cut
    if original_cursor < total_duration_s:
        span = total_duration_s - original_cursor
        keeps.append(
            KeepSegment(
                original_start_s=original_cursor,
                original_end_s=total_duration_s,
                edited_start_s=edited_cursor,
                edited_end_s=edited_cursor + span,
                source_cut_ids_before=list(cut_ids_acc),
            )
        )
        edited_cursor += span

    return keeps, edited_cursor


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--initial-prompt", default=None)
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--language", default="es")
    ap.add_argument("--silence-threshold-db", type=float, default=-30.0)
    ap.add_argument("--silence-min-s", type=float, default=0.4)
    ap.add_argument("--fillers", nargs="*", default=DEFAULT_FILLERS)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Transcribe ────────────────────────────────────────────────
    print(f"[1/5] Transcribing {args.audio} with mlx-whisper {args.model}…")
    t0 = time.monotonic()
    transcript = transcribe(
        args.audio,
        model=args.model,
        language=args.language,
        initial_prompt=args.initial_prompt,
    )
    t1 = time.monotonic() - t0
    print(f"      → {len(transcript.segments)} segments, "
          f"{sum(len(s.words) for s in transcript.segments)} words, "
          f"duration {transcript.duration_s:.1f}s ({t1:.1f}s)")
    (args.out_dir / "transcript_raw.json").write_text(
        transcript.model_dump_json(indent=2), encoding="utf-8"
    )

    # ── 2. Silence detection ─────────────────────────────────────────
    print("[2/5] Running ffmpeg silencedetect…")
    t0 = time.monotonic()
    silences = detect_silences(
        args.audio,
        threshold_db=args.silence_threshold_db,
        min_duration_s=args.silence_min_s,
    )
    t1 = time.monotonic() - t0
    print(f"      → {len(silences)} silence candidates ({t1:.1f}s)")

    # ── 3. Filler detection ──────────────────────────────────────────
    print("[3/5] Running filler detector on transcript…")
    t0 = time.monotonic()
    fillers = detect_fillers(transcript, filler_words=args.fillers)
    t1 = time.monotonic() - t0
    print(f"      → {len(fillers)} filler candidates ({t1:.1f}s)")

    # ── 4. Plan cuts ─────────────────────────────────────────────────
    print("[4/5] Planning cuts (padding + merge)…")
    t0 = time.monotonic()
    all_candidates = silences + fillers
    planned = plan_cuts(all_candidates)
    active = [c for c in planned if c.action == "cut"]
    t1 = time.monotonic() - t0
    print(f"      → {len(planned)} regions after merge, "
          f"{len(active)} active cuts ({t1:.1f}s)")

    # ── 5. Build timeline_map + remap ────────────────────────────────
    print("[5/5] Building timeline_map + remap…")
    t0 = time.monotonic()
    keeps, edited_dur = _build_keeps_from_cuts(active, transcript.duration_s)

    timeline_map = TimelineMap(
        created_at=datetime.now(),
        source_video_path=str(args.audio),
        transcript_original_ref=str(args.out_dir / "transcript_raw.json"),
        sources_used=[],
        detector_versions={
            "ffmpeg_silencedetect": "1.0.0",
            "filler_es": "1.0.0",
        },
        cut_regions=planned,
        keep_segments=keeps,
        total_original_duration_s=transcript.duration_s,
        total_edited_duration_s=edited_dur,
    )
    transcript_polished = remap_transcript(transcript, timeline_map)
    t1 = time.monotonic() - t0
    print(f"      → edited duration {edited_dur:.1f}s "
          f"(saved {transcript.duration_s - edited_dur:.1f}s, "
          f"{100 * (1 - edited_dur / transcript.duration_s):.1f}%) ({t1:.1f}s)")

    (args.out_dir / "timeline_map.json").write_text(
        timeline_map.model_dump_json(indent=2), encoding="utf-8"
    )
    (args.out_dir / "transcript_polished.json").write_text(
        transcript_polished.model_dump_json(indent=2), encoding="utf-8"
    )

    # ── Summary ──────────────────────────────────────────────────────
    summary = {
        "original_duration_s": transcript.duration_s,
        "edited_duration_s": edited_dur,
        "time_saved_s": transcript.duration_s - edited_dur,
        "pct_saved": 100 * (1 - edited_dur / transcript.duration_s),
        "silences_detected": len(silences),
        "fillers_detected": len(fillers),
        "regions_after_merge": len(planned),
        "active_cuts": len(active),
        "words_raw": sum(len(s.words) for s in transcript.segments),
        "words_polished": sum(len(s.words) for s in transcript_polished.segments),
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print("\n=== Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\nArtefactos: {args.out_dir}/")


if __name__ == "__main__":
    main()
