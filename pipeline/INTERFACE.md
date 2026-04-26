# pipeline — Orquestador central de myavatar v6

> **STATUS: FROZEN v1.1 — 2026-04-24**
>
> Interfaz de contrato. Documentación precede al código — cambios de
> interfaz bumpean la versión antes de tocar el código.
>
> **v1.1 (2026-04-24):** Registered `analysis` phase (depends_on=["polish"]).
> Orchestrator picks it up automatically; viewer renders its artefacts via
> the generic renderer. No changes to the pipeline core — only a new
> descriptor in the registry.
>
> **FROZEN v1.0 (2026-04-24):** implementación completa. `pipeline run`
> E2E verificado: capture (50s) + polish (169s) + viewer auto-start +
> pipeline_manifest.json + orchestrator.jsonl. 32 tests verdes.
>
> **DRAFT v0.1 (inicial):** orquestador de los dos railes (ejecutor +
> visual). Input mínimo: vídeo + sources. Output: run_dir con
> artefactos + viewer abierto mostrando progreso live.

---

## Propósito

Un solo comando para todo el pipeline. El usuario solo aporta
**vídeo + fuentes**; el orquestador se encarga del resto:

```bash
pipeline run --video recording.webm --sources top2_sources.txt
```

Efecto:
1. Crea `/tmp/run_<name>/` con sub-dirs por fase.
2. Escribe `pipeline_manifest.json` describiendo qué fases hay y cómo
   se renderizan en el viewer.
3. Arranca el viewer (si no está) y abre el browser en
   `http://127.0.0.1:8765/pipeline/<run_name>`.
4. Lanza cada fase en orden respetando dependencias. Cada fase escribe
   sus artefactos + `progress.jsonl` unificado.
5. Registra trazas en `orchestrator.jsonl`: quién arrancó cuándo, quién
   acabó, quién falló.
6. Al terminar, deja el viewer vivo para inspección.

## Dos railes, una orquestación

```
┌────────────────┐    ┌───────────────┐    ┌────────────────┐
│   EJECUTORAS   │    │  ORQUESTADOR  │    │    VISUAL      │
│                │    │               │    │                │
│  capture       │    │   pipeline    │    │    viewer      │
│  polish        │    │               │    │                │
│  analysis      │──► │  run_dir      │ ──►│  render        │
│  broll_plan    │    │  pipeline     │    │  genérico      │
│  builder       │    │  manifest     │    │                │
│                │    │               │    │                │
└────────────────┘    └───────────────┘    └────────────────┘
  dumb workers         centralised brain     dumb renderer
  escriben disco       conoce fases + UI     lee disco
```

- **Ejecutoras** (`capture`, `polish`, `analysis`, `broll_plan`, `builder`):
  hacen su trabajo, emiten artefactos a su `<phase>/` dir. Agnósticas de UI.
- **Orquestador** (esta pieza): conoce el registry de fases, dependencias,
  cómo lanzarlas, y cómo se renderizan en el viewer.
- **Viewer**: genérico. Lee `pipeline_manifest.json` + artefactos.
  No conoce nombres de fase hardcoded; solo tipos de renderer.

Añadir fase nueva = **una entrada en el registry del orquestador**.
Cero cambios en fases existentes. Cero cambios en viewer.

---

## Inputs

| Input | Obligatorio | Descripción |
|---|---|---|
| `--video` | Sí | Ruta al vídeo crudo (.webm, .mp4, .mov) |
| `--sources` | No | Ruta a sources.txt (una URL por línea) |
| `--out-root` | No | Raíz donde crear run_dir. Default: `/tmp` |
| `--name` | No | Nombre del run. Default: `run_<timestamp>` |
| `--phases` | No | Subset de fases a correr (comma-separated). Default: todas. |
| `--no-open` | No | No abrir browser (para CI / no-tty). Default: abre. |
| `--port` | No | Puerto del viewer. Default: 8765. |

---

## Outputs

### Estructura del run_dir

```
/tmp/run_<name>/
├── pipeline_manifest.json      ← describe fases + render descriptors
├── orchestrator.jsonl          ← trazas del orquestador
├── capture/
│   ├── progress.jsonl
│   ├── capture_manifest.json
│   └── captures/<slug>/{text.txt,screenshot.png}
├── polish/
│   ├── progress.jsonl
│   ├── timeline_map.json
│   ├── transcript_polished.json
│   ├── transcript_patches.json
│   ├── entity_resolutions.json
│   └── ...
├── analysis/        ← futuro
├── broll_plan/      ← futuro
└── builder/         ← futuro
```

