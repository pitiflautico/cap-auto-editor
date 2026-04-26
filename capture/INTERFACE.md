# Phase -1 — capture/

## Changelog v2.0

**FROZEN v2.0 — 2026-04-24.** Breaking change of the progress artefact only;
`CaptureManifest` schema 2.0.0 is **unchanged**.

- Progress emission moved to shared `v6/progress/` package (`ProgressEmitter`/`NullEmitter` from `progress` module).
- Event schema unified: `run_start` now carries `phase="capture"` and `total_steps`; per-URL events are `step_start`/`step_done` with `name="capture_url"` and `detail=<url>`.
- `url_probe` event dropped — content_type is now folded into `step_done.summary`.
- `url_start` event dropped — replaced by `step_start`.
- `url_done` event dropped — replaced by `step_done`.
- Progress file renamed from `capture_progress.jsonl` → **`progress.jsonl`** (clean break; no alias).

> **STATUS: FROZEN v2.0 — 2026-04-24**
>
> Interfaz de contrato. Cualquier implementación de esta fase debe
> respetar las entradas, salidas y garantías descritas aquí.
> Esta documentación precede al código — cambios de interfaz
> requieren actualizar este documento primero y bumpear la versión.
>
> **Changelog v1.0 (respecto al proto DRAFT v0.1):**
> simplificación quirúrgica validada con E2E sobre `top2_sources.txt`
> (9/9 URLs capturadas, 62 tests green). Los meta tags OG/Twitter/
> microdata se descartaron por inútiles en redes sociales y SPAs.
> Se eliminó `extractors/metadata.py`, `CaptureMetadata`, el fichero
> `metadata.json`. `extract_text` prioriza `<article> → <main> → <body>`
> con umbral de 500 caracteres para evitar falsos positivos de
> widgets con `<article>` vacío. Para imágenes directas,
> `CaptureResult.image_info` lleva `{content_type, width, height}`
> inline. Se añadió `progress.py` con emisión JSONL append-only
> (eventos `run_start` / `url_start` / `url_probe` / `url_done` /
> `run_done`) para que el viewer pueda tail en tiempo real. Schema
> de `CaptureManifest` fijado en `2.0.0`.

---

## Propósito

Dada una lista de URLs aportadas por el usuario (artículos, posts,
threads, imágenes sueltas), **capturar todo el material disponible
una sola vez** y dejarlo en disco en un formato canónico reutilizable
por todas las fases downstream.

Capture es la fase **-1** del pipeline V6. Se ejecuta antes de
`polish/`, `analysis/` y `broll_plan/`. Resuelve el cuello de botella
real de V5/V6 polish: las entidades técnicas mal transcritas por
Whisper (KWIN, Cloud, Antropico, Alman, "27 millones") se arreglan
desde la primera transcripción si `polish/transcribe.py` recibe el
prompt enriquecido con la forma canónica extraída de las sources.

---

## Responsabilidad

**Hace:**
- Recorrer las URLs una única vez por proyecto.
- Por cada URL: elegir backend, navegar, extraer `title`,
  `description`, `author`, fecha si existe, el texto visible
  completo y una captura visual de la página.
- Deduplicar por hash de URL normalizada.
- Registrar el intento en un manifest reproducible: backend usado,
  timestamp, sha256 del artefacto, éxito/fallo, motivo del fallo.
- Retry con backoff para errores transitorios (Cloudflare challenge,
  race de Chrome, timeout).

**No hace:**
- Decidir qué URL es relevante para qué entidad.
- Extraer listas de entidades, topics o claims (eso es
  `polish.sources` + `polish.entity_candidates` + `analysis/`).
- Resolver queries en lenguaje natural a URLs (eso es el resolver
  grounded de Gemini que vive en `pipeline/providers/broll`).
- Resumir, traducir o interpretar el contenido.
- Seleccionar highlights visuales o sugerir usos de b-roll.

**Regla dura:** capture/ **nunca interpreta** el contenido. Solo
captura bytes. Downstream decide qué significan. Si una función
necesita entender semántica, modelar entidades o sugerir relevancia,
no pertenece a esta fase.

---

## Inputs

| Input | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `sources` | ruta a `.txt` o lista CLI | Sí | URLs a capturar, una por línea |
| `out_dir` | ruta a directorio | Sí | Destino del manifest y artefactos |
| `mode` | `auto` \| `confirm` | No (default: `auto`) | Ver "Modos de ejecución" |
| `backend` | `browser_sdk` \| `mcp_stdio` \| `claude_orchestrated` \| `auto` | No (default: `browser_sdk`) | Selección de backend |
| `config` | ruta a `.yaml` | No | Overrides de timeouts, viewport, profile, retry |
| `cache` | bool | No (default: `true`) | Si reusar capturas previas por hash de URL |

