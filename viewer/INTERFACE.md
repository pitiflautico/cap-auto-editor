# Viewer — v6/viewer/

## Changelog v3.0.1 (patch)

**FROZEN v3.0.1 — 2026-04-24.**

- Added three new cell formatters in `_process_table_rows` (`app.py`):
  - `list_length`: returns `len(value)` for list fields (or 0 if not a list). Used by `Beat.broll_hints` column.
  - `list_count_by_type`: summarises a list of typed dicts as `"type×N, ..."`. Used for `list_count_by_type` format in future artifact columns.
  - `join_csv`: joins a list of strings with `", "`. Used by `ArcAct.topic_focus` column.
- +12 new regression tests in `test_formatters_v11.py` (48 total, all green).

## Changelog v3.0

**FROZEN v3.0 — 2026-04-24.**

- `pipeline_manifest.json` is now the primary source of truth for what to render on `GET /pipeline/{name}`. The viewer reads the manifest and renders each phase's `render_artifacts` generically based on `type`.
- Generic artifact renderers: `transcript`, `json_table`, `image_gallery`, `text_preview`, `key_value`, `iframe`. Each type has a dedicated rendering block in `pipeline_run.html`.
- Legacy runs (no `pipeline_manifest.json`) still supported via the existing hardcoded per-phase preview panes (capture + polish + unknown).
- New `_load_pipeline_manifest(run_path)`, `_render_artifact(artifact, phase_dir)`, `_process_table_rows()`, `_safe_json()`, `_safe_text()` helpers in `app.py`.
- All artifact renderers degrade gracefully: missing file → `(not available yet)` span; malformed JSON → `None` (shown as not available).
- Phase detail view augmented with `artifacts` list in addition to existing `preview` dict.
- +6 new tests in `test_pipeline_manifest_rendering.py` (36 total, all green).

## Changelog v2.1

**FROZEN v2.1 — 2026-04-24.**

- Added `launcher.py` with `ensure_running()` and `open_pipeline()` for auto-start + auto-browser-open. Used by `v6/pipeline/` orchestrator.
- `ensure_running(port, roots, timeout_s)`: socket probe → Popen uvicorn detached if not up → waits for HTTP 200 → returns base URL. Idempotent.
- `open_pipeline(run_name, port, roots)`: `ensure_running` + `webbrowser.open(pipeline_url)`. Returns URL.
- +6 new tests in `test_launcher.py`.

## Changelog v2.0

**FROZEN v2.0 — 2026-04-24.**

- **Unified pipeline layout**: a "pipeline run" is any directory containing at least one child directory with a `progress.jsonl`. The pipeline run's name is its basename. Phases are the child dirs. Example: `/tmp/live_demo/` → pipeline `live_demo`, phases: `capture`, `polish`.
- **New primary route `GET /`**: lists all discovered pipeline runs as cards. Each card shows pipeline name, phase badges with status indicators (grey = not started, blue = live, green = done, red = failed), and `created_at`. Auto-refresh every 2s via HTMX.
- **New route `GET /pipeline/{name}`**: unified detail page. Renders all phases stacked vertically — each phase shows header (name + status + step count + elapsed), step list (done/active/pending rows), and a phase-specific preview pane. For capture: captured URL list with thumbnails. For polish: transcript excerpt + applied corrections (`transcript_patches.json`) + unresolved entity candidates (`entity_candidates.json`). Unknown phases: file list. All preview panes are collapsible via `<details>`.
- **New route `GET /pipeline/{name}/progress`**: HTMX fragment returning per-phase status badges. Polled every 2s.
- **New routes `GET /pipeline/{name}/{phase}/screenshot/{slug}`** and **`/pipeline/{name}/{phase}/text/{slug}`**: binary serving for pipeline-scoped phase artefacts.
- **Canonical phase order**: `capture, polish, analysis, broll_plan, builder` — unknown phases appended alphabetically.
- **Legacy runs retained**: single-phase runs at root level (with `progress.jsonl` or `timeline_map.json` directly in the run dir) appear as single-phase pipelines with the run dir name as the pipeline name.
- **Back-compat routes kept**: `GET /run/{name}`, `GET /capture`, `GET /capture/{name}`, and their sub-routes remain fully functional.
- **Polish preview additions**: applied corrections table from `transcript_patches.json` (surface_form → canonical, layer, occurrences, confidence) and unresolved entity candidates from `entity_candidates.json` (surface_form, occurrences, first_time mm:ss, evidence tags). Both collapsible. Empty state shown when no data.
- 9 new tests (24 total, all green).

## Changelog v1.1

**FROZEN v1.1 — 2026-04-24.**