### `pipeline_manifest.json` (escrito por el orquestador)

```json
{
  "schema_version": "1.0.0",
  "run_name": "run_20260424_183012",
  "created_at": "<ISO 8601>",
  "video_input": "/abs/path/recording.webm",
  "sources_input": "/abs/path/top2_sources.txt",
  "phases": [
    {
      "name": "capture",
      "display_name": "Capture",
      "order": 1,
      "out_subdir": "capture",
      "depends_on": [],
      "render_artifacts": [
        {"type": "json_table", "title": "URLs",
         "path": "capture_manifest.json#results",
         "options": {"columns": [...]}},
        {"type": "image_gallery", "title": "Screenshots",
         "path_pattern": "captures/*/screenshot.png"}
      ]
    },
    {
      "name": "polish",
      "display_name": "Polish",
      "order": 2,
      "out_subdir": "polish",
      "depends_on": ["capture"],
      "render_artifacts": [
        {"type": "transcript", "title": "Transcripción",
         "path": "transcript_polished.json"},
        {"type": "json_table", "title": "Correcciones",
         "path": "transcript_patches.json"},
        {"type": "json_table", "title": "Entidades sin resolver",
         "path": "entity_resolutions.json"}
      ]
    }
    // analysis/broll_plan/builder cuando existan
  ]
}
```

El viewer lee este manifest y renderiza sin saber nada de polish ni capture.

### `orchestrator.jsonl` (trazas)

JSONL append-only. Eventos:

```jsonl
{"type":"run_start","ts":"...","run_name":"...","video":"...","sources":"..."}
{"type":"phase_launched","ts":"...","phase":"capture","cmd":["capture","run",...],"pid":12345}
{"type":"phase_completed","ts":"...","phase":"capture","duration_ms":58000,"exit_code":0}
{"type":"phase_failed","ts":"...","phase":"polish","duration_ms":12000,"error":"..."}
{"type":"run_done","ts":"...","ok":true,"duration_ms":180000}
```

El viewer puede leerlo para una barra de "progreso global" sobre todas las fases.

---

## Registry de fases

El registry vive en `v6/pipeline/src/pipeline/registry.py`. Una entrada por fase:

```python
@dataclass
class PhaseDescriptor:
    name: str                          # "capture"
    display_name: str                  # "Capture"
    order: int                         # 1, 2, 3 ...
    out_subdir: str                    # "capture" (relativo al run_dir)
    cli_command: list[str]             # ["capture", "run"] — se extiende con args
    cli_args: Callable[[RunContext], list[str]]  # construye args según inputs del run
    depends_on: list[str]              # nombres de fases requeridas antes
    on_failure: Literal["abort","skip","retry"]  # política
    retry_max: int = 0
    timeout_s: int = 600
    render_artifacts: list[RenderArtifact]  # descriptores para el viewer


# Registry actual
PIPELINE_PHASES: list[PhaseDescriptor] = [
    capture_descriptor,
    polish_descriptor,
    # analysis_descriptor,    # cuando exista
    # broll_plan_descriptor,  # cuando exista
    # builder_descriptor,     # cuando exista
]
```

**Añadir fase nueva = una entrada más aquí.** Nadie más se entera.

---

## Control de flujo

- **Orden**: topological sort por `depends_on`. Fases sin deps arrancan primero; el resto cuando sus deps están done.
- **Paralelismo**: v0.1 es secuencial. v1.x podrá paralelizar fases independientes.
- **Fallo de una fase**:
  - `on_failure="abort"` → para todo el run, `run_done.ok=false`.
  - `on_failure="skip"` → continúa sin fases dependientes.
  - `on_failure="retry"` → hasta `retry_max` veces con backoff 5s.
- **Kill**: `pipeline run` con Ctrl-C manda SIGTERM al subprocess activo; el orquestador graba `phase_failed` con `error="interrupted"`.

---

## Viewer integration

- Usa `v6/viewer/launcher.py` (pieza añadida en el mismo round que este paquete):
  - `ensure_running(port=8765) -> str` — Popen detached si no escucha.
  - `open_pipeline(run_name, port=8765) -> str` — ensure + `webbrowser.open()`.
- Con `--no-open`, solo hace `ensure_running()` (el viewer sigue subiendo pero no se abre browser).

---

## Tipos de render_artifact (consumidos por viewer)

