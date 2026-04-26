# Phase 0 — polish/

## Changelog v2.2

**FROZEN v2.2 — 2026-04-24.**

- **Adaptive silence detection** is now the default. First pass runs `ffmpeg loudnorm` to measure `input_thresh`; second pass uses that value as the noise gate. Fixed -30dB mode still available via `mode="fixed"`. Expected effect: fewer over-cuts on quiet recordings.
- **`entity_resolution.py` implemented** using shared `v6/llm/` package. Default provider: `claude_pool` (Claude Code subscription, no API key). Model: `sonnet`. Single LLM call per video. Decision log written to `entity_resolutions.json`.
- **`project_aliases.yaml` deprecated** from the demo pipeline. The `--project-aliases` CLI flag is now a no-op with a `DeprecationWarning`. Code (`project_aliases.py`) is retained for direct import callers.
- **`entity_resolutions.json`** (new output) replaces `entity_candidates.json` as the "corrections decision log". Contains full LLM reasoning (canonical decision, confidence, evidence quote, one-line reasoning) for every candidate. `entity_candidates.json` still emitted for raw detection auditing.
- **Demo pipeline step count stays at 7**: `project_aliases` step dropped, `entity_resolution` (LLM) added between steps 3 and 4.
- **`ConfirmationSource` literal** in `contracts.py` extended with `"unresolved"` value.

## Changelog v2.0

**FROZEN v2.0 — 2026-04-24.** Breaking change of the progress artefact only;
`TimelineMap` schema is **unchanged**.

- Progress emission moved to shared `v6/progress/` package (`ProgressEmitter`/`NullEmitter` from `progress` module).
- Event schema unified: `run_start` now carries `phase="polish"` and `total_steps=7`; steps emit `step_start`/`step_done` with `detail` strings.
- Progress file renamed from `polish_progress.jsonl` → **`progress.jsonl`** (clean break; no alias).
- Each `step_start` now carries a user-facing `detail` string (e.g. `"running whisper on audio.wav"`).
- `run_done.summary` keys changed: now `{"edited_s", "pct_saved", "entity_candidates"}` inside `summary` dict.

## Changelog v1.2

**FROZEN v1.2 — 2026-04-24.** Backwards-compatible addition: new optional
auxiliary output `polish_progress.jsonl` emitted during pipeline runs.
No existing contract inputs or outputs changed.

> **STATUS: FROZEN v2.2 — 2026-04-24**
>
> Interfaz de contrato. Cualquier implementación de esta fase debe
> respetar las entradas, salidas y garantías descritas aquí.
> Esta documentación precede al código — cambios de interfaz
> requieren actualizar este documento primero y bumpear la versión.
>
> **Changelog v1.1:** diseño reajustado para vídeos de temática
> variada. initial_prompt pasa a ser genérico por idioma (no por tema).
> Aliases separados en `generic_aliases.yaml` (siempre activo) vs
> `project_aliases.yaml` (opcional). Entity resolution entra al MVP
> en 3 capas (aliases → candidates → LLM). Nueva regla dura: no se
> auto-corrige magnitud numérica sin evidencia externa. Nuevo output
> de trazabilidad `transcript_patches.json` que registra cada
> normalización aplicada al transcript raw.

---

## Propósito

Dado un vídeo crudo grabado con teleprompter (con silencios, muletillas,
retakes y posibles errores de transcripción de entidades técnicas),
producir una versión **limpia y sincronizada** del material con
trazabilidad total al original.

No decide qué es interesante, qué merece b-roll, ni cómo se estructura
el vídeo. Solo **limpia el habla** y **fija la ortografía canónica**
de las entidades mencionadas.

---

## Responsabilidad

**Hace:**
- Detectar silencios, muletillas, pausas ruidosas y retakes.
- Recortar esos rangos del vídeo original generando un vídeo editado.
- Remapear la transcripción al vídeo editado (sync por construcción).
- Resolver ortografía canónica de entidades con grounding web.
- Emitir señales lingüísticas objetivas (hechos detectados en el texto).

**No hace:**
- Decidir estructura narrativa.
- Seleccionar highlights o mejores momentos.
- Planificar b-roll, layouts o títulos.
- Asignar assets o efectos visuales.
- Emitir proyecto CapCut.

**Regla dura:** polish/ detecta **potencial**, no toma decisiones
editoriales. Si una función necesita modelar al espectador o al
catálogo de assets, no pertenece a esta fase.

---

## Inputs

| Input | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `video` | ruta a `.mp4` | Sí | Grabación original sin editar |
| `sources` | ruta a `.txt` o lista CLI | No | URLs opcionales que enriquecen el initial_prompt y el resolver |
| `project_aliases` | ruta a `.yaml` | No | Reemplazos específicos del proyecto/canal (coste 0, sin LLM) |
| `mode` | `auto_safe` \| `confirm` \| `strict` | No (default: `auto_safe`) | Ver sección "Modos de ejecución" |
| `config` | ruta a `.yaml` | No | Overrides de thresholds, padding, idioma |

