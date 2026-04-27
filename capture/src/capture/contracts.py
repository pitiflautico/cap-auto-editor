"""Pydantic contracts for v6/capture/.

Source of truth: INTERFACE.md.
Any change here requires updating INTERFACE.md first and bumping
schema_version on CaptureManifest.

v0.2 simplification: no semantic metadata extraction. capture/ only
persists text + screenshot. Downstream (polish/sources.py) reads
text.txt directly and finds entities with its own heuristics.

v2.1 (capture-media): each capture can also produce a list of
``MediaAsset`` entries — embedded videos, og:video, og:image, GIFs —
downloaded with yt-dlp / httpx for the broll_resolver to reuse without
re-fetching. Downstream phases read ``CaptureArtifacts.assets`` to know
what ready-made media is available before falling back to stock search.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Backend = Literal[
    "browser_sdk",
    "mcp_stdio",
    "claude_orchestrated",
    "http_direct",
]

Status = Literal["ok", "failed", "skipped_cache"]

ErrorClass = Literal[
    "timeout",
    "cloudflare_challenge",
    "chrome_launch_failed",
    "http_4xx",
    "http_5xx",
    "unknown",
]


class CaptureRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    normalized_url: str
    slug: str
    priority: int = 0


MediaKind = Literal[
    "video",         # downloaded mp4/webm — embedded video, og:video, yt-dlp result
    "og_image",      # og:image when ≥1080px (large enough for portrait crop)
    "gif",           # animated GIF
    "favicon",       # site icon (small, used as logo fallback)
]

MediaProvider = Literal[
    "og_video",      # found via meta property="og:video"/og:video:secure_url
    "video_tag",     # found via <video> or <video><source> tag
    "og_image",      # found via meta property="og:image"
    "yt_dlp",        # downloaded by yt-dlp (YouTube/Twitter/TikTok/Instagram)
    "http_direct",   # direct HTTP fetch of an mp4/gif/jpg/png
]


class MediaAsset(BaseModel):
    """A media file persisted alongside text+screenshot for a captured URL.

    Only present when the source page exposes embedded media that we can
    download legally with yt-dlp or a direct HTTP fetch. Shape kept narrow
    so the broll_resolver can pick assets without re-parsing the source.
    """

    model_config = ConfigDict(extra="forbid")

    kind: MediaKind
    provider: MediaProvider
    path: str                            # relative to captures/<slug>/ (e.g. "media/video_01.mp4")
    source_url: str                      # original media URL (yt-dlp page URL OR direct asset URL)
    sha256: str | None = None
    bytes: int | None = None
    # Image-only metadata
    width: int | None = None
    height: int | None = None
    # Video-only metadata
    duration_s: float | None = None
    thumb_path: str | None = None        # relative path to a poster/thumbnail jpg if extracted


class CaptureArtifacts(BaseModel):
    text_path: str | None = None
    screenshot_path: str | None = None
    raw_html_path: str | None = None
    assets: list[MediaAsset] = Field(default_factory=list)
    media_audit_path: str | None = None   # relative path to media_audit.json


class ImageInfo(BaseModel):
    """Minimal info for direct-image captures.

    Populated only when the URL itself served an ``image/*`` asset
    (http_direct backend). Consumers like broll_plan use this to decide
    whether a downloaded asset fits a required viewport.
    """

    content_type: str
    width: int | None = None
    height: int | None = None


class CaptureResult(BaseModel):
    request: CaptureRequest
    status: Status
    backend: Backend
    captured_at: datetime
    duration_ms: int
    artifacts: CaptureArtifacts = Field(default_factory=CaptureArtifacts)
    image_info: ImageInfo | None = None
    text_sha256: str | None = None
    screenshot_sha256: str | None = None
    attempts: int = 1
    error: str | None = None
    error_class: ErrorClass | None = None

    @model_validator(mode="after")
    def _check_failure_has_diagnostics(self) -> "CaptureResult":
        if self.status == "failed":
            if not self.error or not self.error_class:
                raise ValueError(
                    "status='failed' requires both 'error' and 'error_class'"
                )
        return self


class CaptureManifest(BaseModel):
    schema_version: str = "2.1.0"
    created_at: datetime
    sources_file: str | None = None
    out_dir: str
    backend_default: Backend
    config_snapshot: dict = Field(default_factory=dict)
    results: list[CaptureResult] = Field(default_factory=list)
