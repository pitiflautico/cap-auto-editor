"""http_direct backend: HEAD precheck + asset download.

Handles:
  - Direct image URLs (`image/*` Content-Type): downloads bytes,
    re-encodes to PNG for uniformity, records dimensions via Pillow.
  - Small text files (`text/plain`): downloads text.txt verbatim.

HTML is NOT handled here — it belongs to browser_sdk because Reddit,
Medium, etc. gate httpx with Cloudflare.
"""
from __future__ import annotations

import hashlib
import io
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from capture.contracts import (
    CaptureArtifacts,
    CaptureRequest,
    CaptureResult,
    ErrorClass,
    ImageInfo,
)

if TYPE_CHECKING:
    import httpx


_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) v6-capture/0.1"


def _client_headers() -> dict[str, str]:
    return {"User-Agent": _UA}


def probe_content_type(url: str, timeout_s: float = 4.0) -> str | None:
    """HEAD request to sniff Content-Type. None on any failure."""
    import httpx

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout_s,
            headers=_client_headers(),
        ) as client:
            resp = client.head(url)
            ct = resp.headers.get("content-type", "")
            return ct.split(";")[0].strip().lower() or None
    except Exception:
        return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class HttpDirectBackend:
    name = "http_direct"

    def __init__(self, timeout_s: float = 10.0) -> None:
        self.timeout_s = timeout_s

    def accepts(
        self, request: CaptureRequest, content_type: str | None
    ) -> bool:
        if content_type is None:
            return False
        if content_type.startswith("image/"):
            return True
        if content_type == "text/plain":
            return True
        return False

    def capture(
        self,
        request: CaptureRequest,
        artifact_dir: Path,
    ) -> CaptureResult:
        import httpx

        t0 = time.monotonic()
        artifact_dir.mkdir(parents=True, exist_ok=True)

        def _fail(error_class: ErrorClass, msg: str) -> CaptureResult:
            return CaptureResult(
                request=request,
                status="failed",
                backend="http_direct",
                captured_at=datetime.now(timezone.utc),
                duration_ms=int((time.monotonic() - t0) * 1000),
                attempts=1,
                error=msg,
                error_class=error_class,
            )

        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=self.timeout_s,
                headers=_client_headers(),
            ) as client:
                resp = client.get(request.normalized_url)
        except httpx.TimeoutException as e:
            return _fail("timeout", f"GET timeout: {e}")
        except Exception as e:
            return _fail("unknown", f"GET error: {type(e).__name__}: {e}")

        if 400 <= resp.status_code < 500:
            return _fail("http_4xx", f"HTTP {resp.status_code}")
        if 500 <= resp.status_code < 600:
            return _fail("http_5xx", f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            return _fail("unknown", f"HTTP {resp.status_code}")

        ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()

        artifacts = CaptureArtifacts()
        image_info: ImageInfo | None = None
        screenshot_sha: str | None = None
        text_sha: str | None = None

        if ct.startswith("image/"):
            image_info = ImageInfo(content_type=ct)
            ok, msg = _save_image(
                resp.content, artifact_dir / "screenshot.png", image_info
            )
            if not ok:
                return _fail("unknown", msg)
            artifacts.screenshot_path = "screenshot.png"
            screenshot_sha = _sha256(
                (artifact_dir / "screenshot.png").read_bytes()
            )
        elif ct == "text/plain":
            text_path = artifact_dir / "text.txt"
            text_path.write_bytes(resp.content)
            artifacts.text_path = "text.txt"
            text_sha = _sha256(resp.content)
        else:  # pragma: no cover - accepts() filters this
            return _fail("unknown", f"unsupported content-type: {ct}")

        return CaptureResult(
            request=request,
            status="ok",
            backend="http_direct",
            captured_at=datetime.now(timezone.utc),
            duration_ms=int((time.monotonic() - t0) * 1000),
            attempts=1,
            artifacts=artifacts,
            image_info=image_info,
            text_sha256=text_sha,
            screenshot_sha256=screenshot_sha,
        )


def _save_image(
    data: bytes, out_path: Path, info: ImageInfo
) -> tuple[bool, str]:
    try:
        from PIL import Image  # type: ignore
    except ImportError:  # pragma: no cover
        return False, "Pillow not installed; install capture[backends]"

    try:
        with Image.open(io.BytesIO(data)) as img:
            info.width = img.width
            info.height = img.height
            if img.mode in ("RGB", "RGBA", "L", "P"):
                img.save(out_path, format="PNG")
            else:
                img.convert("RGB").save(out_path, format="PNG")
    except Exception as e:
        return False, f"image decode failed: {type(e).__name__}: {e}"

    if not out_path.exists() or out_path.stat().st_size == 0:
        return False, "image save produced empty file"
    return True, "ok"
