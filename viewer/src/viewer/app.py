"""v6 viewer — FastAPI app that lists pipeline runs and visualises their outputs.

Discovery: a "pipeline run" is any directory containing at least one child
directory with a `progress.jsonl`. Phases are child dirs. Legacy runs (a
single dir at root level with `progress.jsonl` or `timeline_map.json`) are
treated as a single-phase pipeline.

Run: `uvicorn viewer.app:app --reload --port 8765`
"""
from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from progress import parse_progress

log = logging.getLogger(__name__)


HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE.parent.parent / "templates"
STATIC_DIR = HERE.parent.parent / "static"

DEFAULT_ROOTS = [Path("/tmp")]

app = FastAPI(title="myavatar v6 viewer")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _configured_roots() -> list[Path]:
    env = os.environ.get("VIEWER_ROOTS")
    if env:
        return [Path(p) for p in env.split(":") if p]
    return DEFAULT_ROOTS


def _live_status(run_dir: Path) -> tuple[bool, bool, str]:
    """Return (live, done, live_status_str) from progress.jsonl.

    live_status examples:
    - "step 3/7 — transcribe · running whisper on top2_audio.wav"
    - "done: 9/9 ok"
    - "done: 4.99% saved"
    - "—"
    """
    state = parse_progress(run_dir / "progress.jsonl")
    if state.done:
        summary = state.summary or {}
        if "ok" in summary and "failed" in summary:
            ok = summary["ok"]
            total = (summary.get("ok", 0) + summary.get("failed", 0) + summary.get("skipped_cache", 0))
            live_status = f"done: {ok}/{total} ok"
        elif "pct_saved" in summary:
            live_status = f"done: {summary['pct_saved']:.2f}% saved"
        else:
            live_status = "done"
        return False, True, live_status

    if state.in_progress:
        idx = state.current_index
        total = state.total_steps
        name = state.current_name
        detail = state.current_detail
        if idx is not None and total is not None and name:
            parts = [f"step {idx}/{total} — {name}"]
            if detail:
                parts.append(detail)
            live_status = " · ".join(parts)
        else:
            live_status = "starting…"
        return True, False, live_status

    return False, False, "—"


# ── Run discovery ───────────────────────────────────────────────────

def _collect_run_dirs_for_phase(phase: str, legacy_marker: str) -> list[Path]:
    """Collect unique run dirs matching phase, using progress.jsonl as primary
    marker, falling back to legacy_marker for pre-v2 runs."""
    seen: set[Path] = set()
    results: list[Path] = []
    for root in _configured_roots():
        if not root.exists():
            continue
        # Primary: progress.jsonl with matching phase
        for pf in root.rglob("progress.jsonl"):
            run_dir = pf.parent
            if run_dir in seen:
                continue
            state = parse_progress(pf)
            if state.phase == phase:
                seen.add(run_dir)
                results.append(run_dir)
        # Fallback: legacy marker (no progress.jsonl or no phase set)
        for marker in root.rglob(legacy_marker):
            run_dir = marker.parent
            if run_dir in seen:
                continue
            seen.add(run_dir)
            results.append(run_dir)
    return results


def _discover_runs() -> list[dict[str, Any]]:
    """Scan roots for polish run directories."""
    runs: list[dict[str, Any]] = []
    for run_dir in _collect_run_dirs_for_phase("polish", "timeline_map.json"):
        try:
            summary_path = run_dir / "summary.json"
            summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
            tm_path = run_dir / "timeline_map.json"
            tmap = json.loads(tm_path.read_text()) if tm_path.exists() else {}
            state = parse_progress(run_dir / "progress.jsonl")
            live, done, live_status = _live_status(run_dir)

            # Derive display fields best-effort
            original_s = tmap.get("total_original_duration_s")
            edited_s = tmap.get("total_edited_duration_s")
            pct_saved = summary.get("pct_saved")
            active_cuts = summary.get("active_cuts", len([
                c for c in tmap.get("cut_regions", []) if c.get("action") == "cut"
            ]))
            entity_candidates = summary.get("entity_candidates")
            created_at = tmap.get("created_at")

            # Fallback from run_done summary if timeline_map not yet written
            if state.done and not tmap:
                rs = state.summary or {}
                pct_saved = pct_saved or rs.get("pct_saved")
                edited_s = edited_s or rs.get("edited_s")
                entity_candidates = entity_candidates or rs.get("entity_candidates")

            runs.append({
                "name": run_dir.name,
                "path": str(run_dir),
                "source_video_path": tmap.get("source_video_path"),
                "created_at": created_at,
                "original_s": original_s,
                "edited_s": edited_s,
                "pct_saved": pct_saved,
                "active_cuts": active_cuts,
                "entity_candidates": entity_candidates,
                "patches_by_layer": summary.get("patches_by_layer", {}),
                "live": live,
                "done": done,
                "live_status": live_status,
                "phase": state.phase,
            })
        except Exception as exc:
            runs.append({"name": run_dir.name, "path": str(run_dir), "error": str(exc)})
    runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return runs