- Unified progress parser via `v6/progress/` package: `_parse_progress` and `_parse_polish_progress` replaced by a single `parse_progress(path)` from the shared package. One parser, one fragment renderer (`_progress_fragment_html`) used by both capture and polish.
- Progress file renamed to `progress.jsonl` (was `capture_progress.jsonl` / `polish_progress.jsonl`). Clean break — no aliases.
- Discovery now keys off `progress.jsonl` as primary marker so live runs are visible from step 1. Legacy markers (`timeline_map.json`, `capture_manifest.json`) remain as fallbacks for pre-v2 runs.
- `live_status` string now visible on index cards (e.g. `"step 3/7 — transcribe · running whisper on audio.wav"` while live; `"done: 4.99% saved"` when complete).
- `phase` field propagated from `progress.jsonl` → run dict → template.
- 8 new regression tests (15 total).

> **STATUS: FROZEN v3.0 — 2026-04-24**
>
> Interfaz de contrato. Cualquier cambio de rutas, archivos leídos o
> comportamiento de polling requiere actualizar este documento primero
> y bumpear la versión.
>
> **v1.0 (inicial):** viewer read-only sobre runs de polish y capture.
> Polling HTMX para progreso en vivo de ambas fases. Sin escritura a
> disco. HTMX via CDN, Tailwind via CDN.
>
> **v1.0.1 (patch):** `_find_run` y `_find_capture_run` ahora buscan
> con `rglob` para coincidir con `_discover_*`. Antes resolvían solo
> runs ubicados directamente bajo un root configurado; ahora encuentran
> runs en cualquier profundidad, lo que habilita layouts como
> `<root>/<session>/{capture,polish}/`. Añadidos 7 tests de regresión
> (`tests/test_find_runs.py`).

---

## Propósito

Dado un conjunto de directorios de runs producidos por `polish/` y
`capture/`, **renderizar su contenido de forma navegable** en una web
local. Permite inspeccionar timeline, transcripción, candidatos de
entidad, artefactos de captura y progreso en vivo de un run activo.

El viewer es **read-only y sin estado**. No orquesta, no lanza procesos,
no escribe nada a disco. Es un espejo de lo que hay en disco.

---

## Responsabilidad

**Hace:**
- Descubrir runs de polish (directorios con `timeline_map.json`) en
  las raíces configuradas.
- Descubrir runs de capture (directorios con `capture_manifest.json`)
  en las mismas raíces.
- Renderizar listados, detalle de run, timeline visual, transcripción
  polished, candidatos de entidad, tabla de resultados de capture.
- Servir fragmentos HTMX para progreso en vivo de capture y polish,
  con polling a 1500 ms.
- Servir artefactos binarios: audio fuente, screenshots, texto capturado.

**No hace:**
- Escribir, modificar ni borrar ningún fichero en disco.
- Lanzar ni monitorizar procesos del pipeline.
- Autenticar usuarios ni controlar acceso.
- Agregar, resumir ni transformar los datos más allá de lo necesario
  para renderizarlos.
- Inferir entidades, analizar transcriptos ni editar timelines.

**Regla dura:** el viewer **no muta disco**. Cualquier ruta que
reciba un body o emita una escritura es un bug. Es estrictamente
`GET`-only.

---

## Inputs

### Variables de entorno / configuración

| Variable | Default | Descripción |
|---|---|---|
| `VIEWER_ROOTS` | `/tmp` | Rutas separadas por `:` donde buscar runs. Ej.: `/tmp:/data/runs` |

### Convención de pipeline run (v2.0)

Un **pipeline run** se descubre cuando al menos un directorio hijo de la raíz contiene un `progress.jsonl`. El nombre del pipeline es el `basename` del directorio padre. Las fases son los directorios hijos.

- `/tmp/live_demo/capture/progress.jsonl` → pipeline `live_demo`, fase `capture`.
- Las fases futuras (`analysis/`, `broll_plan/`, `builder/`) se incluyen automáticamente sin cambios en el viewer.
- Un run directamente bajo la raíz (con `progress.jsonl` o `timeline_map.json` en el propio dir) es un pipeline de una sola fase cuyo nombre es el `basename` del directorio.

### Archivos leídos por run de polish

El viewer descubre un run de polish cuando encuentra `timeline_map.json`
en un subdirectorio de alguna raíz. Una vez descubierto, lee los
siguientes archivos si existen (los faltantes se ignoran gracefully):