### Formato de `sources.txt`

Una URL por línea. Líneas vacías y líneas que empiezan con `#` se
ignoran. No se infieren URLs desde texto libre.

```
# top 2 del día 2026-04-24
https://www.reddit.com/r/LocalLLaMA/comments/1steip4/qwen_36_27b_is_a_beast/
https://medium.com/@fzbcwvv/an-overnight-stack-for-qwen3-6-27b-85-tps-125k-context-vision-on-one-rtx-3090-0d95c6291914
https://openai.com/index/introducing-gpt-5-5/
https://i.redd.it/nxwstygg30xg1.png
```

Equivalente CLI: `capture run --source <url> --source <url> --out /tmp/top2_captures`.

### Normalización de URL

Antes de hashear y antes de cachear:
- Quitar fragmento (`#something`).
- Quitar query params de tracking (`utm_*`, `ref`, `ref_source`, `igshid`).
- Bajar scheme/host a lowercase.
- Dejar query params funcionales intactos (ids de thread, page numbers).

La URL normalizada es la clave de cache y de deduplicación. La URL
original se preserva en el manifest.

---

## Outputs

### Canónico

| Fichero | Descripción |
|---|---|
| `capture_manifest.json` | **Documento maestro.** Una entrada por URL con status, backend, paths a artefactos, timestamps, hashes, errores. Consumido por polish, analysis, broll_plan. |

### Por URL capturada (carpeta `captures/<slug>/`)

| Fichero | Condiciones | Descripción |
|---|---|---|
| `text.txt` | Si el backend extrae texto (HTML o text/plain) | Texto visible de la **región principal**: `<article>` → `<main>` → `<body>` (primera coincidencia). Sin scripts/estilos. Sin meta tags. Downstream decide qué porción consume. |
| `screenshot.png` | browser_sdk (viewport) o http_direct (la propia imagen re-encodeada a PNG) | PNG, 1280×1600 por defecto en browser_sdk. |
| `raw.html` | Solo si `config.save_raw_html=true` | HTML bruto tras resolver JS, antes de extraer texto. Útil para debug. |

**No hay `metadata.json`.** La extracción semántica (OG/Twitter/microdata) se descartó en v0.2 porque (a) el 80 % de redes sociales y SPAs no la exponen, (b) el contenido de `<article>` ya incluye el título visible al principio, (c) downstream solo necesita texto para buscar entidades. Para imágenes servidas directamente, `CaptureResult.image_info` lleva `{content_type, width, height}` inline — sin fichero extra.

### Slug de la URL

`slug = first(<host>-<segment>, maxlen=60)`, sanitizado a
`[a-z0-9_-]+`. Ejemplos:

- `https://www.reddit.com/r/LocalLLaMA/comments/1steip4/qwen_36_27b_is_a_beast/`
  → `reddit-com-qwen-36-27b-is-a-beast`
- `https://i.redd.it/nxwstygg30xg1.png`
  → `i-redd-it-nxwstygg30xg1`

Colisiones se resuelven con sufijo `-2`, `-3`, etc. El slug se
registra en el manifest — nunca se deriva dinámicamente aguas abajo.

### Caso especial: URL a imagen directa

Cuando el Content-Type es `image/*`:
- `screenshot.png` = la propia imagen (re-encodeada a PNG para
  uniformidad).
- `text.txt` se omite.
- `CaptureResult.image_info = {content_type, width, height}` inline.
- Backend usado queda registrado como `http_direct` (no se lanza browser).

---

## Contratos (Pydantic — referencia)

Los schemas canónicos viven en `contracts.py`. Resumen:

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class CaptureRequest(BaseModel):
    url: str
    normalized_url: str           # resultado de la normalización
    slug: str                     # slug derivado, estable
    priority: int = 0             # orden de captura, default 0


class CaptureArtifacts(BaseModel):
    text_path: str | None         # relativo a artifact_dir del slug
    screenshot_path: str | None
    raw_html_path: str | None


class ImageInfo(BaseModel):
    """Solo presente cuando la URL servía un asset image/*."""
    content_type: str             # "image/png", "image/jpeg", ...
    width: int | None
    height: int | None


