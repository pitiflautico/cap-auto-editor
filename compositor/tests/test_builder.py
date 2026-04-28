"""Tests for compositor.builder — verifies sys.path / project install
without invoking the real v4 agent4_builder.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from compositor import builder as bmod


def test_ensure_v4_on_syspath_inserts_paths_and_is_idempotent():
    bmod._ensure_v4_on_syspath()
    snap = list(sys.path)
    assert any("agent4_builder" in p for p in snap)
    bmod._ensure_v4_on_syspath()       # second call must not duplicate
    duplicates = sum(1 for p in sys.path
                     if p.endswith("/agent4_builder"))
    assert duplicates == 1


def test_write_visual_plan_persists_pretty_json(tmp_path: Path):
    plan = {"name": "x", "beats": []}
    out = bmod.write_visual_plan(plan, tmp_path)
    assert out == tmp_path / "visual_plan_resolved.json"
    parsed = json.loads(out.read_text())
    assert parsed["name"] == "x"


def test_install_to_capcut_returns_none_when_dir_missing(tmp_path: Path):
    """If CapCut isn't installed (typical in CI / Linux), the helper
    returns None instead of crashing."""
    project_dir = tmp_path / "p"
    project_dir.mkdir()
    (project_dir / "draft_info.json").write_text("{}")
    fake_user = tmp_path / "nonexistent_capcut_user_data"
    out = bmod.install_to_capcut(project_dir, capcut_user_dir=fake_user)
    assert out is None


def test_install_to_capcut_copies_project_tree_when_dir_exists(tmp_path: Path):
    project_dir = tmp_path / "p"
    project_dir.mkdir()
    (project_dir / "draft_info.json").write_text('{"hi": 1}')
    (project_dir / "Resources").mkdir()
    (project_dir / "Resources" / "asset.bin").write_bytes(b"x")
    user_dir = tmp_path / "capcut_user_data"
    user_dir.mkdir()
    out = bmod.install_to_capcut(project_dir, capcut_user_dir=user_dir)
    assert out == user_dir / "p"
    assert (out / "draft_info.json").exists()
    assert (out / "Resources" / "asset.bin").read_bytes() == b"x"


def test_install_to_capcut_overwrites_previous_install(tmp_path: Path):
    project_dir = tmp_path / "p"
    project_dir.mkdir()
    (project_dir / "draft_info.json").write_text('{"version": 2}')
    user_dir = tmp_path / "user"; user_dir.mkdir()
    # Simulate a prior install with stale content
    stale = user_dir / "p"
    stale.mkdir()
    (stale / "draft_info.json").write_text('{"version": 1}')
    out = bmod.install_to_capcut(project_dir, capcut_user_dir=user_dir)
    assert json.loads((out / "draft_info.json").read_text())["version"] == 2


def test_run_v4_build_propagates_v4_buildresult_fields(tmp_path: Path,
                                                        monkeypatch):
    """`run_v4_build` should call into v4 `builder.build()` and surface
    its BuildResult fields back as a plain dict — no v4 import here in
    the test, we monkeypatch the lazy import.
    """
    visual_plan = tmp_path / "vp.json"
    visual_plan.write_text(json.dumps({"name": "fake", "beats": []}))
    proj_dir = tmp_path / "out"

    class _StubResult:
        def __init__(self):
            self.project_dir = str(proj_dir)
            self.draft_info_path = str(proj_dir / "draft_info.json")
            self.warnings = ["BROLL_TOO_SHORT b002"]
            self.duration_us = 50_700_000

    def _fake_v4_build(plan_path, output_dir, project_name=""):
        assert plan_path == str(visual_plan)
        assert Path(output_dir) == proj_dir
        return _StubResult()

    # Stand in for the lazy `from builder import build as _v4_build`
    fake_module = type(sys)("builder")
    fake_module.build = _fake_v4_build       # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "builder", fake_module)

    out = bmod.run_v4_build(
        visual_plan_path=visual_plan,
        capcut_project_dir=proj_dir,
        project_name="fake",
    )
    assert out["draft_info_path"].endswith("/draft_info.json")
    assert out["warnings"] == ["BROLL_TOO_SHORT b002"]
    assert out["duration_us"] == 50_700_000
