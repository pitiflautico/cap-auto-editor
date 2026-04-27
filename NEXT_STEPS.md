# V6 — NEXT STEPS

> Documento vivo. Actualizar al cerrar cada sesión.
> Repo: https://github.com/pitiflautico/cap-auto-editor

---

## Instrucción de arranque (próxima sesión)

```
Lee v6/NEXT_STEPS.md.
Estado actual: pipeline 11 fases registradas, 436 tests verde,
último freeze pushado en v0.2.0 + commits post-freeze (broll_matcher,
storyboard, fixes variety+type gate, viewer file endpoint, etc.).
La carpeta v6/ es la unidad versionada del repo cap-auto-editor.
Wrapper único: ./myavatar produce <video> [--sources urls.txt].
Runs viven en ~/myavatar/runs/<name>/.
Viewer: http://127.0.0.1:8765 (auto-launch desde ./myavatar).
```

---

## Pipeline actual (11 fases)

| # | Fase | Output principal |
|---|---|---|
| 1 | `capture` | `capture_manifest.json` + screenshot/text/media + `media_audit.json` |
| 2 | `polish` | `transcript_polished.json` (whisper auto-lang, entity discover) |
| 3 | `analysis` | `analysis.json` (LLM, schema 1.6.0, 6 validators, override gate) |
| 4 | `entity_enricher` | `analysis_enriched.json` (handles via DDG browser) |
| 5 | `auto_source` | `analysis_super_enriched.json` + recapture URL oficial por topic |
| 6 | `visual_inventory` | `visual_inventory.json` (Haiku vision, video + og:image) |
| 7 | `script_finalizer` | `analysis_balanced.json` (industry baselines + variety penalty + type gate) |
| 8 | `broll_matcher` | `analysis_matched.json` (Haiku semantic match per beat) |
| 9 | `broll_resolver` | `broll_plan.json` + `pending_acquisition.json` |
| 10 | `acquisition` | `pending_acquired.json` + `broll_plan_complete.json` (Pexels + text_card) |
| 11 | `storyboard` | `storyboard.json` + `thumbs/<beat>_<n>.jpg` |

Tests por módulo (snapshot post-broll_matcher):

```
capture           88   polish      58   analysis        91
pipeline          32   viewer      48   entity_enricher 55
auto_source       11   visual_inv  14   script_finalizer 9
broll_resolver     7   acquisition  8   storyboard       6
broll_matcher      9
TOTAL: 436 tests passing
```

---

## E2E verificado (último freeze)

| Run | Vídeo | Idioma | Material | Resultado |
|---|---|---|---|---|
| `qwen_27B_real.json` (fixture) | top2 | es | — | BLOCKED → override → unblocked |
| `recording5_full` | Gemma 4 (sin sources) | es | auto-detected DeepMind, 3 webm | 13/14 hints anchored, 1 Pexels |
| `recording5_with_sources` | Gemma 4 + 4 URLs Google | es | 6 vídeos (incluye 33MB hero YT) | 6 anchors distintos + Pexels + text_cards, **broll_matcher 4/6 re-anchored** |
| `mirofish_v8` / `mirofish_v11` | Mirofish TikTok | en | 2 og:images Medium + mirofish.my | 2 thumbs, material_score 0.9 (rich) |

---

## Bugs conocidos / deuda técnica

### 🟡 viewer
- **Screenshots cache-stale**: si el endpoint `screenshot/{slug}` se sirvió una vez y se cambió a `/file/<rel>`, el navegador cachea el 404. Hard reload (Cmd+Shift+R) lo arregla. Considerar `Cache-Control: no-cache` durante desarrollo.
- **Live progress streaming** sigue pendiente. Hoy sólo se actualiza con recarga manual.
- **Refresh manifest sin re-correr**: comando `./myavatar refresh <run>` para regenerar `pipeline_manifest.json` cuando se actualiza un descriptor (hoy hay un snippet ad-hoc).

### 🟡 entity_enricher
- `from_browser` con DuckDuckGo a veces queda 0 incluso cuando hay match (filtro lower-case + path_overlap demasiado estricto). Inspect cuando un canal oficial conocido no se identifica.

### 🟡 script_finalizer
- El gate `_TYPES_ANCHORABLE = {video, web_capture, photo}` excluye demasiado en vídeos cortos donde el LLM emite mayormente type=slide/mockup. En Mirofish (TikTok 51s) sobreviven solo 2 de 4 hints. Mejora propuesta: si tier=`rich` y NO hay alternativa visual para ese type, dejar pasar al anchor con score>0.6.

### 🟡 acquisition
- yt-dlp ytsearch (filtro canales oficiales) y Ken Burns (foto → vídeo zoom-pan) no implementados. Solo Pexels + text_card.

