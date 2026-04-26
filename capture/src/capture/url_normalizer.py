"""Pure URL normalization + slug derivation.

Determinista. Idempotente. Hashable como clave de cache.
Sin dependencias externas (solo stdlib).

Reglas:
  - Scheme/host a lowercase.
  - Fragmento (#...) eliminado.
  - Query params de tracking eliminados, los demás preservados en orden.
  - Trailing slash eliminado excepto en root ("/").
  - Default scheme "https" si falta.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

DEFAULT_TRACKING_PARAMS: frozenset[str] = frozenset({
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "ref_source",
    "ref_src",
    "igshid",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
})

_SLUG_SAFE = re.compile(r"[^a-z0-9]+")
_SLUG_COLLAPSE = re.compile(r"-+")


def normalize_url(
    url: str,
    tracking_params: frozenset[str] | set[str] | None = None,
) -> str:
    """Normaliza una URL para dedupe y cache.

    Deja el path intacto salvo trailing slash.
    """
    if tracking_params is None:
        tracking_params = DEFAULT_TRACKING_PARAMS
    else:
        tracking_params = frozenset(tracking_params)

    if "://" not in url:
        url = "https://" + url

    parts = urlparse(url)
    scheme = parts.scheme.lower() or "https"
    host = parts.netloc.lower()

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    params = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in tracking_params
    ]
    query = urlencode(params, doseq=True)

    return urlunparse((scheme, host, path, parts.params, query, ""))


def derive_slug(url: str, *, maxlen: int = 60) -> str:
    """Slug estable basado en host + último segmento significativo.

    Solo [a-z0-9-]. Si la forma natural excede ``maxlen``, degrada a
    ``host-<hash8>`` — determinista y sin pérdida de identificación
    (la URL completa vive en el manifest). Colisiones naturales las
    resuelve el orquestador añadiendo sufijos numéricos.
    """
    parts = urlparse(url if "://" in url else "https://" + url)
    host = parts.netloc.lower()
    segments = [s for s in parts.path.split("/") if s]

    tail_parts: list[str] = []
    if segments:
        last = segments[-1]
        last = re.sub(r"\.[a-zA-Z0-9]{1,5}$", "", last)
        tail_parts.append(last)

    raw = host + ("-" + "-".join(tail_parts) if tail_parts else "")
    raw = raw.lower()
    natural = _SLUG_COLLAPSE.sub("-", _SLUG_SAFE.sub("-", raw)).strip("-")

    if natural and len(natural) <= maxlen:
        return natural

    # Fallback determinista: host + hash8 del path + query. Conserva
    # identificación sin truncar en medio de palabras.
    host_slug = _SLUG_COLLAPSE.sub("-", _SLUG_SAFE.sub("-", host)).strip("-")
    digest_source = (parts.path + "?" + parts.query).encode("utf-8")
    digest = hashlib.sha1(digest_source).hexdigest()[:8]
    candidate = f"{host_slug}-{digest}" if host_slug else digest

    if len(candidate) > maxlen:
        # Host por sí solo es ya más largo que maxlen — truncamos host
        # pero preservamos el hash al final para no perder identidad.
        keep = max(1, maxlen - len(digest) - 1)
        candidate = f"{host_slug[:keep].rstrip('-')}-{digest}"

    return candidate or "url"
