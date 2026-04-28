"""Headless HyperFrames render of the compositor index.html.

Unlike `hf_designer/render.py` (which writes to a temp dir and trashes
it), the compositor *needs* its project on disk so the relative `src=`
of every b-roll asset and the `<audio>` track resolves. We materialise
a real `project_dir` and tell HyperFrames to render from there.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("compositor.render")


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


def write_project(project_dir: Path, html: str) -> Path:
    """Write the minimal HF project (`hyperframes.json` + `index.html`)
    into `project_dir`. Caller is responsible for any extra symlinks /
    asset staging — the absolute paths in the HTML resolve fine when
    Chromium has --allow-file-access-from-files; HF runs that way.
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "hyperframes.json").write_text(
        json.dumps(_HYPERFRAMES_JSON, indent=2), encoding="utf-8",
    )
    index = project_dir / "index.html"
    index.write_text(html, encoding="utf-8")
    return index


def render_to_mp4(
    *,
    project_dir: Path,
    out_mp4: Path,
    fps: int = 30,
    quality: str = "draft",
    timeout_s: int = 1200,
) -> dict:
    """Run `npx hyperframes render --output ... --fps ...` from
    project_dir. Returns a status dict identical in shape to
    hf_designer.render.render_to_mp4 so the orchestrator can treat
    them uniformly.
    """
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "npx", "hyperframes", "render",
        "--output", str(out_mp4.resolve()),
        "--fps", str(fps),
        "--quality", quality,
        "--quiet",
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=project_dir, capture_output=True, text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"status": "failed",
                "message": f"hyperframes timeout ({timeout_s}s)"}
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[-600:]
        return {"status": "failed",
                "message": f"hyperframes exit={proc.returncode}: {err}"}
    if not out_mp4.exists() or out_mp4.stat().st_size < 1000:
        return {"status": "failed",
                "message": "hyperframes produced empty/missing mp4"}
    return {
        "status": "ok",
        "asset_path": str(out_mp4),
        "duration_s": _probe_duration(out_mp4),
        "sha256": _sha256_of(out_mp4),
    }
