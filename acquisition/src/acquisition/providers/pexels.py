"""Pexels API provider — search images and videos for a query string.

API docs: https://www.pexels.com/api/documentation/
Free tier: 200 req/h, 20k/mes. Adequate for our usage (1-3 calls per pending
hint per video processed).

Two endpoints used:
  • /v1/search           — image search
  • /videos/search       — video search

Both return a JSON list; we pick the first result that meets minimum
dimensions (≥720 portrait) and download it directly via httpx.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("acquisition.pexels")


_IMAGE_API = "https://api.pexels.com/v1/search"
_VIDEO_API = "https://api.pexels.com/videos/search"
_HEADERS_BASE = {
    "User-Agent": "myavatar-v6/0.1 (broll-acquisition)",
}
_MIN_W = 720    # accept ≥ HD portrait
_MIN_H = 720
_MAX_BYTES = 80 * 1024 * 1024


def _api_key() -> str | None:
    """Read PEXELS_API_KEY. Tries env first, then v6/.env, then myavatar/.env."""
    key = os.environ.get("PEXELS_API_KEY")
    if key:
        return key
    # Project root is two levels above this file (acquisition/src/acquisition/providers)
    here = Path(__file__).resolve()
    for env_path in (
        here.parents[4] / ".env",                              # v6/.env (rare)
        here.parents[5] / ".env",                              # myavatar/.env (the configured one)
    ):
        if not env_path.exists():
            continue
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("PEXELS_API_KEY") and "=" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def _http():
    import httpx
    return httpx


def _download_to(url: str, out: Path) -> bool:
    httpx = _http()
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
            if resp.status_code != 200:
                return False
            written = 0
            with out.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                    written += len(chunk)
                    if written > _MAX_BYTES:
                        out.unlink(missing_ok=True)
                        return False
                    f.write(chunk)
        return out.exists() and out.stat().st_size > 4096
    except Exception as exc:
        log.warning("pexels download failed for %s: %s", url, exc)
        return False


def search_image(query: str, out_dir: Path,
                 *, name_prefix: str = "pexels") -> tuple[Path, str, dict] | None:
    """Search Pexels for an image. Returns (path, source_url, info) or None."""
    key = _api_key()
    if not key:
        log.info("PEXELS_API_KEY not set — image search disabled")
        return None
    httpx = _http()
    headers = {**_HEADERS_BASE, "Authorization": key}
    try:
        resp = httpx.get(_IMAGE_API, params={
            "query": query, "per_page": 5, "orientation": "portrait",
        }, headers=headers, timeout=20)
    except Exception as exc:
        log.warning("pexels image search failed: %s", exc)
        return None
    if resp.status_code != 200:
        log.warning("pexels image API returned %d", resp.status_code)
        return None
    photos = (resp.json() or {}).get("photos") or []
    for p in photos:
        w = p.get("width") or 0
        h = p.get("height") or 0
        if w < _MIN_W or h < _MIN_H:
            continue
        # Prefer 'large2x' (medium-resolution); fall back to 'original'.
        src = (p.get("src") or {})
        url = src.get("large2x") or src.get("large") or src.get("original")
        if not url:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{name_prefix}_image_{p['id']}.jpg"
        if _download_to(url, out):
            return out, p.get("url") or url, {
                "id": p["id"], "width": w, "height": h,
                "photographer": p.get("photographer"),
            }
    return None


def search_video(query: str, out_dir: Path,
                 *, name_prefix: str = "pexels",
                 min_duration_s: float = 2.0,
                 max_duration_s: float = 30.0) -> tuple[Path, str, dict] | None:
    """Search Pexels for a portrait video. Returns (path, source_url, info)."""
    key = _api_key()
    if not key:
        log.info("PEXELS_API_KEY not set — video search disabled")
        return None
    httpx = _http()
    headers = {**_HEADERS_BASE, "Authorization": key}
    try:
        resp = httpx.get(_VIDEO_API, params={
            "query": query, "per_page": 5, "orientation": "portrait",
            "size": "medium",
        }, headers=headers, timeout=30)
    except Exception as exc:
        log.warning("pexels video search failed: %s", exc)
        return None
    if resp.status_code != 200:
        log.warning("pexels video API returned %d", resp.status_code)
        return None
    videos = (resp.json() or {}).get("videos") or []
    for v in videos:
        dur = float(v.get("duration") or 0)
        if dur < min_duration_s or dur > max_duration_s:
            continue
        files = v.get("video_files") or []
        # Prefer 720p portrait MP4
        mp4 = next(
            (f for f in files
             if f.get("file_type") == "video/mp4"
             and (f.get("width") or 0) >= _MIN_W
             and (f.get("height") or 0) >= _MIN_H),
            None,
        )
        if not mp4:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{name_prefix}_video_{v['id']}.mp4"
        if _download_to(mp4["link"], out):
            return out, v.get("url") or mp4["link"], {
                "id": v["id"], "duration_s": dur,
                "width": mp4.get("width"), "height": mp4.get("height"),
            }
    return None