| Fichero | Descripción |
|---|---|
| `timeline_map.json` | Fuente de verdad: duración, cuts, fuente de vídeo, created_at |
| `summary.json` | Métricas compactadas: pct_saved, active_cuts, entity_candidates |
| `transcript_polished.json` | Segmentos polished con start_s, end_s, text |
| `transcript_raw.json` | Transcripción raw de Whisper (solo para descarga raw) |
| `transcript_patches.json` | Patches aplicados al transcript (solo para descarga raw) |
| `entity_candidates.json` | Candidatos de entidad detectados |
| `polish_progress.jsonl` | Progreso en vivo (ver Contratos). Puede estar ausente en runs viejos. |

### Archivos leídos por run de capture

El viewer descubre un run de capture cuando encuentra
`capture_manifest.json`. Lee:

| Fichero | Descripción |
|---|---|
| `capture_manifest.json` | Manifest principal con results, backend, created_at |
| `captures/<slug>/screenshot.png` | Servido como imagen en la tabla de resultados |
| `captures/<slug>/text.txt` | Servido como texto plano |
| `capture_progress.jsonl` | Progreso en vivo de capture. Puede estar ausente. |

### Archivos fuente de media

El path `source_video_path` de `timeline_map.json` se sirve directamente
vía `FileResponse`. El viewer no copia ni re-encoda el archivo.

---

## Outputs (rutas HTTP)

El viewer expone únicamente rutas `GET`. Todas devuelven HTML, un
fragmento HTMX o un binario. No hay API JSON.

### Pipeline runs (v2.0 — rutas primarias)

| Ruta | Descripción |
|---|---|
| `GET /` | Listado de todos los pipeline runs descubiertos. Cada card muestra fases con badges de estado. Auto-refresh HTMX 2s. |
| `GET /pipeline/{name}` | Detalle unificado: todas las fases apiladas. Step list + preview pane (capture thumbnails, polish transcript/corrections/candidates). |
| `GET /pipeline/{name}/progress` | Fragmento HTMX: badges de estado por fase. Polled cada 2s. |
| `GET /pipeline/{name}/{phase}/screenshot/{slug}` | Screenshot PNG de capture (con path-traversal guard) |
| `GET /pipeline/{name}/{phase}/text/{slug}` | Texto capturado de capture (con path-traversal guard) |

### Legacy routes (back-compat — retained)

| Ruta | Descripción |
|---|---|
| `GET /run/{run_name}` | Detalle de run de polish (legacy single-phase detail) |
| `GET /run/{run_name}/progress` | Fragmento HTMX: progreso de polish |
| `GET /run/{run_name}/media/audio` | Audio/video fuente del run |
| `GET /run/{run_name}/raw/{fname}` | Artefacto JSON del run |
| `GET /capture` | Listado de runs de capture (legacy) |
| `GET /capture/{run_name}` | Detalle de capture run (legacy) |
| `GET /capture/{run_name}/progress` | Fragmento HTMX: progreso de capture |
| `GET /capture/{run_name}/screenshot/{slug}` | Screenshot PNG (con path-traversal guard) |
| `GET /capture/{run_name}/text/{slug}` | Texto capturado del slug |

---

## Contratos

### `timeline_map.json` (leído por el viewer)

El viewer usa los siguientes campos; ignora el resto:

```
{
  "schema_version": "1.0.0",
  "created_at": "<ISO 8601>",
  "source_video_path": "<ruta absoluta>",
  "total_original_duration_s": <float>,
  "total_edited_duration_s": <float>,
  "cut_regions": [
    {"id": <str>, "start_s": <float>, "end_s": <float>,
     "action": "cut"|"keep", "reason": <str>, "confidence": <float>}
  ]
}
```

Si falta cualquier campo, el viewer muestra `—` o `0` en su lugar.
No falla con 500.

### `capture_manifest.json` (leído por el viewer)

```
{
  "schema_version": "2.0.0",
  "created_at": "<ISO 8601>",
  "sources_file": "<ruta>|null",
  "out_dir": "<ruta>",
  "backend_default": "<str>",
  "results": [
    {
      "request": {"slug": "<str>", "url": "<str>"},
      "status": "ok"|"failed"|"skipped_cache",
      "backend": "<str>",
      "duration_ms": <int>|null,
      "artifacts": {"screenshot_path": "<str>|null", "text_path": "<str>|null"},
      "error": "<str>|null",
      "error_class": "<str>|null"
    }
  ]
}
```

### `polish_progress.jsonl` (polling fragment)

Una línea JSON por evento. El viewer lee todas las líneas al momento
del request; líneas malformadas se ignoran.

Eventos esperados:

