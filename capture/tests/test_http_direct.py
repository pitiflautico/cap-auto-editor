"""Tests for backends.http_direct. Uses httpx MockTransport — no net."""
from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest
from PIL import Image

from capture.backends.http_direct import HttpDirectBackend
from capture.contracts import CaptureRequest


def _req(url: str = "https://i.redd.it/abc.png") -> CaptureRequest:
    return CaptureRequest(
        url=url,
        normalized_url=url,
        slug="i-redd-it-abc",
    )


def _png_bytes(w: int = 32, h: int = 16) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


class _MockRouter:
    """Minimal router that drops into httpx.MockTransport."""

    def __init__(self, handlers: dict[str, httpx.Response]):
        self.handlers = handlers

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url}"
        for k, resp in self.handlers.items():
            if k == key or request.url.path.endswith(k.split(" ")[-1]):
                return resp
        return httpx.Response(404, text="not found")


@pytest.fixture
def patch_httpx(monkeypatch):
    def _apply(handlers: dict[str, httpx.Response]):
        orig_client = httpx.Client

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(_MockRouter(handlers))
            return orig_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", factory)
    return _apply


class TestAccepts:
    def test_accepts_image(self):
        b = HttpDirectBackend()
        assert b.accepts(_req(), "image/png")
        assert b.accepts(_req(), "image/jpeg")

    def test_accepts_plain_text(self):
        assert HttpDirectBackend().accepts(_req(), "text/plain")

    def test_rejects_html(self):
        assert not HttpDirectBackend().accepts(_req(), "text/html")

    def test_rejects_unknown(self):
        assert not HttpDirectBackend().accepts(_req(), None)


class TestImageCapture:
    def test_ok_roundtrip(self, patch_httpx, tmp_path: Path):
        png = _png_bytes(40, 20)
        patch_httpx({
            "GET https://i.redd.it/abc.png": httpx.Response(
                200, content=png, headers={"content-type": "image/png"}
            ),
        })
        result = HttpDirectBackend().capture(_req(), tmp_path)
        assert result.status == "ok"
        assert result.backend == "http_direct"
        assert result.artifacts.screenshot_path == "screenshot.png"
        assert (tmp_path / "screenshot.png").exists()
        assert result.image_info is not None
        assert result.image_info.content_type == "image/png"
        assert result.image_info.width == 40
        assert result.image_info.height == 20
        assert result.screenshot_sha256 is not None

    def test_404(self, patch_httpx, tmp_path: Path):
        patch_httpx({
            "GET https://i.redd.it/abc.png": httpx.Response(404, text="gone"),
        })
        result = HttpDirectBackend().capture(_req(), tmp_path)
        assert result.status == "failed"
        assert result.error_class == "http_4xx"

    def test_500(self, patch_httpx, tmp_path: Path):
        patch_httpx({
            "GET https://i.redd.it/abc.png": httpx.Response(500, text="boom"),
        })
        result = HttpDirectBackend().capture(_req(), tmp_path)
        assert result.status == "failed"
        assert result.error_class == "http_5xx"

    def test_corrupt_image(self, patch_httpx, tmp_path: Path):
        patch_httpx({
            "GET https://i.redd.it/abc.png": httpx.Response(
                200,
                content=b"not an image",
                headers={"content-type": "image/png"},
            ),
        })
        result = HttpDirectBackend().capture(_req(), tmp_path)
        assert result.status == "failed"
        assert result.error_class == "unknown"


class TestPlainText:
    def test_ok(self, patch_httpx, tmp_path: Path):
        body = "hello world"
        patch_httpx({
            "GET https://example.com/file.txt": httpx.Response(
                200,
                text=body,
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
        })
        req = CaptureRequest(
            url="https://example.com/file.txt",
            normalized_url="https://example.com/file.txt",
            slug="example-com-file",
        )
        result = HttpDirectBackend().capture(req, tmp_path)
        assert result.status == "ok"
        assert (tmp_path / "text.txt").read_text(encoding="utf-8") == body
        assert result.text_sha256 is not None
