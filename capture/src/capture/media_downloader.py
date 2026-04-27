"""Media downloader — turn MediaCandidate objects into MediaAsset files.

Two providers supported:
  - yt-dlp        for known platforms (YouTube/Twitter/TikTok/Instagram).
                  Resolves the underlying media + thumbnail in one call.
  - http_direct   for og:video / <video src> / og:image direct URLs.
                  Downloaded with httpx, sha256 + size recorded.

Designed to never raise on a per-asset failure: returns ``None`` and the
caller logs. The capture as a whole still succeeds with text + screenshot
even if every media asset fails — media is opportunistic, not required.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .contracts import MediaAsset
from .extractors.media import MediaCandidate

log = logging.getLogger("capture.media")


_YTDLP_TIMEOUT_S = 120
_HTTP_TIMEOUT_S = 60
_MAX_BYTES = 80 * 1024 * 1024  # 80 MB cap per asset


def _yt_dlp_available() -> bool:
    return shutil.which("yt-dlp") is not None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _image_dims(path: Path) -> tuple[int | None, int | None]:
    """Best-effort width/height extraction. Returns (None, None) on failure."""
    try:
        from PIL import Image  # type: ignore
        with Image.open(path) as im:
            return im.size  # (w, h)
    except Exception:
        return (None, None)


@dataclass
class DownloadContext:
    out_dir: Path                 # captures/<slug>/
    media_subdir: str = "media"   # files land in captures/<slug>/media/
    max_video_duration_s: float | None = 300.0  # skip 30-min trailers


def _download_yt_dlp(cand: MediaCandidate, ctx: DownloadContext, idx: int) -> MediaAsset | None:
    if not _yt_dlp_available():
        log.warning("yt-dlp not installed; skipping %s", cand.url)
        return None

    media_dir = ctx.out_dir / ctx.media_subdir
    media_dir.mkdir(parents=True, exist_ok=True)
    template = str(media_dir / f"video_{idx:02d}.%(ext)s")
    info_json = media_dir / f"video_{idx:02d}.info.json"

    cmd = [
        "yt-dlp",
        "--quiet", "--no-warnings", "--no-playlist",
        "--max-filesize", "80M",
        "--format", "mp4/bestvideo[ext=mp4]+bestaudio/best",
        "--write-info-json", "--no-write-comments",
        "--output", template,
        cand.url,
    ]
    if ctx.max_video_duration_s:
        cmd.extend(["--match-filter", f"duration<={int(ctx.max_video_duration_s)}"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_YTDLP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log.warning("yt-dlp timeout on %s", cand.url)
        return None
    if result.returncode != 0:
        log.info("yt-dlp failed on %s: %s", cand.url, (result.stderr or "")[:200])
        return None

    # yt-dlp writes the actual filename based on extension; find it
    candidates = sorted(media_dir.glob(f"video_{idx:02d}.*"))
    media_files = [p for p in candidates if p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}]
    if not media_files:
        return None
    video_path = media_files[0]

    duration: float | None = None
    if info_json.exists():
        try:
            info = json.loads(info_json.read_text(encoding="utf-8"))
            d = info.get("duration")
            if isinstance(d, (int, float)):
                duration = float(d)
        except Exception:
            pass

    relative = str(video_path.relative_to(ctx.out_dir))
    return MediaAsset(
        kind="video",
        provider="yt_dlp",
        path=relative,
        source_url=cand.url,
        sha256=_sha256(video_path),
        bytes=video_path.stat().st_size,
        duration_s=duration,
    )


def _download_http(cand: MediaCandidate, ctx: DownloadContext, idx: int) -> MediaAsset | None:
    import httpx  # local import to keep capture independent if httpx is unavailable

    media_dir = ctx.out_dir / ctx.media_subdir
    media_dir.mkdir(parents=True, exist_ok=True)

    suffix = ".mp4"
    if cand.kind == "og_image":
        suffix = ".jpg"
    elif cand.url.lower().endswith((".gif", ".webm", ".mov", ".png", ".jpg", ".jpeg")):
        suffix = "." + cand.url.rsplit(".", 1)[-1].lower()

    name_prefix = "image" if cand.kind == "og_image" else "video"
    out_path = media_dir / f"{name_prefix}_{idx:02d}{suffix}"

    try:
        with httpx.stream("GET", cand.url, follow_redirects=True,
                          timeout=_HTTP_TIMEOUT_S) as resp:
            if resp.status_code != 200:
                log.info("http %d on %s", resp.status_code, cand.url)
                return None
            written = 0
            with out_path.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                    written += len(chunk)
                    if written > _MAX_BYTES:
                        log.warning("media %s exceeds %d bytes — abort", cand.url, _MAX_BYTES)
                        f.close()
                        out_path.unlink(missing_ok=True)
                        return None
                    f.write(chunk)
    except Exception as exc:
        log.info("http_direct failure on %s: %s", cand.url, exc)
        return None

    if out_path.stat().st_size < 1024:
        out_path.unlink(missing_ok=True)
        return None

    width: int | None = cand.width
    height: int | None = cand.height
    if cand.kind == "og_image" and (width is None or height is None):
        width, height = _image_dims(out_path)

    relative = str(out_path.relative_to(ctx.out_dir))
    provider = "og_image" if cand.kind == "og_image" else cand.provider  # type: ignore[assignment]
    return MediaAsset(
        kind=cand.kind,           # type: ignore[arg-type]
        provider=provider,        # type: ignore[arg-type]
        path=relative,
        source_url=cand.url,
        sha256=_sha256(out_path),
        bytes=out_path.stat().st_size,
        width=width,
        height=height,
    )


def download_candidates(
    candidates: list[MediaCandidate],
    ctx: DownloadContext,
    max_per_capture: int = 3,
) -> list[MediaAsset]:
    """Download up to ``max_per_capture`` candidates and return MediaAssets.

    Order preserved: yt-dlp candidates first, then og:video, video tags,
    then og:image (per detect_media's emission order).
    """
    out: list[MediaAsset] = []
    for idx, cand in enumerate(candidates):
        if len(out) >= max_per_capture:
            break
        try:
            if cand.provider == "yt_dlp":
                asset = _download_yt_dlp(cand, ctx, len(out) + 1)
            else:
                asset = _download_http(cand, ctx, len(out) + 1)
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("unexpected error downloading %s: %s", cand.url, exc)
            asset = None
        if asset is not None:
            out.append(asset)
    return out
