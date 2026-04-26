"""Capture orchestrator.

Takes a list of CaptureRequests, runs each through the right backend,
and produces a CaptureManifest. Capture-1 scope: no retry logic yet
(beyond what backends do internally). Capture-2 wires the retry
matrix from config.yaml.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from capture import __version__
from capture.backends.base import Backend
from capture.backends.browser_sdk import BrowserSdkBackend
from capture.backends.http_direct import HttpDirectBackend, probe_content_type
from capture.contracts import (
    Backend as BackendName,
    CaptureManifest,
    CaptureRequest,
    CaptureResult,
)
from progress import NullEmitter, ProgressEmitter

log = logging.getLogger("capture.orchestrator")

_CAPTURES_DIR = "captures"


class Orchestrator:
    def __init__(
        self,
        *,
        out_dir: Path,
        backends: Sequence[Backend],
        backend_default: BackendName = "browser_sdk",
        head_timeout_s: float = 4.0,
        progress: ProgressEmitter | NullEmitter | None = None,
    ) -> None:
        self.out_dir = out_dir
        self.backends = list(backends)
        self.backend_default = backend_default
        self.head_timeout_s = head_timeout_s
        self.progress = progress or NullEmitter()

    @classmethod
    def build_default(
        cls,
        *,
        out_dir: Path,
        profile: str = "default",
        viewport_w: int = 1280,
        viewport_h: int = 1600,
        save_raw_html: bool = False,
        progress: ProgressEmitter | NullEmitter | None = None,
    ) -> "Orchestrator":
        return cls(
            out_dir=out_dir,
            backends=[
                HttpDirectBackend(),
                BrowserSdkBackend(
                    profile=profile,
                    viewport_w=viewport_w,
                    viewport_h=viewport_h,
                    save_raw_html=save_raw_html,
                ),
            ],
            backend_default="browser_sdk",
            progress=progress,
        )

    def _artifact_dir(self, request: CaptureRequest) -> Path:
        return self.out_dir / _CAPTURES_DIR / request.slug

    def _pick_backend(
        self, request: CaptureRequest, content_type: str | None
    ) -> Backend | None:
        for backend in self.backends:
            if backend.accepts(request, content_type):
                return backend
        return None

    def run_one(
        self,
        request: CaptureRequest,
        *,
        index: int,
        total: int,
    ) -> CaptureResult:
        # Probe content type (internal — no separate event emitted)
        content_type = probe_content_type(
            request.normalized_url, timeout_s=self.head_timeout_s
        )

        self.progress.emit_step_start(
            index=index,
            total=total,
            name="capture_url",
            detail=request.url,
        )

        backend = self._pick_backend(request, content_type)
        if backend is None:
            result = CaptureResult(
                request=request,
                status="failed",
                backend=self.backend_default,
                captured_at=datetime.now(timezone.utc),
                duration_ms=0,
                attempts=0,
                error=(
                    f"no backend accepts content_type={content_type!r} "
                    f"for {request.normalized_url}"
                ),
                error_class="unknown",
            )
        else:
            log.info(
                "capture %s → %s (content_type=%s)",
                request.slug, backend.name, content_type,
            )
            artifact_dir = self._artifact_dir(request)
            result = backend.capture(request, artifact_dir)

        summary: dict = {
            "status": result.status,
            "backend": result.backend,
            "slug": result.request.slug,
            "content_type": content_type,
        }
        if result.status == "failed":
            summary["error_class"] = result.error_class
            summary["error"] = result.error

        self.progress.emit_step_done(
            index=index,
            name="capture_url",
            duration_ms=result.duration_ms,
            summary=summary,
        )
        return result

    def run(self, requests: Sequence[CaptureRequest]) -> list[CaptureResult]:
        self.progress.emit_run_start(phase="capture", total_steps=len(requests))
        results: list[CaptureResult] = []
        for i, req in enumerate(requests):
            results.append(self.run_one(req, index=i + 1, total=len(requests)))
        ok = sum(1 for r in results if r.status == "ok")
        failed = sum(1 for r in results if r.status == "failed")
        skipped = sum(1 for r in results if r.status == "skipped_cache")
        self.progress.emit_run_done(
            ok=all(r.status == "ok" for r in results),
            summary={"ok": ok, "failed": failed, "skipped_cache": skipped},
        )
        return results

    def build_manifest(
        self,
        results: Sequence[CaptureResult],
        *,
        sources_file: str | None,
        config_snapshot: dict | None = None,
    ) -> CaptureManifest:
        snap = {"capture_version": __version__}
        if config_snapshot:
            snap.update(config_snapshot)
        return CaptureManifest(
            created_at=datetime.now(timezone.utc),
            sources_file=sources_file,
            out_dir=str(self.out_dir),
            backend_default=self.backend_default,
            config_snapshot=snap,
            results=list(results),
        )