```jsonl
{"type":"run_start","ts":"<ISO>","total_steps":7}
{"type":"step_start","ts":"<ISO>","index":<1-7>,"total":7,"name":"transcribe"|"normalize"|"project_aliases"|"entity_candidates"|"silences"|"cuts"|"timeline"}
{"type":"step_done","ts":"<ISO>","index":<1-7>,"name":"<str>","duration_ms":<int>,"summary":{...}}
{"type":"run_done","ts":"<ISO>","edited_s":<float>,"pct_saved":<float>,"entity_candidates":<int>}
```

El viewer determina "in_progress" como: existe `run_start`, NO existe
`run_done`, y hay al menos un `step_start` sin `step_done` pareado
por `index`.

El campo `total_steps` de `run_start` se usa como denominador de la
barra de progreso; si ausente, se asume 7.

### `capture_progress.jsonl` (polling fragment)

Eventos esperados:

```jsonl
{"type":"run_start","ts":"<ISO>","total_urls":<int>}
{"type":"url_start","ts":"<ISO>","slug":"<str>","url":"<str>","backend":"<str>"}
{"type":"url_done","ts":"<ISO>","slug":"<str>","status":"ok"|"failed"|"skipped_cache"}
{"type":"run_done","ts":"<ISO>","ok":<int>,"failed":<int>,"skipped_cache":<int>}
```

---

## Garantías

- **No-mutación de disco**: el viewer nunca abre ningún archivo con
  modo escritura. No crea directorios. Todas las operaciones son
  `read_text()`, `json.loads()` o `FileResponse`.
- **Degradación graceful**: si un artefacto no existe, el campo se
  omite silenciosamente en la UI. No hay 500 por archivo faltante.
- **Path-traversal guard**: las rutas de screenshot y texto de capture
  se resuelven con `.resolve()` y se verifica que el path resultante
  comience con `run_path.resolve()` antes de servir.
- **Descubrimiento incremental**: cada request a `/` o `/capture` re-
  escanea las raíces. Nuevos runs aparecen sin reiniciar el servidor.
- **Polling no bloqueante**: los fragmentos de progreso son stateless.
  Cada request lee el JSONL completo desde disco. Apropiado para
  JSONL de decenas de líneas; no escala a millones.

## No-garantías

- **No orquesta**: el viewer no sabe si un run está "colgado". Un
  `polish_progress.jsonl` con `step_start` sin `run_done` se muestra
  como "in_progress" aunque el proceso haya muerto.
- **No valida schemas**: no usa Pydantic ni JSONSchema. Si un artefacto
  tiene un campo con tipo inesperado, el template Jinja2 puede mostrar
  el valor crudo.
- **No sirve video editado**: solo sirve la fuente original. El vídeo
  editado (salida de polish/ffmpeg) no está en la interfaz.
- **No agrega runs de múltiples directorios en un mismo nombre**: si
  dos raíces tienen un directorio con el mismo nombre, la primera raíz
  gana.

---

## Dependencias

| Dependencia | Versión | Uso |
|---|---|---|
| `fastapi` | latest | Router, `HTTPException`, `FileResponse`, `HTMLResponse` |
| `uvicorn[standard]` | latest | Servidor ASGI con `--reload` |
| `jinja2` | latest (via fastapi) | Motor de templates |
| `htmx.org` | 2.0.3 (CDN) | Polling de fragmentos de progreso |
| `tailwindcss` | CDN | Estilos |

Sin base de datos. Sin workers. Sin websockets.

Arranque:

```
uvicorn viewer.app:app --reload --port 8765
# o bien:
viewer --port 8765 --roots /tmp:/data/runs
```

---

## Estructura del código

```
v6/viewer/
├── INTERFACE.md                  # este documento (FROZEN v1.0)
├── pyproject.toml
├── src/viewer/
│   ├── app.py                    # único módulo: helpers + routes
│   │   ├── _configured_roots()   # lee VIEWER_ROOTS
│   │   ├── _discover_runs()      # rglob timeline_map.json
│   │   ├── _load_run()           # carga todos los JSON de un run de polish
│   │   ├── _find_run()           # localiza run_path por nombre
│   │   ├── _parse_polish_progress()  # lee polish_progress.jsonl → dict|None
│   │   ├── _discover_capture_runs()  # rglob capture_manifest.json
│   │   ├── _find_capture_run()   # localiza run de capture por nombre
│   │   └── _parse_progress()     # lee capture_progress.jsonl → list[dict]
│   └── __init__.py
└── templates/
    ├── base.html                 # layout base: Tailwind CDN, HTMX CDN
    ├── index.html                # listado de runs de polish (badge "● live")
    ├── run.html                  # detalle de run de polish + polling progress
    ├── capture_index.html        # listado de runs de capture
    └── capture_run.html          # detalle de run de capture + polling progress
```
