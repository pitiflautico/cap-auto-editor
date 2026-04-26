"""Tests for capture.contracts — schema integrity + JSON roundtrip."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from capture.contracts import (
    CaptureArtifacts,
    CaptureManifest,
    CaptureRequest,
    CaptureResult,
    ImageInfo,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _req(i: int = 0) -> CaptureRequest:
    return CaptureRequest(
        url=f"https://example.com/post/{i}",
        normalized_url=f"https://example.com/post/{i}",
        slug=f"example-com-post-{i}",
        priority=i,
    )


class TestCaptureRequest:
    def test_frozen(self):
        r = _req()
        with pytest.raises(ValidationError):
            r.url = "https://other.com"  # type: ignore[misc]

    def test_requires_core_fields(self):
        with pytest.raises(ValidationError):
            CaptureRequest.model_validate({"url": "https://x.com"})


class TestCaptureResult:
    def test_minimal_ok_roundtrip(self):
        r = CaptureResult(
            request=_req(),
            status="ok",
            backend="browser_sdk",
            captured_at=_now(),
            duration_ms=1234,
            attempts=1,
        )
        raw = r.model_dump_json()
        back = CaptureResult.model_validate_json(raw)
        assert back.status == "ok"
        assert back.attempts == 1
        assert back.artifacts.text_path is None
        assert back.image_info is None

    def test_failed_full_roundtrip(self):
        r = CaptureResult(
            request=_req(),
            status="failed",
            backend="browser_sdk",
            captured_at=_now(),
            duration_ms=500,
            attempts=3,
            error="timeout after 10s",
            error_class="timeout",
        )
        back = CaptureResult.model_validate_json(r.model_dump_json())
        assert back.error_class == "timeout"

    def test_failed_requires_error_class(self):
        with pytest.raises(ValidationError):
            CaptureResult(
                request=_req(),
                status="failed",
                backend="browser_sdk",
                captured_at=_now(),
                duration_ms=0,
                error="something",
                error_class=None,
            )

    def test_failed_requires_error_message(self):
        with pytest.raises(ValidationError):
            CaptureResult(
                request=_req(),
                status="failed",
                backend="browser_sdk",
                captured_at=_now(),
                duration_ms=0,
                error=None,
                error_class="timeout",
            )

    def test_ok_does_not_require_error(self):
        r = CaptureResult(
            request=_req(),
            status="ok",
            backend="browser_sdk",
            captured_at=_now(),
            duration_ms=100,
        )
        assert r.error is None
        assert r.error_class is None

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            CaptureResult(
                request=_req(),
                status="weird",  # type: ignore[arg-type]
                backend="browser_sdk",
                captured_at=_now(),
                duration_ms=0,
            )

    def test_invalid_backend_rejected(self):
        with pytest.raises(ValidationError):
            CaptureResult(
                request=_req(),
                status="ok",
                backend="curl",  # type: ignore[arg-type]
                captured_at=_now(),
                duration_ms=0,
            )

    def test_image_info_attached(self):
        r = CaptureResult(
            request=_req(),
            status="ok",
            backend="http_direct",
            captured_at=_now(),
            duration_ms=80,
            image_info=ImageInfo(content_type="image/png", width=1080, height=1920),
        )
        back = CaptureResult.model_validate_json(r.model_dump_json())
        assert back.image_info.content_type == "image/png"
        assert back.image_info.width == 1080


class TestImageInfo:
    def test_requires_content_type(self):
        with pytest.raises(ValidationError):
            ImageInfo()  # type: ignore[call-arg]

    def test_dimensions_optional(self):
        info = ImageInfo(content_type="image/jpeg")
        assert info.width is None
        assert info.height is None


class TestCaptureManifest:
    def test_empty_manifest_roundtrip(self):
        m = CaptureManifest(
            created_at=_now(),
            out_dir="/tmp/out",
            backend_default="browser_sdk",
        )
        back = CaptureManifest.model_validate_json(m.model_dump_json())
        assert back.schema_version == "2.0.0"
        assert back.results == []

    def test_with_results(self):
        results = [
            CaptureResult(
                request=_req(i),
                status="ok",
                backend="browser_sdk",
                captured_at=_now(),
                duration_ms=100 * i,
                artifacts=CaptureArtifacts(
                    text_path=f"captures/example-com-post-{i}/text.txt",
                    screenshot_path=f"captures/example-com-post-{i}/screenshot.png",
                ),
                text_sha256="0" * 64,
            )
            for i in range(3)
        ]
        m = CaptureManifest(
            created_at=_now(),
            out_dir="/tmp/out",
            backend_default="browser_sdk",
            results=results,
        )
        back = CaptureManifest.model_validate_json(m.model_dump_json())
        assert len(back.results) == 3
        assert back.results[2].artifacts.screenshot_path.endswith("screenshot.png")