def _load_run(run_path: Path) -> dict[str, Any]:
    """Load all the JSON artefacts for a run."""
    out: dict[str, Any] = {"path": str(run_path), "name": run_path.name}
    for fname, key in [
        ("summary.json", "summary"),
        ("timeline_map.json", "timeline_map"),
        ("transcript_polished.json", "transcript_polished"),
        ("transcript_raw.json", "transcript_raw"),
        ("transcript_patches.json", "transcript_patches"),
        ("entity_candidates.json", "entity_candidates"),
    ]:
        p = run_path / fname
        if p.exists():
            try:
                out[key] = json.loads(p.read_text())
            except Exception as exc:
                out[key] = {"_error": str(exc)}
    return out


def _find_run(run_name: str) -> Path:
    """Find a polish run dir by name. Primary: progress.jsonl; fallback: timeline_map.json."""
    for root in _configured_roots():
        if not root.exists():
            continue
        # Primary: progress.jsonl with matching name
        for pf in root.rglob("progress.jsonl"):
            if pf.parent.name == run_name:
                return pf.parent
        # Fallback: legacy timeline_map
        for tm in root.rglob("timeline_map.json"):
            if tm.parent.name == run_name:
                return tm.parent
    raise HTTPException(status_code=404, detail=f"Run {run_name!r} not found")


# ── Progress fragment helper ────────────────────────────────────────

def _progress_fragment_html(run_dir: Path) -> str:
    """Render a unified progress fragment HTML from progress.jsonl."""
    state = parse_progress(run_dir / "progress.jsonl")

    if not state.in_progress and not state.done:
        return '<span class="text-slate-400 text-sm">no progress log</span>'

    if state.done:
        summary = state.summary or {}
        if "ok" in summary and "failed" in summary:
            ok = summary["ok"]
            failed = summary["failed"]
            cached = summary.get("skipped_cache", 0)
            return (
                f'<span class="text-green-700 text-sm font-medium">'
                f'done: {ok} ok / {failed} failed / {cached} cached'
                f'</span>'
            )
        elif "pct_saved" in summary:
            pct = summary["pct_saved"] or 0
            edited = summary.get("edited_s", 0) or 0
            candidates = summary.get("entity_candidates", 0) or 0
            return (
                f'<span class="text-green-700 text-sm font-medium">'
                f'done: {pct:.2f}% saved, {edited:.1f}s edited, {candidates} candidates'
                f'</span>'
            )
        else:
            return '<span class="text-green-700 text-sm font-medium">done</span>'

    # in-progress
    idx = state.current_index
    total = state.total_steps or "?"
    name = state.current_name or "…"
    detail = state.current_detail or ""
    if idx is not None:
        try:
            pct_bar = int(100 * idx / int(total))
        except (TypeError, ValueError, ZeroDivisionError):
            pct_bar = 0
        detail_part = f" · {detail}" if detail else ""
        return (
            f'<div class="text-sm">'
            f'<span class="text-blue-700">step {idx}/{total} — {name}{detail_part}</span>'
            f'<div class="mt-1 h-1.5 rounded-full bg-slate-200 w-48">'
            f'  <div class="h-1.5 rounded-full bg-blue-500" style="width:{pct_bar}%"></div>'
            f'</div>'
            f'</div>'
        )
    return '<span class="text-slate-500 text-sm">starting…</span>'


# ── Pipeline discovery ──────────────────────────────────────────────

CANONICAL_PHASE_ORDER = ["capture", "polish", "analysis", "broll_plan", "builder"]


def _phase_info(phase_dir: Path) -> dict[str, Any]:
    """Build a PhaseInfo dict for a single phase directory."""
    state = parse_progress(phase_dir / "progress.jsonl")
    live, done, live_status = _live_status(phase_dir)
    failed = state.done and state.ok is False
    return {
        "name": phase_dir.name,
        "path": phase_dir,
        "state": state,
        "live_status": live_status,
        "live": live,
        "done": done,
        "failed": failed,
    }


def _sort_phases(phases: list[dict]) -> list[dict]:
    """Sort phases: canonical order first, then alphabetical."""
    def key(p: dict) -> tuple[int, str]:
        try:
            return (CANONICAL_PHASE_ORDER.index(p["name"]), p["name"])
        except ValueError:
            return (len(CANONICAL_PHASE_ORDER), p["name"])
    return sorted(phases, key=key)


