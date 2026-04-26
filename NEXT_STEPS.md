# V6 — NEXT STEPS

> Retomar aquí. Documento vivo. Actualizar al cerrar cada sesión.

---

## Instrucción de arranque

```
Lee v6/NEXT_STEPS.md y
~/.claude/projects/-Volumes-DiscoExterno2-mac-offload-Projects-myavatar/memory/project_v6_polish.md

No reimplementes nada de polish/ sin preguntar. Trabajamos en capture/ ahora.
```

---

## Estado actual (2026-04-24)

### Qué funciona
- **`v6/polish/`** — Fase 0 FROZEN v1.1. 40 tests green. Corrido E2E sobre `myavatar_recording (7).webm` (5:23): 60 cuts, 5 % ahorro, 19 candidatos de entidades limpios.
- **`v6/viewer/`** — FastAPI + Jinja2 + HTMX + Tailwind. http://127.0.0.1:8765 con timeline visual, transcript clicable, audio player.
- **Outputs canónicos:** `transcript_raw.json`, `transcript_polished.json`, `timeline_map.json`, `transcript_patches.json`, `entity_candidates.json`, `summary.json` en `/tmp/top2_polish_v3/`.

### Qué NO funciona (lo que esperamos arreglar con capture/)
- **Entidades mal transcritas siguen mal**. El transcript polished todavía contiene:
  - `KWIN × 3` (debería ser "Qwen")
  - `Cloud × 3` (debería ser "Claude")
  - `Antropico` (debería ser "Anthropic")
  - `Alman` (debería ser "Altman")
  - `"27 millones"` (error factual — debería ser "27 mil millones" o "27B")
- **No hay CLI real** (`polish run video.mp4`) — solo scripts de demo.
- **No hay preview_polished.mp4 audible** (falta Fase 3 de polish).

### Error de secuenciación reconocido
Implementé `polish/` asumiendo que las sources se fetcheaban en su `sources.py` interno. Dani corrigió después: "exploración de fuentes al inicio, capturas de todo, en el pipeline visual del browser". Polish/ ya estaba hecho cuando salió esa decisión — no reestructuré.

**Corrección pendiente:** hacer `capture/` como fase -1 antes de alimentar polish. Eso arregla las entidades desde la primera transcripción sin necesidad de Fase 4 LLM.

---

## Siguiente paso — SESIÓN ARRANCA POR AQUÍ

### Paso 1 (obligatorio antes de código): `v6/capture/INTERFACE.md`

Diseñar el contrato de la nueva fase siguiendo el patrón de `polish/INTERFACE.md` v1.1. Debe cubrir:

- **Propósito**: recorrer las sources aportadas por el usuario y capturar todo el material (title, text completo, screenshot, metadata). Una sola pasada. Output reutilizable por polish/, analysis/ y broll_plan/.
- **Inputs**: `sources.txt` (una URL por línea) + `mode` (auto/confirm) + config opcional.
- **Outputs canónicos**:
  - `capture_manifest.json` — por URL: status, backend, paths a artefactos, timestamps, hash.
  - `captures/<slug>/text.txt` — contenido textual extraído.
  - `captures/<slug>/screenshot.png` — captura visual (opcional según backend).
  - `captures/<slug>/metadata.json` — title, description, author, date.
- **Backends** (decidir cuál implementar primero):
  - (A) Cliente MCP stdio en Python hacia `tools/v4/server.py`. Limpio pero requiere implementar JSON-RPC.
  - (B) `from tools.v4.browser import Browser` vía `MYAVATAR_NEO_V4_PATH`. Replica lo que hace `pipeline/src/myavatar/providers/broll/web_capture.py`.
  - (C) Claude orquesta capturas con MCP tools (solo funciona en sesión Claude).
- **Contratos Pydantic**: `CaptureRequest`, `CaptureResult`, `CaptureManifest`.
- **Regla dura**: capture/ NUNCA interpreta el contenido. Solo captura. La interpretación (entidades, topics) es de fases posteriores.
- **Dependencias**: neobrowser v4 (env `MYAVATAR_NEO_V4_PATH`), playwright/undetected-chromedriver en el venv.