class CaptureResult(BaseModel):
    request: CaptureRequest
    status: Literal["ok", "failed", "skipped_cache"]
    backend: Literal["browser_sdk", "mcp_stdio",
                     "claude_orchestrated", "http_direct"]
    captured_at: datetime
    duration_ms: int
    artifacts: CaptureArtifacts
    image_info: ImageInfo | None
    text_sha256: str | None
    screenshot_sha256: str | None
    attempts: int                 # nº de intentos (retry)
    error: str | None             # si status=failed, mensaje diagnóstico
    error_class: str | None       # "timeout" | "cloudflare" | "http_4xx" | ...


class CaptureManifest(BaseModel):
    schema_version: str           # "2.0.0" en v0.2
    created_at: datetime
    sources_file: str | None
    out_dir: str
    backend_default: str
    config_snapshot: dict
    results: list[CaptureResult]
```

### Función pura obligatoria

```python
def normalize_url(url: str) -> str:
    """Determinista, idempotente. Lower scheme/host, drop fragment,
    drop tracking query params. Hashable como clave de cache."""
```

Los tests de `normalize_url` y del matching `url → slug` blindan la
reproducibilidad: mismo `sources.txt` → mismo manifest shape, mismos
slugs, mismos paths.

---

## Backends

### (B) `browser_sdk` — **default**

`from tools.v4.browser import Browser` vía `sys.path` hack.

- Ruta: variable de entorno `MYAVATAR_NEO_V4_PATH` apunta a
  `/Volumes/DiscoExterno2/mac_offload/Projects/meta-agente/lab/neorender-v2`.
- Launch en proceso; un `Browser(profile=..., pool_size=1, visible=False)`
  por lote de captura.
- Navegación con `tab.navigate(url, wait_s=3.0)`.
- Extracción de texto: `tab.evaluate("document.body.innerText")` o
  `document.documentElement.outerHTML` + `selectolax` para limpieza.
- Screenshot: `tab.screenshot_save(...)` a 1280×1600.
- Metadata: parse de `<title>`, `<meta name="description">`,
  `<meta property="og:*">`, `<meta name="author">`, `<html lang>`.
- **Ventaja:** mismo stack que ya resuelve Cloudflare en
  `pipeline/.../web_capture.py`; perfiles con cookies persistentes
  en `~/.neorender/profiles/`.
- **Limitación:** solo corre en Mac con neorender-v2 checkouteado.

### (A) `mcp_stdio` — alternativo

Cliente JSON-RPC en Python que habla con `tools/v4/server.py` por
stdio.

- Aísla el proceso Chrome (si el cliente crashea, el browser sigue
  vivo en otro proceso).
- Reutilizable desde cualquier script no-Python.
- **Limitación:** hay que implementar el transport (leer/escribir
  JSON-RPC por pipe, correlacionar ids, timeouts, reconnect).

Stub en la primera versión. Se implementa solo si aparece una razón
(por ejemplo: capture en un host sin acceso al filesystem del
neorender-v2 repo).

### (C) `claude_orchestrated` — solo debug

Cuando Claude ejecuta la captura usando los MCP tools
`mcp__neo-browser-v4__*` directamente desde una sesión de Claude Code.
Verificado 2026-04-24 que resuelve Cloudflare y devuelve title exacto
("Qwen 3.6 27B is a BEAST : r/LocalLLaMA").

- **No es producción.** Queda como backend de último recurso cuando
  los dos anteriores fallan y un humano está en la sesión.
- El código de capture/ no lo llama nunca; el manifest acepta
  entradas con `backend="claude_orchestrated"` que se insertan
  manualmente por el operador.

### `http_direct` — implícito

Precheck antes de lanzar browser: un `HEAD` o `GET` con timeout
corto. Si el Content-Type es imagen/video pequeño o un `.txt` plano,
se descarga directamente y se salta el browser. No es "backend
elegible" por el usuario; se aplica siempre que la URL es un asset
directo.

### Selección (`backend=auto`)

1. Si la URL responde a `HEAD` con Content-Type imagen → `http_direct`.
2. Si `MYAVATAR_NEO_V4_PATH` existe y resolver `import` funciona →
   `browser_sdk`.
3. Si no, fallar con error explícito (no se cae silenciosamente a
   `httpx` porque Reddit/Medium bloquean).

---

## Modos de ejecución

| Modo | Comportamiento | Uso típico |
|---|---|---|
| `auto` **(default)** | Recorre todas las URLs, reintenta errores transitorios, registra fallos en manifest sin abortar. | CI / batch |
| `confirm` | Igual que `auto` pero pide confirmación CLI antes de reemplazar una captura cacheada. | Debug manual |

Modo no-interactivo (`--no-tty`) fuerza `auto`.

### Cache

Por defecto `cache=true`. Cuando existe un `CaptureResult` previo
con mismo `normalized_url` y los artefactos referenciados están en
disco, se registra `status="skipped_cache"` con timestamp nuevo y
se reutilizan los paths. `--no-cache` invalida.

### Retry

| Error class | Retry | Backoff |
|---|---|---|
| `timeout` | 2 intentos | 2s |
| `cloudflare_challenge` | 3 intentos | 5s entre intentos, con cookies restauradas |
| `chrome_launch_failed` | 2 intentos | purge + 2s |
| `http_4xx` | 0 | — (registra y continúa) |
| `http_5xx` | 2 | 3s |
| `unknown` | 1 | 2s |

El patrón de retry+purge imita el ya probado en
`web_capture._capture_with_neo_v4`. Tests con URLs mockeadas cubren
cada error class.

---

## Garantías

- **Idempotencia**: rerun con `cache=true` sobre la misma `sources.txt`
  no abre Chrome más que para URLs nuevas o invalidadas.
- **Determinismo estructural**: mismo input → mismos slugs, mismos
  paths, mismo shape del manifest (no necesariamente mismo contenido:
  la web cambia).
- **Trazabilidad**: cada `CaptureResult` registra backend, attempts,
  timestamps y errores. Un fallo nunca "desaparece".
- **No destructivo**: nunca se borra una captura previa; si se
  reintenta, el artefacto nuevo sobrescribe por path derivado de
  `slug` (el previo vive en git/backup si el usuario lo quiere).
- **Reproducibilidad parcial**: dado el mismo `out_dir` y `sources.txt`,
  otro usuario con los mismos profiles del browser genera un manifest
  con el mismo shape y los mismos slugs. El contenido puede diferir
  (la web cambia) — eso se detecta comparando `text_sha256`.

## No-garantías

- **Acceso universal**: sitios detrás de login, paywalls duros, o
  rate-limits pesados pueden fallar. Se registra el fallo, no se
  intenta scrapear agresivamente.
- **Precisión de `metadata.author` / `metadata.published_at`**: depende
  de que la web use microdata/OG tags correctamente.
- **Texto perfectamente limpio**: `text.txt` es "texto visible" — puede
  incluir menús, cookies banners, footers. Limpieza semántica es
  responsabilidad de `polish/sources.py` y `analysis/`.
- **Captura de vídeos**: no se soportan. URLs a vídeos (YouTube,
  Twitch VODs) capturan solo la página, no el vídeo. Si downstream
  lo necesita, extensión futura.

---

## Consumidores downstream

### `polish/` (fase 0)

Lee el manifest y, por cada resultado `ok`, abre `text.txt`. Pasa los
primeros ~1800 caracteres (compatible con los 224 tokens máximos del
initial_prompt de Whisper) a `polish.sources.build_initial_prompt`.
La heurística existente (tokens con capitalización rara, versiones
adyacentes a números) extrae candidatos de entidad de esa ventana.
No se consume ningún campo estructurado — solo texto plano.

Nuevo flag en `polish`:

```
polish run video.mp4 --capture-manifest /tmp/top2_captures/capture_manifest.json
```

Cuando se pasa, `polish/sources.py` ignora el fetch httpx propio (hoy
con timeouts de 3s/URL y bloqueado por Reddit/Medium) y lee el
manifest en 0ms.

### `analysis/` (fase 1, futura)

Lee `text.txt` completo para grounding semántico. Genera topics,
claims soportables, y mapea cada mención del transcript a una fuente
si hay match lexical.

### `broll_plan/` (fase 2, futura)

Lee `screenshot.png` + `request.url` para planificar b-roll visual.
Las capturas ya hechas en capture/ son reutilizables como
asset directo si el layout/viewport encaja.

### `entity_resolution/` (polish Fase 4, futura)

Recibe los candidatos sin resolver + el manifest como contexto de
grounding. Evita una llamada extra al browser (todo lo que necesita
ya está en disco).

---

## Dependencias

- **Runtime**: Python 3.12+, `pydantic >= 2.0`, `httpx` (HEAD precheck
  y `http_direct`), `selectolax` o `beautifulsoup4` (parse de
  metadata), `pyyaml`.
- **Browser backend**: neobrowser v4 en `MYAVATAR_NEO_V4_PATH`.
  Necesita Chrome instalado y perfiles en `~/.neorender/profiles/`.
- **Opcional**: `Pillow` para re-encode de imágenes y lectura de EXIF
  cuando la URL es un asset.

## Coste estimado

| Backend | Coste por URL | Notas |
|---|---|---|
| `browser_sdk` | $0 | Chrome local |
| `http_direct` | $0 | `httpx` directo |
| `mcp_stdio` | $0 | Chrome local |
| `claude_orchestrated` | Coste de los tokens de la sesión Claude | No contar en presupuesto del pipeline |

Capture/ **no gasta API de pago** en su forma por defecto.

## Latencia estimada

| Fase | Tiempo |
|---|---|
| Precheck HEAD por URL | ~0.2s |
| Navegación + extracción texto + screenshot (browser_sdk) | ~4-8s/URL |
| Retry en Cloudflare | +5-15s |
| Parse de metadata + write de artefactos | ~0.1s/URL |
| **Batch de 10 URLs (cold start browser)** | **~50-90s** |
| **Batch de 10 URLs (cache hit)** | **<1s** |

---

## Estructura del código (prevista)

```
v6/capture/
├── INTERFACE.md                 # este documento
├── pyproject.toml
├── config.yaml                  # defaults: viewport, timeouts, retry, profile
├── src/capture/
│   ├── contracts.py             # schemas Pydantic
│   ├── url_normalizer.py        # normalize_url + slug derivation (pura)
│   ├── cache.py                 # lookup/write del manifest, resolución hits
│   ├── backends/
│   │   ├── base.py              # protocolo Backend
│   │   ├── browser_sdk.py       # impl. default via sys.path
│   │   ├── mcp_stdio.py         # stub + skeleton JSON-RPC
│   │   ├── claude_orchestrated.py  # stub — solo acepta entradas manuales
│   │   └── http_direct.py       # HEAD + descarga de assets
│   ├── extractors/
│   │   └── text.py              # article/main/body priority + cleanup
│   ├── progress.py              # JSONL event emitter (run/url start/done)
│   ├── orchestrator.py          # por URL elige backend, retry, cache
│   └── cli.py                   # `capture run --sources ... --out ...`
└── tests/
    ├── test_url_normalizer.py   # dedupe, tracking params, fragments
    ├── test_contracts.py        # schemas + JSON roundtrip
    ├── test_extractors.py       # article/main/body fixtures
    ├── test_http_direct.py      # image + text/plain + 4xx/5xx
    ├── test_progress.py         # JSONL roundtrip
    ├── test_cache.py            # skip_cache, invalidation (Capture-2)
    └── test_orchestrator.py     # retry matrix (Capture-2)
