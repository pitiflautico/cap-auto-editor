"""Run v4's `agent4_builder.build()` from a v6 visual_plan dict.

The v4 module has no pyproject.toml — it lives as a flat package next
to the rest of `pipeline_v4_frozen_20260423/`. We expose its module
roots via `sys.path` only when the bridge is invoked, so unit tests
that don't touch real assets never load it.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("compositor.builder")


_V4_ROOT = (
    Path("/Volumes/DiscoExterno2/mac_offload/Projects/myavatar/"
         "pipeline_v4_frozen_20260423")
)


def _ensure_v4_on_syspath() -> None:
    """Prepend the v4 builder dirs to `sys.path` so `import builder` /
    `from layers.X import …` resolve. Idempotent.
    """
    paths_to_add = [
        _V4_ROOT / "agent4_builder",
        _V4_ROOT / "agent4_builder" / "shared",
        _V4_ROOT / "agent4_builder" / "effects",
        _V4_ROOT / "agent4_builder" / "layers",
        _V4_ROOT,                              # for `shared.capcut_constants`
    ]
    for p in paths_to_add:
        s = str(p.resolve())
        if s not in sys.path:
            sys.path.insert(0, s)


def write_visual_plan(visual_plan: dict, out_dir: Path) -> Path:
    """Persist the v4 visual_plan_resolved.json next to the build
    output. Useful for debugging and for re-running just the v4
    builder without re-doing the v6 adapter.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "visual_plan_resolved.json"
    path.write_text(
        json.dumps(visual_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def run_v4_build(
    *,
    visual_plan_path: Path,
    capcut_project_dir: Path,
    project_name: str | None = None,
) -> dict:
    """Invoke `agent4_builder.build()` and return its BuildResult as
    a JSON-serialisable dict.

    The v4 build writes the CapCut project tree (`draft_info.json` +
    `Resources/`) under `capcut_project_dir`. The caller is then free
    to copy that tree into CapCut's user-data Projects directory.
    """
    _ensure_v4_on_syspath()
    capcut_project_dir.mkdir(parents=True, exist_ok=True)
    # Lazy import — keeps unit tests of this module free of v4 deps.
    from builder import build as _v4_build         # type: ignore

    res = _v4_build(
        plan_path=str(visual_plan_path),
        output_dir=str(capcut_project_dir),
        project_name=project_name or capcut_project_dir.name,
    )
    return {
        "project_dir": getattr(res, "project_dir", str(capcut_project_dir)),
        "draft_info_path": getattr(res, "draft_info_path", ""),
        "warnings": list(getattr(res, "warnings", []) or []),
        "duration_us": getattr(res, "duration_us", 0),
    }


def install_to_capcut(project_dir: Path,
                      capcut_user_dir: Path | None = None) -> Path | None:
    """Copy the built CapCut project tree into CapCut's user data so
    the project shows up in the app launcher. macOS-only path.

    Returns the destination directory or None when the user data dir
    can't be located (e.g. running on Linux / CI).
    """
    if capcut_user_dir is None:
        default = Path.home() / (
            "Library/Containers/com.lemon.lvoverseas/Data/Movies/CapCut/"
            "User Data/Projects/com.lveditor.draft"
        )
        capcut_user_dir = default
    if not capcut_user_dir.exists():
        log.info("CapCut user data dir not found: %s", capcut_user_dir)
        return None
    dst = capcut_user_dir / project_dir.name
    if dst.exists():
        log.info("Removing previous install at %s", dst)
        import shutil
        shutil.rmtree(dst)
    import shutil
    shutil.copytree(project_dir, dst)
    return dst