### Paso 2: implementar `v6/capture/` con backend elegido
- Seguir la estructura modular de polish/ (`src/capture/`, tests/, `pyproject.toml`, `config.yaml`).
- `backends/{mcp_stdio,browser_sdk,claude_orchestrated}.py` — solo el elegido primero; los otros stubs.
- `orchestrator.py` — por URL elige backend, retry, cache por hash.
- `cli.py` — `capture run --sources top2_sources.txt --out /tmp/top2_captures/`.

### Paso 3: alimentar polish/ desde capture/
- Nuevo flag en `phase2b_demo.py`: `--capture-manifest /tmp/top2_captures/capture_manifest.json`.
- Extraer entity hints del manifest y enriquecer `build_initial_prompt`.
- Re-correr sobre el mismo wav. Comparar `entity_candidates.json` — expectativa: "KWIN" desaparece, "Cloud" desaparece, "Antropico" desaparece, "27 millones" se convierte en "27 mil millones" o "27B".

### Paso 4 (si paso 3 funciona): adaptar viewer
- Añadir pestaña "Capture" que muestra el manifest, screenshots lado a lado, text capturado.

---

## Después de capture/

Por orden de prioridad:

1. **polish/ Fase 3** — `emit.py` + `preview.py` + `cli.py` real. Así hay preview audible sin LLM.
2. **polish/ Fase 4** — `entity_resolution.py` con Gemini Flash + grounding para los candidatos que capture/ no resolvió.
3. **`analysis/INTERFACE.md`** — siguiente fase (narrative, topics, broll opportunities).
4. **`broll_plan/INTERFACE.md`** + **`builder/INTERFACE.md`**.

---

## Referencias

### Paths clave
- `v6/polish/` — código Fase 0.
- `v6/viewer/` — app web.
- `v6/polish/INTERFACE.md` — contrato Fase 0 FROZEN v1.1.
- `v6/polish/examples/top2_sources.txt` — 9 URLs sobre Qwen 3.6 27B y GPT-5.5.
- `/tmp/top2_audio.wav` — audio extraído (324 s, 16 kHz mono).
- `/tmp/top2_polish_v3/` — outputs del último run.
- `/Volumes/DiscoExterno2/mac_offload/Projects/meta-agente/lab/neorender-v2/` — neobrowser v4 + ghost.
  - `tools/v4/server.py` — MCP stdio server.
  - `tools/v4/browser.py` — Python API directa.
  - `tools/spa-clone/ghost.py` — CLI undetected-chromedriver.

### Memoria
- `~/.claude/projects/-Volumes-DiscoExterno2-mac-offload-Projects-myavatar/memory/project_v6_polish.md`

### Comandos
```bash
# Tests polish
cd v6/polish && .venv/bin/python -m pytest -v

# E2E demo actual (sin capture, dará errores de entidad conocidos)
.venv/bin/python scripts/phase2b_demo.py \
  --audio /tmp/top2_audio.wav \
  --out-dir /tmp/top2_polish_v3 \
  --project-aliases project_aliases.example.yaml

# Viewer
cd v6/viewer && .venv/bin/python -m uvicorn viewer.app:app --port 8765 --reload
```

### MCP disponibles en sesión Claude
- `mcp__neo-browser-v4__navigate` / `read` / `page_info` / `screenshot` / `extract` — probados, funcionan contra Cloudflare.
- Verificado: https://www.reddit.com/r/LocalLLaMA/comments/1steip4/qwen_36_27b_is_a_beast/ devuelve title "Qwen 3.6 27B is a BEAST : r/LocalLLaMA".

---

## Decisiones arquitectónicas (no cambiar sin hablar con Dani)

1. Cada fase tiene `INTERFACE.md` frozen antes de código. Cambios → bump de versión.
2. Cada fase es paquete Python independiente con su `pyproject.toml` y `.venv`.
3. Contratos entre fases vía JSON (Pydantic schemas).
4. `timeline_map.json` es documento maestro de polish/; `keep_segments` y `cut_map` son vistas derivadas.
5. **Capture es fase -1 (pre-polish)** y sirve a TODAS las fases downstream. No es privado de polish.
6. `generic_aliases` / text normalizer NUNCA contiene marcas/productos. Solo puntuación y formato universal.
7. Nunca auto-corregir magnitud numérica ("27 millones" vs "27 mil millones") sin evidencia externa explícita. Warning en signals.
8. Modo default `auto_safe` en polish/: cosméticos sí, entidades alta confianza sí, numéricos nunca.
9. `project_aliases.yaml` es opcional y específico del proyecto. No se ship con default.
