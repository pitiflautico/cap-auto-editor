"""End-to-end Phase 2b demo — v2.2.

Chains: transcribe → text_normalizer → entity_candidates → entity_resolution
→ silences (adaptive) → cuts → timeline.

Step count: 7 (project_aliases dropped from demo — deprecated v2.2; entity_resolution added).

# project_aliases path deprecated v2.2; entity resolution via LLM supersedes it.
# The --project-aliases CLI flag is still accepted as a no-op for backwards compat
# (other callers may import apply_project_aliases directly — the code is retained).

Usage:
    python scripts/phase2b_demo.py \\
        --audio /tmp/top2_audio.wav \\
        --out-dir /tmp/top2_polish_v2 \\
        [--capture-manifest /tmp/live_demo/capture/capture_manifest.json]
"""
from __future__ import annotations

import argparse
import json
import time
import warnings
from datetime import datetime
from pathlib import Path

from polish.contracts import KeepSegment, TimelineMap
from progress import NullEmitter, ProgressEmitter
from polish.sources import extract_entity_hints, load_from_capture_manifest
from polish.cut_planner import plan_cuts
from polish.detectors.filler import detect_fillers
from polish.detectors.silence import detect_silences
from polish.entity_candidates import detect_entity_candidates
from polish.entity_resolution import resolve_entities
from polish.project_aliases import apply_project_aliases, load_project_aliases  # retained, not called
from polish.remap import remap_transcript
from polish.text_normalizer import load_rules, normalize_transcript
from polish.transcribe import build_initial_prompt, transcribe
from polish.transcript_patches import collect, summarise_by_layer


DEFAULT_FILLERS = [
    "eh", "um", "este", "osea", "o sea", "pues", "vale",
    "como que", "tipo", "sabes", "digamos",
]

TOTAL_STEPS = 7