def _discover_pipeline_runs() -> list[dict[str, Any]]:
    """Return a list of pipeline run dicts grouped by parent directory.

    Grouping rule:
    - rglob progress.jsonl under each configured root.
    - phase_dir = file.parent; pipeline_dir = file.parent.parent.
    - If pipeline_dir IS a configured root → legacy single-phase: pipeline IS phase_dir.
    - Otherwise group by pipeline_dir. Multiple phase_dirs under same pipeline_dir = multi-phase.
    - Also pick up legacy timeline_map.json dirs that have no progress.jsonl.

    Each returned dict: name, path, phases (sorted), created_at, any_live, any_failed, all_done
    """
    roots = set(_configured_roots())
    # Map: pipeline_dir Path → set of phase dirs
    pipeline_map: dict[Path, set[Path]] = {}
    seen_phase_dirs: set[Path] = set()

    for root in _configured_roots():
        if not root.exists():
            continue
        for pf in root.rglob("progress.jsonl"):
            phase_dir = pf.parent
            if phase_dir in seen_phase_dirs:
                continue
            seen_phase_dirs.add(phase_dir)

            pipeline_dir = phase_dir.parent
            if pipeline_dir in roots:
                # Direct child of a root → single-phase legacy pipeline; key = phase_dir itself
                pipeline_map.setdefault(phase_dir, set()).add(phase_dir)
            else:
                # Normal case: pipeline = parent dir of phase dir
                pipeline_map.setdefault(pipeline_dir, set()).add(phase_dir)

    # Legacy: timeline_map.json with no progress.jsonl
    for root in _configured_roots():
        if not root.exists():
            continue
        for tm in root.rglob("timeline_map.json"):
            phase_dir = tm.parent
            if phase_dir in seen_phase_dirs:
                continue
            seen_phase_dirs.add(phase_dir)
            pipeline_dir = phase_dir.parent
            if pipeline_dir in roots:
                pipeline_map.setdefault(phase_dir, set()).add(phase_dir)
            else:
                pipeline_map.setdefault(pipeline_dir, set()).add(phase_dir)

    results: list[dict[str, Any]] = []
    for pipeline_dir, phase_dirs_set in pipeline_map.items():
        phases_raw = [_phase_info(pd) for pd in phase_dirs_set]
        pipeline_name = pipeline_dir.name

        phases = _sort_phases(phases_raw)

        # Infer cross-phase metadata
        run_start_ts = []
        for ph in phases:
            state = ph["state"]
            if state.events_seen > 0:
                # Read first event's ts from the actual jsonl
                pf = ph["path"] / "progress.jsonl"
                try:
                    first_line = pf.read_text().splitlines()[0]
                    evt = json.loads(first_line)
                    if ts := evt.get("ts"):
                        run_start_ts.append(ts)
                except Exception:
                    pass

        created_at = min(run_start_ts) if run_start_ts else None
        any_live = any(ph["live"] for ph in phases)
        any_failed = any(ph["failed"] for ph in phases)
        all_done = bool(phases) and all(ph["done"] for ph in phases)

        results.append({
            "name": pipeline_name,
            "path": pipeline_dir,
            "phases": phases,
            "created_at": created_at,
            "any_live": any_live,
            "any_failed": any_failed,
            "all_done": all_done,
        })

    results.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return results


def _find_pipeline(pipeline_name: str) -> dict[str, Any]:
    """Find a pipeline run by name. Returns the pipeline dict or raises 404."""
    for run in _discover_pipeline_runs():
        if run["name"] == pipeline_name:
            return run
    raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_name!r} not found")


def _load_phase_preview(phase_dir: Path, phase_name: str) -> dict[str, Any]:
    """Load phase-specific preview data (best-effort, all fields optional)."""
    preview: dict[str, Any] = {}

    if phase_name == "capture":
        captures_dir = phase_dir / "captures"
        if captures_dir.exists():
            slugs = [d.name for d in captures_dir.iterdir() if d.is_dir()]
            preview["capture_slugs"] = slugs[:20]
        mf = phase_dir / "capture_manifest.json"
        if mf.exists():
            try:
                manifest = json.loads(mf.read_text())
                preview["capture_results"] = manifest.get("results", [])
            except Exception:
                pass

    elif phase_name == "polish":
        # Transcript excerpt (first 20 segments)
        for fname in ("transcript_polished.json", "transcript_raw.json"):
            tp = phase_dir / fname
            if tp.exists():
                try:
                    data = json.loads(tp.read_text())
                    segs = data.get("segments", [])[:20]
                    preview["transcript_segments"] = segs
                    preview["transcript_source"] = fname
                    break
                except Exception:
                    pass

        # Applied corrections
        patches_file = phase_dir / "transcript_patches.json"
        if patches_file.exists():
            try:
                data = json.loads(patches_file.read_text())
                preview["patches"] = data.get("patches", [])
            except Exception:
                preview["patches"] = []
        else:
            preview["patches"] = []

        # Unresolved entity candidates
        ent_file = phase_dir / "entity_candidates.json"
        if ent_file.exists():
            try:
                data = json.loads(ent_file.read_text())
                candidates = data.get("candidates", [])
                # Sort by occurrences descending, take top 20
                candidates_sorted = sorted(
                    candidates,
                    key=lambda c: c.get("occurrences", 0),
                    reverse=True
                )[:20]
                preview["entity_candidates"] = candidates_sorted
            except Exception:
                preview["entity_candidates"] = []
        else:
            preview["entity_candidates"] = []

    else:
        # Unknown phase — list files
        try:
            preview["file_list"] = [f.name for f in phase_dir.iterdir()
                                    if not f.name.startswith(".")]
        except Exception:
            pass

    return preview


# ── Pipeline manifest (v3.0 generic renderer) ───────────────────────

def _load_pipeline_manifest(run_path: Path) -> dict | None:
    """Read pipeline_manifest.json from run root. Returns None if absent."""
    mf = run_path / "pipeline_manifest.json"
    if not mf.exists():
        return None
    try:
        return json.loads(mf.read_text())
    except Exception:
        return None