### Formato de `sources.txt` (opcional)

Una URL por línea. Cero ceremonia:

```
https://blog.google/technology/developers/gemma-4-launch/
https://x.com/GoogleAI/status/1234567890
https://github.com/google-ai-edge/gallery
```

O equivalente por CLI: `polish run video.mp4 --source <url> --source <url>`.

**Filosofía**: no se pide al usuario que declare topics/entities por
adelantado. El sistema está diseñado para vídeos de **temática
variada** — nunca asume tema previo como default. Las sources
opcionales solo aportan señal cuando existen; si no, polish/ funciona
igual con un prompt 100 % genérico.

### initial_prompt — siempre genérico

El prompt por defecto sesga al decoder hacia **preservación de forma**,
no hacia contenido concreto. Texto base (idioma = es):

```
Transcripción en español. Mantén nombres propios, marcas, herramientas,
números y términos técnicos con la forma más probable. No traduzcas
nombres de productos. Conserva siglas y cifras.
```

Esto no introduce sesgo temático.

### Enriquecimiento opcional desde sources (si se aportan)

1. **Fetch ligero de metadata** — por cada URL, un GET HTTP que extrae
   `<title>` y `<meta name="description">`. Timeout 3 s/URL, paralelo,
   skip silencioso en fallos.
2. **Extracción de entidades candidatas del metadata** — tokens con
   capitalización no estándar, siglas, versiones (`Qwen 3.6`, `RTX 3090`).
3. **Prompt enriquecido** — se concatenan esas entidades al prompt
   genérico, manteniendo ≤224 tokens.
4. **Contexto extra para el resolver** — los mismos títulos se pasan
   al resolver de entidades como contexto adicional.

Sin sources, polish/ funciona igual. Con sources, la transcripción
de esas entidades concretas es más precisa.

---

## Outputs

### Canónicos (consumidos por `analysis/`)

| Fichero | Descripción |
|---|---|
| `transcript_polished.json` | Transcript word-level del vídeo editado con ortografía canónica aplicada. Sincronizado con `edited_video.mp4`. |
| `keep_segments.json` | Vista de las regiones del original que se han conservado, con mapeo original→editado. |
| `entity_resolution.json` | Formas canónicas de las entidades detectadas + surface forms + confianza + fuente + `confirmed_by`. |
| `speech_signals.json` | Detección lingüística objetiva en 4 categorías: `claims_detected`, `numeric_facts`, `entities_mentioned`, `discourse_markers`. |

### Auxiliares (siempre emitidos, trazabilidad)

| Fichero | Descripción |
|---|---|
| `timeline_map.json` | **Documento maestro.** Todos los cuts, todos los keeps, metadatos, detectores usados. Fuente de verdad de la edición. |
| `cut_map.json` | Vista derivada sobre timeline_map. Lista plana de regiones cortadas con razón/confianza/detector. Para QA humano. |
| `transcript_raw.json` | Transcript original sin normalizar. Input al resolver y al remap. |
| `transcript_patches.json` | **Nuevo en v1.1.** Registro de cada cambio de ortografía aplicado al transcript raw: `(surface_form, canonical, layer, confidence, source)`. Permite revertir cualquier patch y auditar por qué se aplicó. |
| `polish_progress.jsonl` | **Nuevo en v1.2.** Stream de eventos JSONL append-only emitido durante el run. Mismo formato que `capture_progress.jsonl`. Permite al viewer (u otro consumidor) reconstruir el estado del pipeline sin inspeccionar stdout. Eventos: `run_start`, `step_start`, `step_done`, `run_done`. |

### Opcionales

| Fichero | Descripción |
|---|---|
| `edited_video.mp4` | Vídeo con cortes aplicados. Se genera siempre si hay que entregarlo a downstream; si solo se entrega EDL, se omite. |
| `preview_polished.mp4` | Render rápido para revisión humana. **No es fuente de verdad.** |

### Regla de sincronización

`timeline_map.json` es el **único documento maestro**.
`keep_segments.json` y `cut_map.json` son **vistas derivadas** y se
regeneran desde él. Editar una vista sin regenerar el maestro deja
el sistema inconsistente.

---

## Contratos (Pydantic — referencia)

Los schemas canónicos viven en `contracts.py`. Resumen:

