"""Recapture a single URL — invoke the existing v6/capture/ binary.

Auto_source asks capture/ to run on a one-line sources file. The captures
land alongside the original ones (same out_dir/captures/<slug>/), and the
new manifest is merged with the original.
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("auto_source.recapture")


_CAPTURE_BIN_DEFAULT = (
    "/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/v6/"
    "capture/.venv/bin/capture"
)


def recapture_urls(
    urls: list[str],
    capture_out_dir: Path,
    *,
    capture_bin: str = _CAPTURE_BIN_DEFAULT,
    timeout_s: int = 180,
) -> dict | None:
    """Run capture on the given URLs INTO the existing capture_out_dir.

    Captures append to ``captures/<slug>/`` and a fresh manifest is written.
    Returns the parsed manifest dict (with `results` for the NEW URLs only),
    or None on failure.
    """
    if not urls:
        return None
    capture_out_dir.mkdir(parents=True, exist_ok=True)

    # Write the URLs to a temp sources file so capture can read them.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for u in urls:
            f.write(u.rstrip() + "\n")
        sources_file = Path(f.name)

    cmd = [
        capture_bin, "run",
        "--sources", str(sources_file),
        "--out", str(capture_out_dir),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout_s)
    except subprocess.TimeoutExpired:
        log.warning("capture recapture timed out on %d URLs", len(urls))
        return None
    finally:
        try:
            sources_file.unlink()
        except OSError:
            pass

    if proc.returncode != 0:
        log.warning("capture recapture failed (exit %d): %s",
                    proc.returncode, (proc.stderr or "")[:300])
        return None

    manifest_path = capture_out_dir / "capture_manifest.json"
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("could not read recapture manifest: %s", exc)
        return None