```

---

## Plan de implementación (por fases — una PR cada una)

1. **Capture-0 (skeleton)**
   - `contracts.py`, `url_normalizer.py`, `cli.py` no-op,
     `config.yaml` mínimo, tests de contratos y normalizer.
   - Salida: `capture_manifest.json` vacío con `results=[]`.

2. **Capture-1 (backend http_direct + browser_sdk)**
   - Implementación de ambos backends, `orchestrator` básico sin
     retry complejo, `extractors/text` y `extractors/metadata`.
   - E2E: corre sobre `polish/examples/top2_sources.txt`, produce
     manifest con al menos 6/9 URLs en `status=ok`.

3. **Capture-2 (retry + cache)**
   - Error classification completa, backoffs, cache hit por
     `normalized_url`, `--no-cache`.
   - E2E: segundo run sobre las mismas 9 URLs termina en <1s.

4. **Capture-3 (integración con polish)**
   - `polish/sources.py` acepta `--capture-manifest`.
   - Re-run del E2E de polish sobre `myavatar_recording (7).webm`
     con el manifest del top 2.
   - **Criterio de aceptación:** `entity_candidates.json` pierde
     "KWIN", "Cloud", "Antropico", "Alman" (la forma canónica ya
     entró en el initial_prompt de Whisper).
   - Warning en signals si Whisper devolvió "27 millones" pese al
     hint — capture/ no arregla magnitudes numéricas por sí solo,
     eso sigue siendo Fase 4.

5. **Capture-4 (viewer)**
   - Pestaña `Capture` en `v6/viewer/` con manifest, screenshots
     lado a lado, text capturado y linking al transcript polished.

---

## Versionado

- `schema_version` de `CaptureManifest` empieza en `1.0.0`.
- Cambios backwards-compatible incrementan minor.
- Cambios breaking incrementan major y requieren migración
  documentada.
- Esta INTERFACE.md es versionada en git junto al código.
- El salto de `DRAFT v0.1` → `FROZEN v1.0` se hace solo tras
  revisión humana explícita.