Tipos predefinidos que el viewer sabe renderizar genéricamente:

| tipo | uso típico | options clave |
|---|---|---|
| `transcript` | word-level timestamps | `path` al JSON con segments/words |
| `json_table` | lista genérica como tabla | `columns: [{field,label,mono,badge,format}]` |
| `image_gallery` | múltiples imágenes | `path_pattern` glob |
| `text_preview` | primeros N chars de un .txt | `max_chars` |
| `key_value` | summary como tarjeta | `fields: [{key,label}]` |
| `iframe` | embed render final Remotion | `src_pattern` |

Añadir un tipo nuevo → bump `viewer` minor. No debería pasar a menudo — los 6 cubren 90 % de casos.

---

## Contratos (Pydantic — referencia)

```python
class PhaseDescriptor(BaseModel):
    name: str
    display_name: str
    order: int
    out_subdir: str
    cli_command: list[str]
    depends_on: list[str]
    on_failure: Literal["abort","skip","retry"]
    retry_max: int = 0
    timeout_s: int = 600
    render_artifacts: list[RenderArtifact]

class RenderArtifact(BaseModel):
    type: Literal["transcript","json_table","image_gallery",
                  "text_preview","key_value","iframe"]
    title: str
    path: str | None                 # ruta relativa al out_subdir
    path_pattern: str | None         # glob para gallery
    options: dict                    # options por tipo

class PipelineManifest(BaseModel):
    schema_version: str = "1.0.0"
    run_name: str
    created_at: datetime
    video_input: str
    sources_input: str | None
    phases: list[ManifestPhase]      # igual que PhaseDescriptor + resuelto para este run
```

---

## CLI

```bash
# Uso básico: todas las fases
pipeline run --video recording.webm --sources top2.txt

# Custom out dir
pipeline run --video r.webm --sources t.txt --out-root ~/videos --name top2_test

# Solo capture + polish (skip analysis/broll/builder)
pipeline run --video r.webm --sources t.txt --phases capture,polish

# CI / headless
pipeline run --video r.webm --sources t.txt --no-open

# Ver runs pasados
pipeline list
pipeline show <run_name>
```

---

## Garantías

- **Idempotencia del run_dir**: no sobreescribe un run existente; si ya existe, pide `--force` o cambia `--name`.
- **Trazabilidad total**: orchestrator.jsonl + cada progress.jsonl + artefactos de cada fase permiten reconstruir qué pasó y cuándo.
- **Fase faltante no bloquea**: si `analysis` no está instalada y no está en `--phases`, no se intenta lanzar.
- **Browser abre solo cuando viewer está listo**: socket probe hasta 200 OK antes del `open()`.

## No-garantías

- No paraleliza fases en v0.1 (se puede añadir después sin cambiar manifest).
- No reintenta transitoriamente fuera del `on_failure="retry"` declarado.
- No garantiza artefactos de fases saltadas (`--phases` subset).

---

## Dependencias

- `v6/progress/` — parser unificado (el viewer lo usa para cada fase).
- `v6/viewer/` — renderer + launcher.
- `v6/llm/` — solo indirectamente (fases que lo usan).
- Fases en PATH: `capture`, `polish` (sus CLIs). El orquestador hace `shutil.which()` y falla claro si faltan.

---

## Estructura del código (prevista)

```
v6/pipeline/
├── INTERFACE.md                    # este documento
├── pyproject.toml
├── src/pipeline/
│   ├── __init__.py
│   ├── contracts.py                # PhaseDescriptor, RenderArtifact, PipelineManifest
│   ├── registry.py                 # PIPELINE_PHASES — el registry
│   ├── descriptors/
│   │   ├── capture.py              # capture_descriptor
│   │   ├── polish.py               # polish_descriptor
│   │   └── __init__.py
│   ├── orchestrator.py             # planner + runner + tracer
│   ├── tracer.py                   # orchestrator.jsonl emitter
│   └── cli.py                      # `pipeline run ...`
└── tests/
    ├── test_registry.py
    ├── test_orchestrator.py        # dry-run con mocks de subprocess
    └── test_tracer.py
```

---

## Versionado

- `schema_version` de `PipelineManifest` empieza en `1.0.0`.
- Añadir fase nueva (registrarla) = minor bump.
- Cambio breaking del schema = major bump.
- Esta INTERFACE.md es versionada en git junto al código.
- Salto DRAFT v0.1 → FROZEN v1.0 solo tras revisión humana.