_BROLL_TYPE_COLORS = {
    "video":       "bg-rose-500",
    "slide":       "bg-amber-500",
    "web_capture": "bg-sky-500",
    "photo":       "bg-emerald-500",
    "pexels":      "bg-violet-500",
    "mockup":      "bg-fuchsia-500",
    "title":       "bg-slate-500",
}
_EF_COLORS = {
    "hook":       "bg-indigo-100  text-indigo-800",
    "pain":       "bg-rose-100    text-rose-800",
    "solution":   "bg-emerald-100 text-emerald-800",
    "proof":      "bg-cyan-100    text-cyan-800",
    "value":      "bg-teal-100    text-teal-800",
    "how_to":     "bg-amber-100   text-amber-800",
    "thesis":     "bg-violet-100  text-violet-800",
    "payoff":     "bg-fuchsia-100 text-fuchsia-800",
    "transition": "bg-slate-100   text-slate-600",
}


def _build_timeline(analysis: dict, options: dict) -> dict | None:
    """Transform an analysis.json into a flat timeline structure the
    template can render with width-percentages.

    Output shape:
        {
          "duration_s": 221.78,
          "beats": [
            {"id":"b001","start_s":0.0,"end_s":3.0,"width_pct":1.4,
             "left_pct":0.0, "ef":"hook","ef_color":"...","text":"...",
             "broll_hints":[
                {"type":"video","color":"bg-rose-500",
                 "left_pct":0.0,"width_pct":1.4,
                 "subject":"Gemma 4","shot_type":"logo_centered",
                 "query":"Gemma 4 logo","description":"..."},
             ]
            }
          ]
        }
    """
    narrative = analysis.get("narrative") if isinstance(analysis, dict) else None
    if not narrative:
        return None
    duration = float(analysis.get("duration_s") or 0)
    beats_raw = narrative.get("beats") or []
    if not beats_raw:
        return None
    if duration <= 0:
        # Derive from last beat
        duration = max((float(b.get("end_s", 0) or 0) for b in beats_raw), default=0)
    if duration <= 0:
        return None

    rows = []
    type_counts: dict[str, int] = {}
    hint_total_s = 0.0
    hint_global_spans: list[tuple[float, float]] = []
    flat_hints_for_audit: list[dict] = []
    for beat in beats_raw:
        try:
            s = float(beat.get("start_s", 0))
            e = float(beat.get("end_s", 0))
        except (TypeError, ValueError):
            continue
        if e <= s:
            continue
        beat_dur = e - s
        beat_left = round(100.0 * s / duration, 3)
        beat_width = round(100.0 * beat_dur / duration, 3)
        ef = beat.get("editorial_function", "")
        hints_out = []
        spans_in_beat: list[tuple[float, float]] = []
        for h in beat.get("broll_hints") or []:
            tin = float((h.get("timing") or {}).get("in_pct", 0.0))
            tout = float((h.get("timing") or {}).get("out_pct", 1.0))
            tin = max(0.0, min(1.0, tin))
            tout = max(tin, min(1.0, tout))
            hint_dur_s = beat_dur * (tout - tin)
            hint_total_s += hint_dur_s
            type_counts[h.get("type", "")] = type_counts.get(h.get("type", ""), 0) + 1
            abs_start = s + beat_dur * tin
            abs_end = s + beat_dur * tout
            spans_in_beat.append((abs_start, abs_end))
            hint_global_spans.append((abs_start, abs_end))
            row_hint = {
                "type": h.get("type", ""),
                "color": _BROLL_TYPE_COLORS.get(h.get("type", ""), "bg-gray-400"),
                "left_pct":  round(beat_width * tin, 3),
                "width_pct": round(beat_width * (tout - tin), 3),
                "subject": h.get("subject") or "",
                "shot_type": h.get("shot_type") or "",
                "query": h.get("query") or "",
                "queries_fallback": h.get("queries_fallback") or [],
                "description": h.get("description") or "",
                "source_ref": h.get("source_ref") or "",
                "duration_s": round(hint_dur_s, 2),
                "duration_target_s": h.get("duration_target_s"),
                "energy_match": h.get("energy_match") or "",
                "abs_start_s": round(abs_start, 2),
                "abs_end_s": round(abs_end, 2),
            }
            hints_out.append(row_hint)
            flat_hints_for_audit.append({
                "beat_id": beat.get("beat_id", ""),
                **row_hint,
            })

        # In-beat overlap detection (two hints sharing time inside same beat)
        overlap_in_beat = False
        if len(spans_in_beat) >= 2:
            sorted_spans = sorted(spans_in_beat)
            for i in range(1, len(sorted_spans)):
                if sorted_spans[i][0] < sorted_spans[i-1][1]:
                    overlap_in_beat = True
                    break

        rows.append({
            "id": beat.get("beat_id", ""),
            "start_s": s,
            "end_s": e,
            "duration_s": round(beat_dur, 2),
            "left_pct": beat_left,
            "width_pct": beat_width,
            "ef": ef,
            "ef_color": _EF_COLORS.get(ef, "bg-slate-100 text-slate-600"),
            "text": beat.get("text", ""),
            "hero": beat.get("hero_text_candidate") or "",
            "broll_hints": hints_out,
            "n_hints": len(hints_out),
            "overloaded": len(hints_out) >= 3,
            "no_broll": len(hints_out) == 0,
            "overlap_in_beat": overlap_in_beat,
        })

    # Coverage = union of all hint spans / duration
    coverage_s = 0.0
    if hint_global_spans:
        sorted_spans = sorted(hint_global_spans)
        cur_s, cur_e = sorted_spans[0]
        for ns, ne in sorted_spans[1:]:
            if ns <= cur_e:
                cur_e = max(cur_e, ne)
            else:
                coverage_s += cur_e - cur_s
                cur_s, cur_e = ns, ne
        coverage_s += cur_e - cur_s

    minutes = duration / 60.0 if duration > 0 else 1.0
    target_min = max(1, round(minutes * 3))
    target_max = max(target_min, round(minutes * 5))

    total_hints = sum(r["n_hints"] for r in rows)
    stats = {
        "total_hints": total_hints,
        "hints_per_min": round(total_hints / minutes, 1) if minutes else 0,
        "target_min": target_min,
        "target_max": target_max,
        "coverage_s": round(coverage_s, 2),
        "coverage_pct": round(100.0 * coverage_s / duration, 1) if duration else 0,
        "hint_total_s": round(hint_total_s, 2),  # raw sum (counts overlaps twice)
        "type_counts": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])),
        "beats_no_broll": sum(1 for r in rows if r["no_broll"]),
        "beats_overloaded": sum(1 for r in rows if r["overloaded"]),
        "beats_with_overlap": sum(1 for r in rows if r["overlap_in_beat"]),
    }

    return {
        "duration_s": duration,
        "beats": rows,
        "stats": stats,
        "all_hints": flat_hints_for_audit,
    }


