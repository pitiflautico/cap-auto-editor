"""parse_progress — reads a progress.jsonl file and returns a ProgressState.

Missing file → neutral ProgressState (everything None/False/0).
Malformed lines are skipped silently (logged to warnings).
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

from progress.contracts import ProgressState


def parse_progress(path: Path) -> ProgressState:
    """Parse *path* as a progress JSONL file and return a ProgressState.

    Degrades gracefully:
    - Missing file → neutral state (in_progress=False, done=False).
    - Malformed lines → silently skipped.
    """
    if not path.exists():
        return ProgressState()

    events: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception as exc:
            warnings.warn(f"progress: skipping malformed line: {exc}", stacklevel=1)

    events_seen = len(events)

    # Extract run_start info
    run_start = next((e for e in events if e.get("type") == "run_start"), None)
    phase = run_start.get("phase") if run_start else None
    total_steps = run_start.get("total_steps") if run_start else None

    # run_done?
    run_done = next((e for e in events if e.get("type") == "run_done"), None)
    if run_done:
        return ProgressState(
            phase=phase,
            total_steps=total_steps,
            completed_steps=sum(1 for e in events if e.get("type") == "step_done"),
            in_progress=False,
            done=True,
            ok=run_done.get("ok"),
            summary=run_done.get("summary") or {},
            events_seen=events_seen,
        )

    # in-progress: find the active step_start not yet matched by step_done
    done_indices = {e.get("index") for e in events if e.get("type") == "step_done"}
    completed_steps = len(done_indices)

    active_step = next(
        (
            e for e in reversed(events)
            if e.get("type") == "step_start" and e.get("index") not in done_indices
        ),
        None,
    )

    in_progress = run_start is not None  # run_start seen but no run_done

    return ProgressState(
        phase=phase,
        total_steps=total_steps,
        current_index=active_step.get("index") if active_step else None,
        current_name=active_step.get("name") if active_step else None,
        current_detail=active_step.get("detail") if active_step else None,
        completed_steps=completed_steps,
        in_progress=in_progress,
        done=False,
        ok=None,
        summary={},
        events_seen=events_seen,
    )