```python
class CutRegion(BaseModel):
    id: str
    start_s: float
    end_s: float
    reason: Literal["silence", "filler", "noisy_pause",
                    "retake", "false_start", "manual"]
    detector: str
    detector_version: str
    confidence: float            # 0.0 - 1.0
    action: Literal["cut", "compress", "keep"]
    padding_before_s: float = 0.12
    padding_after_s: float = 0.12
    affected_words: list[int]    # índices en transcript_raw
    notes: str | None = None

class KeepSegment(BaseModel):
    original_start_s: float
    original_end_s: float
    edited_start_s: float
    edited_end_s: float
    source_cut_ids_before: list[str]

class TimelineMap(BaseModel):
    schema_version: str
    created_at: datetime
    source_video_path: str
    edited_video_path: str | None
    transcript_original_ref: str           # path o sha256
    sources_used: list[str]                # URLs aportadas por el usuario
    detector_versions: dict[str, str]
    cut_regions: list[CutRegion]
    keep_segments: list[KeepSegment]
    total_original_duration_s: float
    total_edited_duration_s: float
    join_strategy: Literal["hard_cut", "micro_fade", "crossfade"]
    join_compensation_s: float = 0.0

class EntityResolution(BaseModel):
    canonical: str                         # "Gemma 4"
    surface_forms: list[str]               # ["Genma", "genma"]
    confidence: float
    source_url: str | None
    confirmed_by: Literal["llm", "human", "briefing", "auto_accept"]

class SpeechSignal(BaseModel):
    signal_type: Literal["claim_detected", "numeric_fact",
                         "entity_mentioned", "discourse_marker"]
    start_s: float
    end_s: float
    text: str
    evidence_spans: list[tuple[int, int]]  # word_idx ranges
    confidence: float
```

### Función pura obligatoria

```python
def remap_transcript(
    transcript_raw: Transcript,
    timeline_map: TimelineMap,
) -> Transcript:
    """Determinista, idempotente, pura.

    Descarta words dentro de cut_regions. Recalcula start/end
    restando las duraciones cortadas previas más join_compensation.
    Aplica entity_resolution para normalizar texto.
    """
```

Los tests de esta función blindan toda la fase: si `remap` es correcta,
la sincronización transcript↔vídeo está garantizada.

---

## Modos de ejecución

| Modo | Comportamiento | Uso típico |
|---|---|---|
| `auto_safe` **(default)** | Aplica cosméticos (clase A) siempre; entidades (clase B) con confianza ≥ umbral; numéricos de magnitud (clase C) **nunca** — solo warning. | CI / batch / producción diaria |
| `confirm` | Igual que `auto_safe` pero baja confianza pide confirmación en CLI. | Piezas cuidadas |
| `strict` | Toda corrección (incluso cosmética) requiere confirmación humana. | Cliente / piezas críticas |

Modo no-interactivo (`--no-tty`) degrada `confirm` y `strict` a
`auto_safe` y marca los casos dudosos como warnings.

### Clasificación de correcciones (regla dura)

| Clase | Ejemplo | Auto-aplicable |
|---|---|---|
| **A. Cosmético** | "GPT 5.5" → "GPT-5.5", "chat gpt" → "ChatGPT" | Sí, siempre |
| **B. Entidad** | "Cloud Code" → "Claude Code" | Sí solo si confidence ≥ threshold y contexto compatible |
| **C. Factual numérico** | "27 millones" → "27 mil millones" | **Nunca** sin evidencia externa explícita o confirmación humana |

La clase C es no-negociable: un cambio de magnitud numérica altera un
hecho. Se marca en `speech_signals.numeric_facts` con un warning
específico y se pasa tal cual al transcript polished.

### Pipeline de entity resolution (3 capas)

Capas aplicadas en orden, cada una puede resolver o marcar un
candidato como "dudoso" para la siguiente. Cada patch aplicado se
registra en `transcript_patches.json`.

1. **Capa 1 — `generic_aliases.yaml`** (siempre activa, coste 0).
   Reemplazos cosméticos universales del idioma. Lista corta y
   conservadora. Solo clase A.
2. **Capa 2 — `project_aliases.yaml`** (opcional, coste 0).
   Reemplazos específicos del proyecto/canal si el usuario aporta el
   fichero. Clase A y B con confidence "high".
3. **Capa 3 — `entity_candidates.py` + `entity_resolution.py`**
   (coste ~$0.002/vídeo si se usa LLM, o 0 si se desactiva).
   Detecta candidatos con NER + heurística (mayúsculas raras, siglas,
   tokens adyacentes a números). Solo los NO resueltos por las capas
   anteriores pasan al resolver LLM con grounding.

En modo offline (sin API keys), la capa 3 se salta silenciosamente;
los candidatos no resueltos quedan en `entity_resolution.json` como
`confirmed_by: "unresolved"` con el transcript preservando la forma
original.

---

## Garantías

- **Sincronización** transcript↔vídeo por construcción (testeable).
- **Trazabilidad total**: cada corte registra detector, versión,
  confianza y razón.