def _resolve_field(obj: Any, field: str) -> Any:
    """Resolve a dotted field path like 'request.slug' from a nested dict."""
    parts = field.split(".")
    cur = obj
    for part in parts:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _render_artifact(artifact: dict, phase_dir: Path) -> dict:
    """Resolve paths and data for a single render artifact. Returns enriched dict."""
    import glob as glob_mod
    result = dict(artifact)
    atype = artifact.get("type", "")
    path = artifact.get("path")
    path_pattern = artifact.get("path_pattern")
    options = artifact.get("options", {})

    if path:
        full_path = phase_dir / path
        if atype == "transcript":
            result["data"] = _safe_json(full_path)
        elif atype == "json_table":
            raw = _safe_json(full_path)
            if isinstance(raw, dict):
                # Support both `root_path` (dotted, e.g. "narrative.beats")
                # and the legacy `root_key` (single-level key).
                root_path = options.get("root_path") or options.get("root_key")
                if root_path:
                    rows = _resolve_field(raw, root_path)
                elif "results" in raw:
                    rows = raw["results"]
                else:
                    rows = raw
            elif isinstance(raw, list):
                rows = raw
            else:
                rows = None

            # Optional flatten: when each row contains a list field, expand it
            # so each nested item becomes its own row (used for broll_hints
            # which are list[BrollHint] per beat). Selected parent fields are
            # copied onto each child via `inherit_fields`.
            flatten_field = options.get("flatten_field")
            if flatten_field and isinstance(rows, list):
                inherit = options.get("inherit_fields", [])
                expanded: list[dict] = []
                for parent in rows:
                    if not isinstance(parent, dict):
                        continue
                    inherited = {k: parent.get(k) for k in inherit}
                    for child in (parent.get(flatten_field) or []):
                        if not isinstance(child, dict):
                            continue
                        expanded.append({**inherited, **child})
                rows = expanded

            columns = options.get("columns", [])
            result["rows"] = _process_table_rows(rows, columns) if rows is not None else None
            result["columns"] = columns
        elif atype == "key_value":
            raw = _safe_json(full_path)
            if isinstance(raw, dict):
                fields = options.get("fields", [])
                result["kv_items"] = [
                    {"label": f.get("label", f.get("key")), "value": _resolve_field(raw, f["key"])}
                    for f in fields
                ]
            else:
                result["kv_items"] = None
        elif atype == "text_preview":
            result["text"] = _safe_text(full_path, max_chars=options.get("max_chars", 400))
        elif atype == "timeline":
            raw = _safe_json(full_path)
            result["timeline"] = _build_timeline(raw, options) if raw else None

    if path_pattern:
        pattern = str(phase_dir / path_pattern)
        matched = sorted(glob_mod.glob(pattern))
        if atype == "image_gallery":
            # Return relative paths for URL building
            result["images"] = [Path(p) for p in matched]
        elif atype == "text_preview":
            # Preview first matching file
            if matched:
                result["text"] = _safe_text(Path(matched[0]), max_chars=options.get("max_chars", 400))
            else:
                result["text"] = None

    return result