def _build_keeps_from_cuts(cuts, total_duration_s):
    cut_ids_acc = []
    keeps = []
    edited_cursor = 0.0
    original_cursor = 0.0
    for c in sorted(cuts, key=lambda x: x.start_s):
        if c.start_s > original_cursor:
            span = c.start_s - original_cursor
            keeps.append(KeepSegment(
                original_start_s=original_cursor,
                original_end_s=c.start_s,
                edited_start_s=edited_cursor,
                edited_end_s=edited_cursor + span,
                source_cut_ids_before=list(cut_ids_acc),
            ))
            edited_cursor += span
        original_cursor = max(original_cursor, c.end_s)
        cut_ids_acc.append(c.id)
    if original_cursor < total_duration_s:
        span = total_duration_s - original_cursor
        keeps.append(KeepSegment(
            original_start_s=original_cursor,
            original_end_s=total_duration_s,
            edited_start_s=edited_cursor,
            edited_end_s=edited_cursor + span,
            source_cut_ids_before=list(cut_ids_acc),
        ))
        edited_cursor += span
    return keeps, edited_cursor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--project-aliases", type=Path, default=None,
                    help="DEPRECATED v2.2 — no-op. Entity resolution via LLM supersedes this.")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--language", default="auto",
                    help="ISO code (es/en/...) or 'auto' to let whisper detect. "
                         "Forcing the wrong code makes whisper pseudo-translate.")
    ap.add_argument("--silence-threshold-db", type=float, default=-30.0,
                    help="Threshold for fixed silence mode. Not used in adaptive mode.")
    ap.add_argument("--silence-min-s", type=float, default=0.5,
                    help="Min silence duration (adaptive mode). Default 0.5s.")
    ap.add_argument("--silence-mode", default="adaptive", choices=["adaptive", "fixed"],
                    help="Silence detection mode. Default: adaptive (loudnorm-calibrated).")
    ap.add_argument("--capture-manifest", type=Path, default=None,
                    metavar="PATH",
                    help="Path to capture manifest JSON from v6/capture/. "
                         "Provides source text context for LLM entity resolution.")
    ap.add_argument("--no-progress", action="store_true",
                    help="Disable progress JSONL emission (swaps in NullEmitter).")
    ap.add_argument("--skip-entity-resolution", action="store_true",
                    help="Skip LLM entity resolution step (useful for offline testing).")
    args = ap.parse_args()

    # Deprecation warning for project_aliases
    if args.project_aliases is not None:
        warnings.warn(
            "--project-aliases is deprecated in v2.2 and is a no-op. "
            "Entity resolution via LLM (entity_resolution.py) supersedes it. "
            "The project_aliases.py module is retained for direct import callers.",
            DeprecationWarning,
            stacklevel=1,
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parents[1]

    # ── Progress emitter ─────────────────────────────────────────────
    if args.no_progress:
        emitter = NullEmitter()
    else:
        emitter = ProgressEmitter(args.out_dir / "progress.jsonl")
    emitter.emit_run_start(phase="polish", total_steps=TOTAL_STEPS)

    # ── 0. Load capture manifest (opt-in) ────────────────────────────
    entity_hints: list[str] = []
    if args.capture_manifest:
        metas = load_from_capture_manifest(args.capture_manifest)
        entity_hints = extract_entity_hints(metas)
        print(f"[0/{TOTAL_STEPS}] Loaded {len(metas)} sources from capture manifest")
        print(f"      entity_hints ({len(entity_hints)}): {entity_hints}")

    # ── 1. Transcribe ─────────────────────────────────────────────────
    emitter.emit_step_start(index=1, total=TOTAL_STEPS, name="transcribe",
                           detail=f"running whisper on {args.audio.name}")
    # 'auto' / falsy → let whisper detect language. Initial_prompt is also
    # skipped in auto mode: a Spanish-biased prompt was making whisper
    # pseudo-translate English audio (e.g. "spawna miles de agentes").
    transcribe_lang: str | None = None if (not args.language or args.language == "auto") else args.language
    prompt = (
        build_initial_prompt(language=transcribe_lang, entity_hints=entity_hints or None)
        if transcribe_lang else None
    )
    print(f"[1/{TOTAL_STEPS}] Transcribing"
          f" (lang={'auto-detect' if transcribe_lang is None else transcribe_lang}"
          f"{', with entity hints' if entity_hints and prompt else ''}):")
    if prompt:
        print(f"      «{prompt}»")
    t0 = time.monotonic()
    transcript_raw = transcribe(
        args.audio,
        model=args.model,
        language=transcribe_lang,
        initial_prompt=prompt,
    )
    t1 = time.monotonic() - t0
    n_words = sum(len(s.words) for s in transcript_raw.segments)
    print(f"      → lang={transcript_raw.language!r}  "
          f"{len(transcript_raw.segments)} segments / {n_words} words "
          f"/ {transcript_raw.duration_s:.1f}s ({t1:.1f}s)")
    (args.out_dir / "transcript_raw.json").write_text(
        transcript_raw.model_dump_json(indent=2), encoding="utf-8"
    )
    emitter.emit_step_done(index=1, name="transcribe",
                          duration_ms=round(t1 * 1000),
                          summary={"segments": len(transcript_raw.segments),
                                   "words": n_words,
                                   "duration_s": round(transcript_raw.duration_s, 2)})

    # ── 2. Text normaliser ───────────────────────────────────────────
    emitter.emit_step_start(index=2, total=TOTAL_STEPS, name="normalize",
                           detail="applying universal normalizer")
    _t2 = time.monotonic()
    print(f"[2/{TOTAL_STEPS}] Applying universal text normalizer…")
    rules = load_rules(project_root / "text_normalization_rules.yaml")
    transcript_norm, norm_patches = normalize_transcript(transcript_raw, rules)
    _norm_occurrences = sum(p.occurrences for p in norm_patches)
    print(f"      → {len(norm_patches)} normalisation patches "
          f"({_norm_occurrences} total occurrences)")
    emitter.emit_step_done(index=2, name="normalize",
                          duration_ms=round((time.monotonic() - _t2) * 1000),
                          summary={"patches": len(norm_patches),
                                   "occurrences": _norm_occurrences})

    # ── 3. Entity candidates ─────────────────────────────────────────
    emitter.emit_step_start(index=3, total=TOTAL_STEPS, name="entity_candidates",
                           detail="scanning transcript")
    _t3 = time.monotonic()
    print(f"[3/{TOTAL_STEPS}] Detecting entity candidates…")
    candidates = detect_entity_candidates(transcript_norm)
    print(f"      → {len(candidates)} candidates detected")
    cand_dump = [
        {
            "surface_form": c.surface_form,
            "occurrences": c.occurrences,
            "first_time_s": round(c.first_time_s, 2),
            "evidence": sorted(c.evidence_types),
            "positions": c.positions,
        }
        for c in candidates
    ]
    (args.out_dir / "entity_candidates.json").write_text(
        json.dumps({"candidates": cand_dump}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    emitter.emit_step_done(index=3, name="entity_candidates",
                          duration_ms=round((time.monotonic() - _t3) * 1000),
                          summary={"count": len(candidates)})

    # ── 4. Entity resolution (LLM) ───────────────────────────────────
    emitter.emit_step_start(index=4, total=TOTAL_STEPS, name="entity_resolution",
                           detail=f"LLM resolving {len(candidates)} candidates")
    _t4 = time.monotonic()
    llm_patches: list = []
    entity_resolutions_raw: list = []
    transcript_resolved = transcript_norm
    llm_alias_map: dict[str, str] = {}

    if args.skip_entity_resolution:
        print(f"[4/{TOTAL_STEPS}] Entity resolution SKIPPED (--skip-entity-resolution)")
        emitter.emit_step_done(index=4, name="entity_resolution",
                              duration_ms=0,
                              summary={"skipped": True, "canonical": 0, "patches": 0})
    else:
        print(f"[4/{TOTAL_STEPS}] Running LLM entity resolution ({len(candidates)} candidates)…")
        try:
            entity_resolutions, llm_patches, entity_resolutions_raw = resolve_entities(
                transcript_norm,
                candidates,
                capture_manifest_path=args.capture_manifest,
            )
            # Build the alias_map. Patches are applied ONCE, after remap, on
            # the polished transcript — see end of pipeline. Applying both
            # pre- and post-remap caused canonicals that contain their own
            # surface to duplicate ("Chrome" → "Google Chrome" then a second
            # pass yields "Google Google Chrome"). Cut-planner and filler
            # detection do not need canonical spelling.
            if llm_patches:
                llm_alias_map = {p.from_: p.to for p in llm_patches}
                print(f"      → {len(entity_resolutions)} canonical / "
                      f"{len(entity_resolutions_raw) - len(entity_resolutions)} unresolved / "
                      f"{len(llm_patches)} patches applied")
            else:
                print(f"      → 0 patches (all unresolved or no candidates)")

            # Write entity_resolutions.json
            er_dump = {
                "schema_version": "2.2.0",
                "provider": "claude_pool",
                "model": "sonnet",
                "resolutions": entity_resolutions_raw,
                "applied_patches": [
                    {"from": p.from_, "to": p.to, "occurrences": p.occurrences}
                    for p in llm_patches
                ],
            }
            (args.out_dir / "entity_resolutions.json").write_text(
                json.dumps(er_dump, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            emitter.emit_step_done(index=4, name="entity_resolution",
                                  duration_ms=round((time.monotonic() - _t4) * 1000),
                                  summary={
                                      "candidates": len(candidates),
                                      "canonical": len(entity_resolutions),
                                      "patches": len(llm_patches),
                                  })
        except Exception as exc:
            print(f"      [WARN] LLM entity resolution failed: {exc}")
            print(f"      Continuing with unresolved transcript (no auto-correction applied)")
            # Always write entity_resolutions.json so downstream (analysis,
            # broll_plan) can detect the failure rather than silently consume
            # an unresolved transcript.
            er_dump = {
                "schema_version": "2.2.0",
                "provider": "claude_pool",
                "model": "sonnet",
                "status": "failed",
                "error": str(exc),
                "resolutions": [],
                "applied_patches": [],
            }
            (args.out_dir / "entity_resolutions.json").write_text(
                json.dumps(er_dump, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            emitter.emit_step_done(index=4, name="entity_resolution",
                                  duration_ms=round((time.monotonic() - _t4) * 1000),
                                  summary={"error": str(exc), "canonical": 0, "patches": 0,
                                           "failed": True})

    # Dump combined patches (norm + llm)
    all_patches = norm_patches + llm_patches
    tp = collect(all_patches)
    (args.out_dir / "transcript_patches.json").write_text(
        tp.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )

    # ── 5. Silence detection (adaptive default) ───────────────────────
    emitter.emit_step_start(index=5, total=TOTAL_STEPS, name="silences",
                           detail=f"ffmpeg silencedetect ({args.silence_mode} mode)")
    _t5 = time.monotonic()
    print(f"[5/{TOTAL_STEPS}] Running ffmpeg silencedetect ({args.silence_mode} mode)…")
    silences = detect_silences(
        args.audio,
        mode=args.silence_mode,
        min_duration_s=args.silence_min_s,
        threshold_db=args.silence_threshold_db,
    )
    print(f"      → {len(silences)} silence candidates")
    emitter.emit_step_done(index=5, name="silences",
                          duration_ms=round((time.monotonic() - _t5) * 1000),
                          summary={"count": len(silences), "mode": args.silence_mode})

    # ── 6. Filler detection + cut planning ───────────────────────────
    emitter.emit_step_start(index=6, total=TOTAL_STEPS, name="cuts",
                           detail="planning cuts")
    _t6 = time.monotonic()
    print(f"[6/{TOTAL_STEPS}] Running filler detector + planning cuts…")
    fillers = detect_fillers(transcript_resolved, filler_words=DEFAULT_FILLERS)
    planned = plan_cuts(silences + fillers)
    active = [c for c in planned if c.action == "cut"]
    print(f"      → {len(fillers)} fillers / {len(active)} active cuts")
    emitter.emit_step_done(index=6, name="cuts",
                          duration_ms=round((time.monotonic() - _t6) * 1000),
                          summary={"fillers": len(fillers), "active_cuts": len(active)})

    # ── 7. Build timeline_map + remap ────────────────────────────────
    emitter.emit_step_start(index=7, total=TOTAL_STEPS, name="timeline",
                           detail="remapping transcript")
    _t7 = time.monotonic()
    print(f"[7/{TOTAL_STEPS}] Building timeline_map + remap…")
    keeps, edited_dur = _build_keeps_from_cuts(active, transcript_resolved.duration_s)
    tm = TimelineMap(
        created_at=datetime.now(),
        source_video_path=str(args.audio),
        transcript_original_ref=str(args.out_dir / "transcript_raw.json"),
        sources_used=[],
        detector_versions={
            "ffmpeg_silencedetect": "2.2.0" if args.silence_mode == "adaptive" else "1.0.0",
            "filler_es": "1.0.0",
            "text_normalizer": "1.0.0",
            "entity_resolution_llm": "2.2.0",
        },
        cut_regions=planned,
        keep_segments=keeps,
        total_original_duration_s=transcript_resolved.duration_s,
        total_edited_duration_s=edited_dur,
    )
    transcript_polished = remap_transcript(transcript_resolved, tm)

    # Re-apply LLM patches over the post-remap transcript: remap regenerates
    # seg.text from seg.words, dropping any multi-token canonical we placed
    # earlier ("o llama" → "Ollama", "inteligencia metal" → "Apple
    # Intelligence"). The span-based patcher restores them.
    if llm_alias_map:
        transcript_polished = _apply_llm_patches(transcript_polished, llm_alias_map)

    (args.out_dir / "timeline_map.json").write_text(
        tm.model_dump_json(indent=2), encoding="utf-8"
    )
    (args.out_dir / "transcript_polished.json").write_text(
        transcript_polished.model_dump_json(indent=2), encoding="utf-8"
    )
    _pct_saved = round(100 * (1 - edited_dur / transcript_resolved.duration_s), 2)
    emitter.emit_step_done(index=7, name="timeline",
                          duration_ms=round((time.monotonic() - _t7) * 1000),
                          summary={"cut_regions": len(planned),
                                   "pct_saved": _pct_saved})
    emitter.emit_run_done(
        ok=True,
        summary={
            "edited_s": round(edited_dur, 3),
            "pct_saved": _pct_saved,
            "entity_candidates": len(candidates),
        },
    )

    # ── Summary ──────────────────────────────────────────────────────
    summary = {
        "original_duration_s": transcript_resolved.duration_s,
        "edited_duration_s": edited_dur,
        "pct_saved": _pct_saved,
        "silences_detected": len(silences),
        "silence_mode": args.silence_mode,
        "fillers_detected": len(fillers),
        "active_cuts": len(active),
        "words_raw": n_words,
        "words_polished": sum(len(s.words) for s in transcript_polished.segments),
        "normalisation_patches": len(norm_patches),
        "llm_entity_patches": len(llm_patches),
        "entity_candidates": len(candidates),
        "patches_by_layer": summarise_by_layer(tp),
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("\n=== Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\nArtefactos en: {args.out_dir}/")


def _apply_llm_patches(transcript, alias_map: dict[str, str]):
    """Apply LLM entity-resolution patches with span-based replacement.

    Operates on each segment's full text (not word-by-word) so multi-word
    surfaces — "o llama" → "Ollama", "inteligencia metal" → "Apple
    Intelligence", "google ayer gallery" → "Google AI Edge Gallery" —
    actually match. Word-level matching only catches single-token patches
    and silently drops everything else.

    Algorithm (per segment):
      1. Collect (surface, canonical) pairs sorted longest-first.
      2. Find every regex match (\\bsurface\\b, case-insensitive) in seg.text.
      3. Resolve overlaps: longest match wins.
      4. Apply right-to-left so earlier offsets stay valid.
      5. For single-token surfaces, also patch seg.words[*].text so
         word-level consumers (e.g. cut_planner, remap) see the canonical.
         Multi-token surfaces only update seg.text — timestamps are
         word-level and can't be re-aligned without re-running ASR.
    """
    import re

    pairs = sorted(
        ((s, c) for s, c in alias_map.items() if s and s != c),
        key=lambda p: -len(p[0]),
    )
    if not pairs:
        return transcript

    def _spans(text: str) -> list[tuple[int, int, str, str]]:
        out: list[tuple[int, int, str, str]] = []
        for surface, canonical in pairs:
            pat = re.compile(
                r"(?<![\w])" + re.escape(surface) + r"(?![\w])",
                flags=re.IGNORECASE,
            )
            for m in pat.finditer(text):
                out.append((m.start(), m.end(), surface, canonical))
        if not out:
            return out
        out.sort(key=lambda m: (-(m[1] - m[0]), m[0]))
        accepted: list[tuple[int, int, str, str]] = []
        for m in out:
            s, e = m[0], m[1]
            if any(not (e <= a_s or s >= a_e) for (a_s, a_e, _, _) in accepted):
                continue
            accepted.append(m)
        accepted.sort(key=lambda m: m[0])
        return accepted

    def _apply(text: str, spans: list[tuple[int, int, str, str]]) -> str:
        out = text
        for s, e, _surf, canonical in sorted(spans, key=lambda m: -m[0]):
            out = out[:s] + canonical + out[e:]
        return out

    single_token_map: dict[str, str] = {
        s.lower(): c for s, c in alias_map.items() if " " not in s
    }

    def _strip(t: str) -> str:
        return t.strip(".,;:!?¡¿\"'()[]{}…").strip()

    new_segs = []
    for seg in transcript.segments:
        spans = _spans(seg.text)
        new_text = _apply(seg.text, spans) if spans else seg.text

        new_words = []
        for w in seg.words:
            stripped = _strip(w.text)
            replacement = single_token_map.get(stripped.lower())
            if replacement and stripped in w.text:
                prefix = w.text[: w.text.index(stripped)]
                suffix = w.text[len(prefix) + len(stripped):]
                new_words.append(w.model_copy(update={"text": prefix + replacement + suffix}))
            else:
                new_words.append(w)

        new_segs.append(seg.model_copy(update={"words": new_words, "text": new_text}))
    return transcript.model_copy(update={"segments": new_segs})


if __name__ == "__main__":
    main()
