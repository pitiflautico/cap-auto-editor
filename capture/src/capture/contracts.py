"""Pydantic contracts for v6/capture/.

Source of truth: INTERFACE.md (DRAFT v0.2).
Any change here requires updating INTERFACE.md first and bumping
schema_version on CaptureManifest.

v0.2 simplification: no semantic metadata extraction. capture/ only
persists text + screenshot. Downstream (polish/sources.py) reads
text.txt directly and finds entities with its own heuristics.
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


class CaptureArtifacts(BaseModel):
    text_path: str | None = None
    screenshot_path: str | None = None
    raw_html_path: str | None = None


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
    schema_version: str = "2.0.0"
    created_at: datetime
    sources_file: str | None = None
    out_dir: str
    backend_default: Backend
    config_snapshot: dict = Field(default_factory=dict)
    results: list[CaptureResult] = Field(default_factory=list)