def _process_table_rows(rows: list, columns: list) -> list[dict]:
    """Resolve column fields from each row dict.

    Supported format values:
    - "list_length": returns len(value) if value is a list, else 0.
    - "list_count_by_type": returns "type1×N, type2×M" summary for a list of
      dicts with a "type" key.
    - "join_csv": joins a list of strings with ", ".
    """
    out = []
    for row in rows:
        cells = {}
        for col in columns:
            field = col.get("field", "")
            fmt = col.get("format")
            composed = col.get("composed")
            if composed and len(composed) == 2:
                a = _resolve_field(row, composed[0])
                b = _resolve_field(row, composed[1])
                value = f"{a} → {b}" if a is not None and b is not None else str(a or b or "")
            else:
                value = _resolve_field(row, field)
                if fmt == "list_length":
                    value = len(value) if isinstance(value, list) else 0
                elif fmt == "list_count_by_type":
                    if isinstance(value, list):
                        counts: dict[str, int] = {}
                        for item in value:
                            t = item.get("type", "?") if isinstance(item, dict) else str(item)
                            counts[t] = counts.get(t, 0) + 1
                        value = ", ".join(f"{t}×{n}" for t, n in counts.items()) if counts else ""
                    else:
                        value = ""
                elif fmt == "join_csv":
                    if isinstance(value, list):
                        value = ", ".join(str(v) for v in value)
                    elif value is None:
                        value = ""
            cells[field] = value
        out.append(cells)
    return out


