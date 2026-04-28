"""Headless HyperFrames renderer — write a self-contained HTML doc to a
temporary HF project, run ``npx hyperframes render``, and return the
MP4 path.

Adapted from `pipeline_v4_frozen_20260423/agents/executor_tools/hyperframes_render.py`.
The v6 module trims it down to what the designer needs:
  • `_HYPERFRAMES_JSON`     — minimal hyperframes.json scaffold
  • `_sha256_of(path)`       — content hash
  • `_probe_duration(path)`  — ffprobe wrapper
  • `_run_hyperframes(html)` — write project + render, return (ok, msg)
  • `render_to_mp4(html, out_mp4, …)` — public wrapper
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("hf_designer.render")


_HYPERFRAMES_JSON = {
    "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
    "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
    "paths": {
        "blocks": "compositions",
        "components": "compositions/components",
        "assets": "assets",
    },
}


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe_duration(path: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            timeout=10,
        )
        return float(out.decode().strip())
    except Exception:
        return None


def _run_hyperframes(
    *,
    html_content: str,
    out_mp4: Path,
    fps: int = 24,
    quality: str = "draft",
    timeout_s: int = 180,
) -> tuple[bool, str]:
    """Write a temp HF project (hyperframes.json + index.html), run the
    HyperFrames CLI, and verify the resulting MP4 isn't empty.
    """
    with tempfile.TemporaryDirectory(prefix="hf_designer_") as tmp:
        proj = Path(tmp)
        (proj / "hyperframes.json").write_text(
            json.dumps(_HYPERFRAMES_JSON, indent=2), encoding="utf-8",
        )
        (proj / "index.html").write_text(html_content, encoding="utf-8")
        cmd = [
            "npx", "hyperframes", "render",
            "--output", str(out_mp4.resolve()),
            "--fps", str(fps),
            "--quality", quality,
            "--quiet",
        ]
        try:
            proc = subprocess.run(
                cmd, cwd=proj, capture_output=True, text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return False, f"hyperframes timeout ({timeout_s}s)"
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "")[-400:]
            return False, f"hyperframes exit={proc.returncode}: {err}"
        if not out_mp4.exists() or out_mp4.stat().st_size < 1000:
            return False, "hyperframes produced empty/missing mp4"
    return True, "ok"


def render_to_mp4(
    html: str,
    out_mp4: Path,
    *,
    duration_s: float = 6.0,
    fps: int = 24,
    quality: str = "draft",
    timeout_s: int = 180,
) -> dict:
    """Render an HTML+GSAP doc through HyperFrames CLI to MP4.

    Returns a status dict::

        {"status": "ok", "asset_path": "...", "duration_s": 6.0, "sha256": "..."}
        {"status": "failed", "message": "..."}
    """
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    ok, msg = _run_hyperframes(
        html_content=html, out_mp4=out_mp4,
        fps=fps, quality=quality, timeout_s=timeout_s,
    )
    if not ok:
        return {"status": "failed", "message": msg}
    return {
        "status": "ok",
        "asset_path": str(out_mp4),
        "duration_s": _probe_duration(out_mp4) or duration_s,
        "sha256": _sha256_of(out_mp4),
    }
