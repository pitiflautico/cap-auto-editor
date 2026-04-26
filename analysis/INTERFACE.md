# analysis — Fase 1 de myavatar v6

> **STATUS: FROZEN v1.1 — 2026-04-24**
>
> Interfaz de contrato. Documentación precede al código.

## Changelog v1.1 (2026-04-24)

- **Schema bumped to 1.1.0.**
- **New models:** `BrollTiming`, `BrollHint`.
- **New fields:** `Beat.broll_hints: list[BrollHint]` (default `[]`), `ArcAct.topic_focus: list[str]` (default `[]`).
- **Backward compat:** both new fields default to `[]` — v1.0 outputs parse cleanly.
- **Prompt rewritten** in claude-code style English with short-form editorial discipline: 3-second hook rule (`beat[0].end_s ≤ 3.0`), beat sizing 3-5s target / 12s hard cap, mid-hooks at 15-30s, multi-topic awareness (detect ALL main topics, suffix act names with story tag), CapCut effect catalog, b-roll hint guidance per beat.
- **Domain hardcoding removed** from prompt — purely schema/type-driven.
- 42 tests green (was 30 passing before schema bump).

---

> **FROZEN v1.0 (2026-04-24):** implementación completa. `analysis run`
> E2E verificado: 1 call Claude Pool + analysis.json + progress.jsonl
> con 5 pasos. Registrado en pipeline como fase order=3. 32 tests verdes.
>
> **DRAFT v0.1 (inicial):** port del análisis narrativo de V4
> (`pipeline_v4_frozen_20260423/v4/transcript_analyze.py`) al estándar
> V6. Consume transcript polished y sources del capture; produce el
> "cerebro editorial" — arc + beats + topics + entities — para que
> `broll_plan/` y `builder/` planifiquen visuales y monten el vídeo.

---

## Propósito

Dado un `transcript_polished.json` (del polish) y opcionalmente un
`capture_manifest.json` (sources aportadas), producir la
**descomposición editorial** del vídeo:

- **Arc narrativo**: actos (Hook, Problem, Solution, Payoff, Closure, …).
- **Beats**: unidades de 3-12s que tilean todo el audio, cada una con
  editorial_function + hero_text_candidate + energy + topic_ids.
- **Topics**: temas principales (`role="main"`) y de apoyo
  (`role="supporting"`) con su kind.
- **Entities**: canonical + surface_forms + kind + (opcional) official URLs.

Sin audio — el transcript viene ya limpio de polish. Sin re-transcribir.

## Responsabilidad

**Hace:**
- 1 call a un LLM (default: Claude Pool) con el transcript + contexto de sources.
- Valida el output contra el schema Pydantic.
- Emite `analysis.json` canónico + `progress.jsonl` unificado.
- Post-processing determinista mínimo: split de beats > 12s, tile
  coverage del audio, consolidación de duplicados consecutivos.

**No hace:**
- Re-transcribir (eso es polish).
- Resolver entidades (eso es polish).
- Descargar assets visuales (eso es broll_plan).
- Decidir layouts / títulos / efectos (eso es builder).
- Orquestar nada (eso es pipeline).

**Regla dura:** los beats tilean el audio sin gaps. Si hay silencio
entre palabras, vive dentro del beat que lo precede, no entre beats.

---

## Inputs

| Input | Obligatorio | Descripción |
|---|---|---|
| `--transcript` | Sí | Ruta a `transcript_polished.json` |
| `--capture-manifest` | No | Ruta a `capture_manifest.json` — sus `text.txt` se pasan como contexto al LLM |
| `--out-dir` | Sí | Directorio destino (crea `analysis.json`, `progress.jsonl`) |
| `--language` | No (default `es`) | Idioma del transcript |
| `--llm-provider` | No (default `claude_pool`) | `claude_pool` \| `anthropic_api` \| `gemini` \| `openai` |
| `--llm-model` | No (default `sonnet`) | Modelo dentro del provider |

---

## Outputs

### Canónico

| Fichero | Descripción |
|---|---|
| `analysis.json` | **Documento maestro.** arc_acts + beats + topics + entities + metadata. Consumido por `broll_plan/`. |
| `progress.jsonl` | Stream de eventos JSONL (5 steps: load → prompt → llm_call → validate → postprocess). |

### Schema `analysis.json` (Pydantic)

Idéntico al de V4, schema version **1.0.0**:

```python
class ArcAct(BaseModel):
    name: str                        # "Hook", "Problem", "Solution", ...
    start_s: float
    end_s: float
    purpose: str                     # frase descriptiva, no keyword

class Beat(BaseModel):
    beat_id: str                     # "b001", "b002", ...
    start_s: float
    end_s: float                     # ≤ start_s + 12.0 (regla dura)
    text: str                        # transcript literal del beat
    editorial_function: Literal["hook", "pain", "solution", "proof",
                                 "value", "how_to", "thesis",
                                 "payoff", "transition"]
    hero_text_candidate: str | None  # 2-9 palabras del texto literal, Sentence case
    energy: Literal["high", "medium", "low"]
    references_topic_ids: list[str]

class Topic(BaseModel):
    topic_id: str                    # lowercase_snake_case
    label: str                       # "Qwen 3.6 27B"
    description: str                 # 1-2 sentences
    role: Literal["main", "supporting"]
    kind: Literal["product", "company", "person", "concept",
                  "platform", "sector", "event"]
    mentioned_in_beats: list[str]

class Entity(BaseModel):
    canonical: str
    surface_forms: list[str]
    kind: Literal["product", "company", "person", "platform",
                  "sector", "concept"]
    mentioned_in_beats: list[str]
    official_urls: list[str] = []

class Narrative(BaseModel):
    video_summary: str
    narrative_thesis: str
    audience: str
    tone: str
    arc_acts: list[ArcAct]
    beats: list[Beat]
    topics: list[Topic]
    entities: list[Entity]

class AnalysisResult(BaseModel):
    schema_version: str = "1.0.0"
    created_at: datetime
    transcript_ref: str              # path al transcript_polished.json
    capture_manifest_ref: str | None
    language: str
    duration_s: float
    llm_provider: str
    llm_model: str
    narrative: Narrative
```

---

## Prompt design

Port del prompt de V4 `transcript_analyze.py` con adaptaciones:

- Se elimina "You are listening to audio" → recibe transcript textual.
- Se elimina "Use Google Search" → Claude Pool no tiene grounding (entidades ya resueltas por polish).
- Se mantiene TODO lo demás: arc_acts tile the audio, beats 3-12s hard cap, one hook per beat, retakes como transition beats, hero_text_candidate de 2-9 palabras, topics role main/supporting, entities canonical + surface_forms.

El prompt vive en `src/analysis/prompts.py` como constante `ANALYSIS_PROMPT`. Versionado con el paquete.

**Contexto que recibe el LLM:**

1. Transcript polished con timestamps por segment (no word-level — demasiado ruido; los segments de 3-10s son suficientes para que el LLM razone sobre beats).
2. Por cada source capturada, primeros ~1500 chars del `text.txt` + title (primera línea del text). Esto ancla las entidades y evita que el LLM invente topics irrelevantes.
3. `duration_s` y `language` como metadata.

---

## Modos de ejecución

| Modo | Comportamiento | Uso |
|---|---|---|
| `auto` **(default)** | 1 call LLM + validate + postprocess + emit. Si falla validation, 1 retry con reminder del schema. | producción |
| `dry_run` | Imprime el prompt y la config; no llama al LLM. | debug |

Flag `--no-sources` desactiva el contexto de sources si el capture manifest existe pero no quieres usarlo.

---

## Garantías

- **Tile coverage**: beats[i].end_s ≈ beats[i+1].start_s (gap ≤ 0.15s). Post-processing determinista corrige gaps/overlaps mínimos.
- **12s hard cap**: cualquier beat > 12s se split deterministicamente en el silencio más largo interno.
- **schema_version** en analysis.json permite migraciones.
- **Determinismo para misma entrada**: `temperature=0` en el LLM; mismo transcript + sources → mismo analysis (salvo stochasticity inherente del provider).

## No-garantías

- Calidad editorial perfecta: el arc/beats dependen del LLM. Haikus raros o transcripts muy cortos pueden producir arc_acts con purposes genéricos.
- Entity URLs: si el LLM no las conoce (no tiene grounding) quedan como lista vacía. Broll_plan puede inferirlas desde capture_manifest si hace falta.

---

## Dependencias

- `v6/progress/` — emisión de progress.jsonl.
- `v6/llm/` — provider + complete(). Default Claude Pool.
- `pydantic >= 2.0` para schemas.

## Coste estimado

| Provider | Call | Coste |
|---|---|---|
| `claude_pool` (Sonnet) | 1 | $0 (subscription) |
| `anthropic_api` (Sonnet) | 1 | ~$0.015/vídeo |
| `gemini` (2.5 Pro) | 1 | ~$0.005/vídeo |

## Latencia estimada

| Fase | Tiempo |
|---|---|
| Load transcript + sources | <100 ms |
| Build prompt | <10 ms |
| LLM call (Sonnet) | 15-40 s |
| Validate + postprocess | <200 ms |
| **Total** | **15-40 s** |

---

## Consumidores downstream

### `broll_plan/` (fase 2, futura)