def _safe_json(path: Path) -> Any:
    """Read JSON from path. Returns None on error."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _safe_text(path: Path, max_chars: int = 400) -> str | None:
    """Read first max_chars of a text file. Returns None if missing."""
    if not path.exists():
        return None
    try:
        return path.read_text(errors="replace")[:max_chars]
    except Exception:
        return None


def _load_pipeline_detail(pipeline: dict[str, Any]) -> dict[str, Any]:
    """Augment phases with step lists and preview data for the detail view."""
    phases_detail = []
    for ph in pipeline["phases"]:
        phase_dir: Path = ph["path"]
        state = ph["state"]

        # Build step rows from progress events
        steps: list[dict] = []
        pf = phase_dir / "progress.jsonl"
        if pf.exists():
            try:
                events = [json.loads(ln) for ln in pf.read_text().splitlines() if ln.strip()]
            except Exception:
                events = []
            done_map: dict[int, dict] = {
                e["index"]: e for e in events if e.get("type") == "step_done"
            }
            done_indices = set(done_map.keys())
            active_index = state.current_index

            total = state.total_steps or 0
            # Collect all seen step_start events
            seen_starts: dict[int, dict] = {}
            for e in events:
                if e.get("type") == "step_start":
                    seen_starts[e["index"]] = e

            for idx in range(1, total + 1):
                start_evt = seen_starts.get(idx)
                done_evt = done_map.get(idx)
                if done_evt:
                    summary = done_evt.get("summary") or {}
                    summary_str = ", ".join(
                        f"{k}: {v}" for k, v in list(summary.items())[:3]
                    )
                    steps.append({
                        "idx": idx,
                        "name": done_evt.get("name") or (start_evt.get("name") if start_evt else "?"),
                        "status": "done",
                        "duration_ms": done_evt.get("duration_ms"),
                        "summary_str": summary_str,
                        "detail": start_evt.get("detail", "") if start_evt else "",
                    })
                elif idx == active_index:
                    steps.append({
                        "idx": idx,
                        "name": start_evt.get("name") if start_evt else "?",
                        "status": "active",
                        "detail": start_evt.get("detail", "") if start_evt else "",
                    })
                else:
                    steps.append({
                        "idx": idx,
                        "name": start_evt.get("name") if start_evt else f"step {idx}",
                        "status": "pending",
                        "detail": "",
                    })

        # Elapsed time
        elapsed_str = "—"
        pf2 = phase_dir / "progress.jsonl"
        if pf2.exists():
            try:
                lines = [ln for ln in pf2.read_text().splitlines() if ln.strip()]
                if lines:
                    first_ts = json.loads(lines[0]).get("ts", "")
                    last_ts = json.loads(lines[-1]).get("ts", "")
                    if first_ts and last_ts:
                        from datetime import datetime, timezone
                        fmt = "%Y-%m-%dT%H:%M:%S.%f+00:00"
                        try:
                            t0 = datetime.fromisoformat(first_ts.replace("+00:00", "+00:00"))
                            t1 = datetime.fromisoformat(last_ts.replace("+00:00", "+00:00"))
                            elapsed_s = (t1 - t0).total_seconds()
                            elapsed_str = f"{elapsed_s:.1f}s"
                        except Exception:
                            pass
            except Exception:
                pass

        preview = _load_phase_preview(phase_dir, ph["name"])

        # v3.0: load manifest artifacts if pipeline_manifest.json is present
        manifest_artifacts: list[dict] = []
        manifest = _load_pipeline_manifest(pipeline["path"])
        if manifest:
            # Find this phase's artifacts from the manifest
            for mp in manifest.get("phases", []):
                if mp["name"] == ph["name"]:
                    for art in mp.get("render_artifacts", []):
                        manifest_artifacts.append(_render_artifact(art, phase_dir))
                    break

        phases_detail.append({
            **ph,
            "steps": steps,
            "elapsed": elapsed_str,
            "preview": preview,
            "artifacts": manifest_artifacts,
        })

    return {**pipeline, "phases": phases_detail}


# ── Routes ─────────────────────────────────────────────────────────

@app.get("/api/health")
def api_health():
    """Lightweight health endpoint exposing the live VIEWER_ROOTS.

    Callers (notably ``viewer.launcher.ensure_running``) use this to detect
    a stale viewer that was started with a different root and needs a
    restart. Returning the actual roots avoids the silent "Pipeline not
    found" 404 that happens when the running viewer points to /tmp but the
    new pipeline writes to ~/myavatar/runs.
    """
    return {
        "ok": True,
        "roots": [str(r) for r in _configured_roots()],
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    pipeline_runs = _discover_pipeline_runs()
    return templates.TemplateResponse(
        request=request,
        name="pipeline_index.html",
        context={"pipeline_runs": pipeline_runs},
    )


@app.get("/pipeline/{pipeline_name}", response_class=HTMLResponse)
def pipeline_detail(request: Request, pipeline_name: str):
    pipeline = _find_pipeline(pipeline_name)
    detail = _load_pipeline_detail(pipeline)
    return templates.TemplateResponse(
        request=request,
        name="pipeline_run.html",
        context={"pipeline": detail},
    )


@app.get("/pipeline/{pipeline_name}/progress", response_class=HTMLResponse)
def pipeline_progress(pipeline_name: str):
    pipeline = _find_pipeline(pipeline_name)
    # Re-parse phases fresh for the fragment
    phases_fresh = [_phase_info(ph["path"]) for ph in pipeline["phases"]]
    phases_sorted = _sort_phases(phases_fresh)
    # Build HTML fragment with per-phase status badges
    parts = []
    for ph in phases_sorted:
        if ph["live"]:
            badge_cls = "text-blue-700 animate-pulse"
            badge_txt = f"● {ph['live_status']}"
        elif ph["done"] and not ph["failed"]:
            badge_cls = "text-green-700"
            badge_txt = ph["live_status"]
        elif ph["failed"]:
            badge_cls = "text-red-600"
            badge_txt = "failed"
        else:
            badge_cls = "text-slate-400"
            badge_txt = "not started"
        parts.append(
            f'<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 text-xs {badge_cls}" '
            f'title="{ph["name"]}">'
            f'<span class="font-medium">{ph["name"]}</span>'
            f'<span>{badge_txt}</span>'
            f'</span>'
        )
    return HTMLResponse('<div class="flex flex-wrap gap-2">' + "".join(parts) + "</div>")


@app.api_route("/pipeline/{pipeline_name}/{phase_name}/screenshot/{slug}", methods=["GET", "HEAD"])
def pipeline_screenshot(pipeline_name: str, phase_name: str, slug: str):
    pipeline = _find_pipeline(pipeline_name)
    phase = next((ph for ph in pipeline["phases"] if ph["name"] == phase_name), None)
    if phase is None:
        raise HTTPException(status_code=404, detail="phase not found")
    phase_dir: Path = phase["path"]
    img_path = (phase_dir / "captures" / slug / "screenshot.png").resolve()
    if not str(img_path).startswith(str(phase_dir.resolve())):
        raise HTTPException(status_code=400, detail="invalid path")
    if not img_path.is_file():
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(img_path, media_type="image/png")


@app.get("/pipeline/{pipeline_name}/{phase_name}/text/{slug}")
def pipeline_text(pipeline_name: str, phase_name: str, slug: str):
    pipeline = _find_pipeline(pipeline_name)
    phase = next((ph for ph in pipeline["phases"] if ph["name"] == phase_name), None)
    if phase is None:
        raise HTTPException(status_code=404, detail="phase not found")
    phase_dir: Path = phase["path"]
    txt_path = (phase_dir / "captures" / slug / "text.txt").resolve()
    if not str(txt_path).startswith(str(phase_dir.resolve())):
        raise HTTPException(status_code=400, detail="invalid path")
    if not txt_path.is_file():
        raise HTTPException(status_code=404, detail="text not found")
    return FileResponse(txt_path, media_type="text/plain; charset=utf-8")


@app.get("/run/{run_name}", response_class=HTMLResponse)
def run_detail(request: Request, run_name: str):
    run_path = _find_run(run_name)
    data = _load_run(run_path)

    # Pre-compute timeline visual data (best-effort — may be empty during live run)
    tmap = data.get("timeline_map", {})
    total = tmap.get("total_original_duration_s") or 1.0
    cuts = [
        {
            "id": c["id"],
            "start_s": c["start_s"],
            "end_s": c["end_s"],
            "reason": c["reason"],
            "confidence": c["confidence"],
            "pct_start": 100.0 * c["start_s"] / total,
            "pct_width": 100.0 * (c["end_s"] - c["start_s"]) / total,
        }
        for c in tmap.get("cut_regions", []) if c.get("action") == "cut"
    ]
    data["timeline_visual"] = {"total_s": total, "cuts": cuts}

    # Transcript segments for interactive display
    tp = data.get("transcript_polished", {})
    segments = [
        {
            "idx": i,
            "start_s": s["start_s"],
            "end_s": s["end_s"],
            "text": s["text"],
        }
        for i, s in enumerate(tp.get("segments", []))
    ]
    data["polished_segments"] = segments

    return templates.TemplateResponse(
        request=request, name="run.html", context={"run": data},
    )


@app.get("/run/{run_name}/progress", response_class=HTMLResponse)
def polish_progress(run_name: str):
    run_path = _find_run(run_name)
    return HTMLResponse(_progress_fragment_html(run_path))


@app.get("/run/{run_name}/media/audio")
def run_audio(run_name: str):
    run_path = _find_run(run_name)
    tmap_path = run_path / "timeline_map.json"
    tmap = json.loads(tmap_path.read_text())
    src = tmap.get("source_video_path")
    if not src or not Path(src).exists():
        raise HTTPException(status_code=404, detail="source media not found")
    mime, _ = mimetypes.guess_type(src)
    return FileResponse(src, media_type=mime or "application/octet-stream")


@app.get("/run/{run_name}/raw/{fname}")
def run_raw(run_name: str, fname: str):
    """Serve a run's JSON artefact raw (for download/inspection)."""
    run_path = _find_run(run_name)
    p = run_path / fname
    if not p.exists():
        raise HTTPException(status_code=404, detail=fname)
    return FileResponse(p, media_type="application/json")


