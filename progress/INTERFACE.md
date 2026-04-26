# progress — Unified Progress Protocol

**FROZEN v1.0 — 2026-04-24**

Shared Python package (`v6/progress/`) that defines the single progress-event protocol used by every myavatar v6 phase: `capture`, `polish`, `analysis`, `broll_plan`, `builder`, …

---

## Schema

`progress.jsonl` — newline-delimited JSON, append-only per run. One run truncates the file on start. Events in strict order:

```json
{"type":"run_start","ts":"<ISO8601>","phase":"capture|polish|analysis|...","total_steps":<int>}
{"type":"step_start","ts":"<ISO8601>","index":<1..total>,"total":<int>,"name":"<slug>","detail":"<free text or null>"}
{"type":"step_done","ts":"<ISO8601>","index":<1..total>,"name":"<slug>","duration_ms":<int>,"summary":{<dict>}}
{"type":"run_done","ts":"<ISO8601>","ok":<bool>,"summary":{<dict>}}
```

### Rules

- `phase` is required on `run_start` so downstream can distinguish pipelines.
- `detail` is free-form string for live display. Must be safe to show in HTML (viewer escapes it).
- `step_start` and `step_done` pair by `index`.
- `summary` on `step_done` is phase-specific opaque dict.
- No `url_probe` or other custom event types — if a phase needs multi-stage substeps it emits a `step_done` then a new `step_start`. Don't invent new event types.

---

## Public API

```python
from progress import ProgressEmitter, NullEmitter, ProgressState, parse_progress
```

### `ProgressEmitter(path: Path)`

Truncates `path` on construction (each run owns its log). Provides:

- `emit_run_start(phase, total_steps)`
- `emit_step_start(index, total, name, detail=None)`
- `emit_step_done(index, name, duration_ms, summary)`
- `emit_run_done(ok, summary)`

### `NullEmitter`

No-op drop-in (tests / programmatic use without a log file).

### `parse_progress(path: Path) -> ProgressState`

Reads `path` (missing file → neutral state), skips malformed lines. Returns:

```python
class ProgressState:
    phase: str | None
    total_steps: int | None
    current_index: int | None
    current_name: str | None
    current_detail: str | None
    completed_steps: int
    in_progress: bool
    done: bool
    ok: bool | None
    summary: dict
    events_seen: int
```