Lee `analysis.json`, usa beats + topics + entities para planificar qué
b-roll va en cada beat. El `hero_text_candidate` se convierte en
overlay animado; `topics.role=="main"` define las búsquedas de b-roll
principales; los `official_urls` de entities son fuentes de screenshots
si no están ya capturadas.

### `builder/` (fase 3, futura)

Lee `analysis.json` + output de broll_plan. El `arc_acts` define la
estructura temporal, los beats definen los cuts con overlays.

---

## Estructura del código (prevista)

```
v6/analysis/
├── INTERFACE.md
├── pyproject.toml
├── src/analysis/
│   ├── __init__.py
│   ├── contracts.py          # Pydantic: Beat, Topic, Entity, ArcAct, Narrative, AnalysisResult
│   ├── prompts.py            # ANALYSIS_PROMPT (port de V4 _PROMPT, adaptado)
│   ├── analyzer.py           # run(transcript, sources, llm_provider) -> AnalysisResult
│   ├── postprocess.py        # split_long_beats, tile_coverage, consolidate_duplicates
│   └── cli.py                # `analysis run ...`
└── tests/
    ├── test_contracts.py
    ├── test_prompts.py       # snapshot del prompt contra el de V4
    ├── test_postprocess.py   # split 12s, tile, duplicates
    └── test_analyzer.py      # mock LLM, end-to-end mocked
```

---

## Integración en el orquestador (cuando FROZEN v1.0)

Una entrada en `v6/pipeline/src/pipeline/descriptors/analysis.py`:

```python
analysis_descriptor = PhaseDescriptor(
    name="analysis",
    display_name="Analysis",
    order=3,
    out_subdir="analysis",
    cli_command=[".../analysis/.venv/bin/analysis", "run"],
    cli_args_fn=lambda ctx: [
        "--transcript", str(ctx.run_dir / "polish" / "transcript_polished.json"),
        "--capture-manifest", str(ctx.run_dir / "capture" / "capture_manifest.json"),
        "--out-dir", str(ctx.phase_out_dir),
    ],
    depends_on=["polish"],
    on_failure="abort",
    timeout_s=120,
    render_artifacts=[
        RenderArtifact(type="key_value", title="Narrativa",
                       path="analysis.json", options={"fields": [
                           {"key": "narrative.video_summary", "label": "Resumen"},
                           {"key": "narrative.narrative_thesis", "label": "Tesis"},
                           {"key": "narrative.audience", "label": "Audiencia"},
                           {"key": "narrative.tone", "label": "Tono"},
                       ]}),
        RenderArtifact(type="json_table", title="Arc (actos)",
                       path="analysis.json", options={
                           "root_path": "narrative.arc_acts",
                           "columns": [
                               {"field": "name", "label": "Acto", "badge": True},
                               {"field": "start_s", "label": "Start", "format": "seconds"},
                               {"field": "end_s", "label": "End", "format": "seconds"},
                               {"field": "purpose", "label": "Propósito", "truncate": 100},
                           ]}),
        RenderArtifact(type="json_table", title="Beats",
                       path="analysis.json", options={
                           "root_path": "narrative.beats",
                           "columns": [
                               {"field": "beat_id", "label": "ID", "mono": True},
                               {"field": "start_s", "label": "Start", "format": "seconds"},
                               {"field": "end_s", "label": "End", "format": "seconds"},
                               {"field": "editorial_function", "label": "Función", "badge": True},
                               {"field": "energy", "label": "Energía", "badge": True},
                               {"field": "hero_text_candidate", "label": "Hero text"},
                               {"field": "text", "label": "Texto", "truncate": 80},
                           ]}),
        RenderArtifact(type="json_table", title="Topics",
                       path="analysis.json", options={
                           "root_path": "narrative.topics",
                           "columns": [
                               {"field": "label", "label": "Topic"},
                               {"field": "role", "label": "Rol", "badge": True},
                               {"field": "kind", "label": "Kind", "badge": True},
                               {"field": "description", "label": "Descripción", "truncate": 120},
                           ]}),
        RenderArtifact(type="json_table", title="Entities",
                       path="analysis.json", options={
                           "root_path": "narrative.entities",
                           "columns": [
                               {"field": "canonical", "label": "Canonical", "mono": True},
                               {"field": "kind", "label": "Kind", "badge": True},
                               {"field": "surface_forms", "label": "As heard"},
                               {"field": "official_urls", "label": "URLs"},
                           ]}),
    ],
)
```

---

## Versionado

- `schema_version` en `AnalysisResult` empieza en `1.0.0`.
- Cambios backwards-compat → minor bump.
- Cambios breaking → major bump + migración documentada.
- DRAFT → FROZEN tras validación humana.
