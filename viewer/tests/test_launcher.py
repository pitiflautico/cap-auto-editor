"""Tests for viewer.launcher — mocked Popen + socket probe."""
from __future__ import annotations

import webbrowser
from pathlib import Path
from unittest.mock import MagicMock, patch, call


# ── ensure_running: already up → no Popen ───────────────────────────

class TestEnsureRunning:
    def test_already_up_no_popen(self):
        """If port is already up, Popen is NOT called."""
        with (
            patch("viewer.launcher._port_is_up", return_value=True),
            patch("viewer.launcher._http_ok", return_value=True),
            patch("viewer.launcher.subprocess.Popen") as mock_popen,
        ):
            from viewer.launcher import ensure_running
            url = ensure_running(port=8765)
            assert url == "http://127.0.0.1:8765"
            mock_popen.assert_not_called()

    def test_not_up_launches_popen(self):
        """If port is NOT up, Popen is called once."""
        import viewer.launcher as launcher_mod
        call_count = 0

        def fake_port_is_up(port):
            nonlocal call_count
            call_count += 1
            # First call (fast check) returns False; second (poll) returns True
            return call_count > 1

        with (
            patch("viewer.launcher._port_is_up", side_effect=fake_port_is_up),
            patch("viewer.launcher._http_ok", return_value=True),
            patch("viewer.launcher.subprocess.Popen") as mock_popen,
            patch("viewer.launcher.time.sleep"),
        ):
            url = launcher_mod.ensure_running(port=8765, timeout_s=2.0)
            assert url == "http://127.0.0.1:8765"
            assert mock_popen.call_count == 1

    def test_timeout_raises(self):
        """If viewer doesn't come up within timeout, RuntimeError is raised."""
        import viewer.launcher as launcher_mod
        with (
            patch("viewer.launcher._port_is_up", return_value=False),
            patch("viewer.launcher._http_ok", return_value=False),
            patch("viewer.launcher.subprocess.Popen"),
            patch("viewer.launcher.time.sleep"),
        ):
            import pytest
            with pytest.raises(RuntimeError, match="port 9999"):
                launcher_mod.ensure_running(port=9999, timeout_s=0.01)

    def test_sets_viewer_roots_env(self):
        """VIEWER_ROOTS is set in subprocess env when roots are provided."""
        import viewer.launcher as launcher_mod
        captured_env = {}

        def fake_popen(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return MagicMock()

        call_count = 0

        def fake_port_is_up(port):
            nonlocal call_count
            call_count += 1
            return call_count > 1

        with (
            patch("viewer.launcher._port_is_up", side_effect=fake_port_is_up),
            patch("viewer.launcher._http_ok", return_value=True),
            patch("viewer.launcher.subprocess.Popen", side_effect=fake_popen),
            patch("viewer.launcher.time.sleep"),
        ):
            launcher_mod.ensure_running(port=8765, roots=[Path("/tmp/runs")])
            assert "VIEWER_ROOTS" in captured_env
            assert "/tmp/runs" in captured_env["VIEWER_ROOTS"]


# ── open_pipeline: ensure + webbrowser.open ─────────────────────────

class TestOpenPipeline:
    def test_opens_browser_with_correct_url(self):
        """open_pipeline calls webbrowser.open with pipeline URL."""
        with (
            patch("viewer.launcher.ensure_running", return_value="http://127.0.0.1:8765"),
            patch("viewer.launcher.webbrowser.open") as mock_open,
        ):
            import viewer.launcher as launcher_mod
            url = launcher_mod.open_pipeline("my_run", port=8765)
            assert url == "http://127.0.0.1:8765/pipeline/my_run"
            mock_open.assert_called_once_with("http://127.0.0.1:8765/pipeline/my_run")

    def test_returns_url(self):
        import viewer.launcher as launcher_mod
        with (
            patch("viewer.launcher.ensure_running", return_value="http://127.0.0.1:9000"),
            patch("viewer.launcher.webbrowser.open"),
        ):
            url = launcher_mod.open_pipeline("run_xyz", port=9000)
            assert "run_xyz" in url
            assert "9000" in url
