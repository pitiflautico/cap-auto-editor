"""Tests for compositor.render — without invoking the real `npx`."""
from __future__ import annotations

import json
from pathlib import Path

from compositor_hf import render as render_mod


def _stub_subprocess_run(monkeypatch, *, returncode: int, write: bytes | None = None,
                          stderr: str = "", stdout: str = ""):
    captured: dict = {"calls": []}

    class _Result:
        def __init__(self):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake(cmd, **kw):
        captured["calls"].append({"cmd": cmd, "kw": kw})
        # If we expect success, write a fake mp4 to the --output target
        if write is not None and "--output" in cmd:
            idx = cmd.index("--output")
            out = Path(cmd[idx + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(write)
        return _Result()

    monkeypatch.setattr(render_mod.subprocess, "run", _fake)
    monkeypatch.setattr(render_mod, "_probe_duration", lambda p: 5.5)
    return captured


def test_write_project_creates_index_and_hyperframes_json(tmp_path: Path):
    proj = tmp_path / "proj"
    out = render_mod.write_project(proj, "<!doctype html><html></html>")
    assert out == proj / "index.html"
    assert out.exists()
    hf = json.loads((proj / "hyperframes.json").read_text())
    assert hf["paths"]["assets"] == "assets"


def test_render_to_mp4_returns_ok_when_renderer_succeeds(tmp_path: Path, monkeypatch):
    proj = tmp_path / "proj"; proj.mkdir()
    out = tmp_path / "out" / "final.mp4"
    captured = _stub_subprocess_run(monkeypatch, returncode=0, write=b"x" * 8192)
    res = render_mod.render_to_mp4(project_dir=proj, out_mp4=out, fps=30)
    assert res["status"] == "ok"
    assert res["asset_path"] == str(out)
    assert res["duration_s"] == 5.5
    assert len(res["sha256"]) == 64
    cmd = captured["calls"][0]["cmd"]
    assert cmd[:3] == ["npx", "hyperframes", "render"]
    assert "--fps" in cmd and "30" in cmd
    assert "--quiet" in cmd


def test_render_to_mp4_returns_failed_on_nonzero_exit(tmp_path: Path, monkeypatch):
    proj = tmp_path / "proj"; proj.mkdir()
    out = tmp_path / "final.mp4"
    _stub_subprocess_run(monkeypatch, returncode=1,
                          stderr="rendering failed: deadline exceeded")
    res = render_mod.render_to_mp4(project_dir=proj, out_mp4=out)
    assert res["status"] == "failed"
    assert "deadline" in res["message"]


def test_render_to_mp4_returns_failed_on_empty_output(tmp_path: Path, monkeypatch):
    proj = tmp_path / "proj"; proj.mkdir()
    out = tmp_path / "final.mp4"
    # subprocess "succeeds" but produces nothing
    _stub_subprocess_run(monkeypatch, returncode=0, write=None)
    res = render_mod.render_to_mp4(project_dir=proj, out_mp4=out)
    assert res["status"] == "failed"
    assert "empty" in res["message"]