- **Reproducibilidad**: `timeline_map.json` + `sources_used` +
  `detector_versions` permiten regenerar la edición bit a bit.
- **No destructivo**: el vídeo original y el transcript raw se
  conservan siempre.
- **Determinismo** dado mismo input + misma configuración, misma
  salida (excepto el detector de retakes en modo LLM, que es
  estocástico — documentado como no-determinista).

## No-garantías

- **Calidad perceptual del corte**: requiere reglas de padding y
  revisión humana del `preview_polished.mp4`. El sync está garantizado;
  la musicalidad del corte no.
- **Precisión de la resolución de entidades**: depende del grounding
  web. Entidades muy nuevas o de nicho pueden no resolverse.
- **Detección de retakes sutiles**: el detector híbrido coge el ~80%;
  el resto requiere ojo humano o LLM assist.

---

## Dependencias

- `mlx-whisper` (large-v3) — transcripción local en Apple Silicon.
- `ffmpeg >= 7.0` — silencedetect, concat, acrossfade.
- `google-genai` — entity resolution con grounding (Gemini Flash).
- `anthropic` — opcional, para retakes con LLM assist (Haiku).
- `httpx` — fetch paralelo de metadata de sources (timeout 3s/url).
- `selectolax` (o `beautifulsoup4`) — extracción de `<title>`/`<meta>`.
- `pydantic >= 2.0`, `pyyaml`, `spacy` (es_core_news_md).

## Coste estimado por vídeo (10 min)

| Subsistema | Modelo | Coste |
|---|---|---|
| Transcribe | mlx-whisper local | $0 |
| Silencedetect | ffmpeg | $0 |
| Filler detector | listado local | $0 |
| Noisy pause | local | $0 |
| Retake determinista | local | $0 |
| Retake LLM assist (opcional) | Haiku, solo ventanas dudosas | ~$0.005 |
| Entity resolution | Gemini Flash + grounding, 1 call | ~$0.002 |
| **Total** | | **<$0.01** |

## Latencia estimada (10 min de audio, M4 Pro)

| Etapa | Tiempo |
|---|---|
| Fetch sources (paralelo, si aportadas) | ~2-5s |
| Transcribe | ~60s |
| Detectores | ~5s |
| Entity resolution | ~10s |
| Cut planner + remap + emit | ~1s |
| Preview render (opcional) | ~15s |
| **Total end-to-end** | **~75-95s** |

---

## Estructura del código (prevista)

```
v6/polish/
├── INTERFACE.md                  # este documento
├── pyproject.toml
├── config.yaml                   # thresholds por defecto
├── generic_aliases.yaml          # capa 1: reemplazos cosméticos universales
├── src/polish/
│   ├── contracts.py              # schemas Pydantic
│   ├── transcribe.py             # mlx-whisper wrapper + initial_prompt genérico
│   ├── sources.py                # fetch metadata + extracción de entidades
│   ├── detectors/
│   │   ├── silence.py            # ffmpeg silencedetect
│   │   ├── filler.py             # lista universal por idioma + context_dependent flags
│   │   ├── noisy_pause.py        # no_speech_prob + fillers largos
│   │   └── retake.py             # markers + fuzzy n-gram + LLM ventanas
│   ├── aliases.py                # apply generic + project aliases (capas 1 y 2)
│   ├── entity_candidates.py      # capa 3.a: NER + heurística (coste 0)
│   ├── entity_resolution.py      # capa 3.b: LLM + grounding (coste ~$0.002)
│   ├── cut_planner.py            # candidatos → cut/compress/keep + padding
│   ├── remap.py                  # función pura
│   ├── signals.py                # claims/numbers/entities/markers
│   ├── emit.py                   # timeline_map + vistas derivadas + patches
│   ├── preview.py                # ffmpeg concat opcional
│   └── cli.py                    # `polish run video.mp4`
└── tests/
    ├── test_contracts.py         # schemas + JSON roundtrip
    ├── test_remap.py             # invariantes de la función pura
    ├── test_aliases.py           # normalización determinista
    ├── test_detectors.py
    └── test_entity_resolution.py
```

---

## Lo que consume la siguiente fase (`analysis/`)

`analysis/` lee `transcript_polished.json`, `entity_resolution.json`,
`speech_signals.json` y opcionalmente `keep_segments.json`. Nunca lee
`timeline_map.json` (eso es trazabilidad interna de polish/).

`analysis/` emite estructura narrativa, topic segments, pacing notes y
broll opportunities. `polish/` no debe conocer nada de esas categorías.

---

## Versionado

- `schema_version` de TimelineMap empieza en `1.0.0`.
- Cambios backwards-compatible incrementan minor.
- Cambios breaking incrementan major y requieren migración
  documentada.
- Esta INTERFACE.md es versionada en git junto al código.