# ── Capture routes ──────────────────────────────────────────────────

def _discover_capture_runs() -> list[dict[str, Any]]:
    """Scan roots for capture run directories."""
    runs: list[dict[str, Any]] = []
    for run_dir in _collect_run_dirs_for_phase("capture", "capture_manifest.json"):
        try:
            mf_path = run_dir / "capture_manifest.json"
            manifest = json.loads(mf_path.read_text()) if mf_path.exists() else {}
            results = manifest.get("results", [])
            ok = sum(1 for r in results if r.get("status") == "ok")
            failed = sum(1 for r in results if r.get("status") == "failed")
            live, done, live_status = _live_status(run_dir)
            state = parse_progress(run_dir / "progress.jsonl")
            runs.append({
                "name": run_dir.name,
                "path": str(run_dir),
                "created_at": manifest.get("created_at"),
                "total": len(results),
                "ok": ok,
                "failed": failed,
                "sources_file": manifest.get("sources_file"),
                "backend_default": manifest.get("backend_default"),
                "live": live,
                "done": done,
                "live_status": live_status,
                "phase": state.phase,
            })
        except Exception as exc:
            runs.append({"name": run_dir.name, "path": str(run_dir), "error": str(exc)})
    runs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return runs


def _find_capture_run(run_name: str) -> Path:
    """Find a capture run dir by name. Primary: progress.jsonl; fallback: capture_manifest.json."""
    for root in _configured_roots():
        if not root.exists():
            continue
        # Primary: progress.jsonl with matching name
        for pf in root.rglob("progress.jsonl"):
            if pf.parent.name == run_name:
                return pf.parent
        # Fallback: legacy capture_manifest
        for manifest in root.rglob("capture_manifest.json"):
            if manifest.parent.name == run_name:
                return manifest.parent
    raise HTTPException(status_code=404, detail=f"Capture run {run_name!r} not found")


@app.get("/capture", response_class=HTMLResponse)
def capture_index(request: Request):
    runs = _discover_capture_runs()
    return templates.TemplateResponse(
        request=request, name="capture_index.html", context={"runs": runs},
    )


@app.get("/capture/{run_name}", response_class=HTMLResponse)
def capture_run_detail(request: Request, run_name: str):
    run_path = _find_capture_run(run_name)
    manifest = {}
    mf_path = run_path / "capture_manifest.json"
    if mf_path.exists():
        manifest = json.loads(mf_path.read_text())
    state = parse_progress(run_path / "progress.jsonl")
    run_done = state.done
    return templates.TemplateResponse(
        request=request,
        name="capture_run.html",
        context={
            "run_name": run_name,
            "manifest": manifest,
            "event_count": state.events_seen,
            "run_done": run_done,
        },
    )


@app.get("/capture/{run_name}/progress", response_class=HTMLResponse)
def capture_progress(run_name: str):
    run_path = _find_capture_run(run_name)
    return HTMLResponse(_progress_fragment_html(run_path))


@app.api_route("/capture/{run_name}/screenshot/{slug}", methods=["GET", "HEAD"])
def capture_screenshot(run_name: str, slug: str):
    run_path = _find_capture_run(run_name)
    img_path = (run_path / "captures" / slug / "screenshot.png").resolve()
    # Path traversal guard
    if not str(img_path).startswith(str(run_path.resolve())):
        raise HTTPException(status_code=400, detail="invalid path")
    if not img_path.is_file():
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(img_path, media_type="image/png")


@app.get("/capture/{run_name}/text/{slug}")
def capture_text(run_name: str, slug: str):
    run_path = _find_capture_run(run_name)
    txt_path = (run_path / "captures" / slug / "text.txt").resolve()
    # Path traversal guard
    if not str(txt_path).startswith(str(run_path.resolve())):
        raise HTTPException(status_code=400, detail="invalid path")
    if not txt_path.is_file():
        raise HTTPException(status_code=404, detail="text not found")
    return FileResponse(txt_path, media_type="text/plain; charset=utf-8")


# ── CLI entrypoint ─────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--roots", default=None,
                    help="Colon-separated paths to scan for runs. "
                         "Default: /tmp. Also reads VIEWER_ROOTS env var.")
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    if args.roots:
        os.environ["VIEWER_ROOTS"] = args.roots

    import uvicorn
    uvicorn.run("viewer.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