### 🟡 broll_matcher
- Funciona pero se podría:
  - Pasar `chosen_score` post-LLM al broll_resolver como `confidence`
  - Hacer 1 sola llamada cuando un beat tiene 2 hints (multi-hint prompt)

### 🟢 capture
- `media_audit.json` con warnings explícitos. v4-spec source priority cumplido.

---

## Lo que queda para producir el .mp4 final

### Fase 12 — `subtitler` (siguiente próxima sesión)

**Input**: `transcript_polished.json` (word-level con timestamps) + opcionalmente `analysis_matched.json` (para hero_text en title beats).

**Output**:
- `subtitles.srt` (estándar)
- `subtitles.ass` (karaoke word-by-word para CapCut/Remotion)
- `subtitle_clips.json` (estructura para el compositor)

Spec v4 (`pipeline_v4_frozen_20260423/BROLL_CREATIVE_SPEC.md`) define el estilo:
- bold sans-serif (Inter Bold / Montserrat Bold)
- pill negro semi-transparente
- 1 word at a time, bottom third, centered
- sync exacto al audio

Pure determinista (sin LLM). Estimado: ½ jornada.

### Fase 13 — `compositor`

**Input**: `broll_plan_complete.json` + `subtitle_clips.json` + `audio.wav` (post-cut polish) + `transcript_polished.json` (timeline_map para presenter video matted).

**Output**: `final.mp4` (1080×1920 9:16, 30 fps, h264).

Dos opciones:
- **(a) Remotion local** (recomendada) — `npx remotion render` headless. JSX programable. Skill `remotion-best-practices` ya cargado en este Claude session.
- **(b) CapCut export** — genera `.draft_content` editable. Código reutilizable en `pipeline_v4_frozen_20260423/capcut_builder.py` y `pipeline_v4_frozen_20260423/capcut_format_research.md`.

Estimado: 1-2 jornadas (compose + asset stitching + título overlays + subtitle sync).

---

## Comandos útiles

```bash
# Pipeline completo desde cero
cd v6 && ./myavatar produce /path/to/video.mp4 [--sources urls.txt] [--name X]

# Re-correr una sola fase (después de capture+polish+analysis ya hechos)
RUN=$HOME/myavatar/runs/<name>
v6/script_finalizer/.venv/bin/script-finalizer run \
  --analysis "$RUN/auto_source/analysis_super_enriched.json" \
  --visual-inventory "$RUN/visual_inventory/visual_inventory.json" \
  --out-dir "$RUN/script_finalizer"

# Override de gate numeric_conflict (cuando analysis BLOCKED)
v6/analysis/.venv/bin/analysis run --validation-override over.json …

# Refrescar manifest del viewer cuando un descriptor cambia
v6/pipeline/.venv/bin/python -c "
import json
from pathlib import Path
from pipeline.contracts import PipelineManifest
from pipeline.registry import PIPELINE_PHASES
for run in (Path.home()/'myavatar'/'runs').iterdir():
    mf = run/'pipeline_manifest.json'
    if not mf.exists(): continue
    old = json.loads(mf.read_text())
    new = PipelineManifest(
        run_name=old['run_name'], created_at=old['created_at'],
        video_input=old.get('video_input',''),
        sources_input=old.get('sources_input'),
        phases=[d.to_manifest_phase() for d in PIPELINE_PHASES])
    mf.write_text(new.model_dump_json(indent=2))
"

# Reiniciar viewer apuntando al root correcto
lsof -ti :8765 | xargs -r kill 2>/dev/null
VIEWER_ROOTS=$HOME/myavatar/runs \
  v6/viewer/.venv/bin/python -m uvicorn viewer.app:app \
  --host 127.0.0.1 --port 8765 &
```

---

## Decisiones editoriales que rigen el sistema

(extraídas del `BROLL_CREATIVE_SPEC.md` v4 + búsqueda web 2026)

- **Source priority**: real footage > official screenshots > logos > mockups > stock > text card
- **B-roll coverage target adaptativo**: 35-50% (default) / 50-65% (rich material) / 25-35% (thin)
- **Real footage ratio ≥ 50%** del total de hints; **filler ≤ 30%**
- **Hints/min target**: 3-5 (industry, vídeos explainer hybrid)
- **Beat duration sweet spot**: 6-10s (vídeos > 2 min)
- **Max consecutive talking head**: 7s en short-form / 15s en long-form
- **Variety penalty**: -0.15 por reuso de asset, -0.40 por reuso de segment
- **Type gate**: solo `video / web_capture / photo` pueden anchor a inventory; `slide / title / mockup` van a `acquisition`
- **YouTube como fuente**: solo desde canales oficiales verificados (regla del operador)
- **LLM nunca inventa**: URLs ni handles ni magnitudes numéricas (gate determinista bloquea)
