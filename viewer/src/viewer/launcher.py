"""Viewer launcher — auto-start uvicorn + auto-open browser.

API:
    ensure_running(port, roots, timeout_s) -> base_url
    open_pipeline(run_name, port, roots) -> url
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def ensure_running(
    port: int = 8765,
    roots: list[Path] | None = None,
    timeout_s: float = 10.0,
) -> str:
    """Return base URL (e.g. 'http://127.0.0.1:8765').

    Launches uvicorn detached via Popen if nothing listens on port.
    Socket probe every 0.3s until 200 OK from GET / or timeout.
    Idempotent: no-op if already up AND its VIEWER_ROOTS covers `roots`.

    If a viewer is up but was started with stale roots (e.g. legacy /tmp
    while we now write to ~/myavatar/runs), we kill it and relaunch with
    the correct env. Otherwise the user sees "Pipeline not found".
    """
    base_url = f"http://127.0.0.1:{port}"

    if _port_is_up(port):
        if roots and not _roots_covered(base_url, roots):
            _kill_listener(port)
            # Brief pause so the OS releases the port before relaunch.
            for _ in range(20):
                if not _port_is_up(port):
                    break
                time.sleep(0.1)
        else:
            return base_url

    env = dict(os.environ)
    if roots:
        env["VIEWER_ROOTS"] = ":".join(str(r) for r in roots)

    cmd = [
        sys.executable, "-m", "uvicorn",
        "viewer.app:app",
        "--host", "127.0.0.1",
        "--port", str(port),
        "--reload",
    ]
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _port_is_up(port) and _http_ok(base_url):
            return base_url
        time.sleep(0.3)

    raise RuntimeError(
        f"Viewer did not come up on port {port} within {timeout_s}s.\n"
        f"Try running manually: uvicorn viewer.app:app --port {port}"
    )


def open_pipeline(
    run_name: str,
    port: int = 8765,
    roots: list[Path] | None = None,
) -> str:
    """Ensure viewer is running, then open the browser to the pipeline URL.

    Returns the URL opened.
    """
    base_url = ensure_running(port=port, roots=roots)
    url = f"{base_url}/pipeline/{run_name}"
    webbrowser.open(url)
    return url


# ── Private helpers ──────────────────────────────────────────────────

def _port_is_up(port: int) -> bool:
    """True if something is listening on 127.0.0.1:port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _http_ok(base_url: str) -> bool:
    """True if GET base_url returns HTTP 200."""
    try:
        import httpx
        resp = httpx.get(base_url + "/", timeout=1.0)
        return resp.status_code == 200
    except Exception:
        return False


def _roots_covered(base_url: str, wanted: list[Path]) -> bool:
    """True if the running viewer's VIEWER_ROOTS contains every wanted root.

    Older viewers without /api/health return 404; we treat that as "unknown"
    and ask the caller to relaunch defensively (returning False).
    """
    try:
        import httpx
        resp = httpx.get(base_url + "/api/health", timeout=1.0)
        if resp.status_code != 200:
            return False
        live_roots = {Path(p).resolve() for p in resp.json().get("roots", [])}
    except Exception:
        return False
    return all(Path(w).resolve() in live_roots for w in wanted)


def _kill_listener(port: int) -> None:
    """Terminate whatever process is bound to ``port`` on 127.0.0.1.

    Best-effort: SIGTERM via lsof. Used to evict a stale viewer before we
    relaunch with the correct env.
    """
    try:
        out = subprocess.run(
            ["lsof", "-tiTCP:" + str(port), "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=2,
        )
        for pid_str in out.stdout.split():
            try:
                os.kill(int(pid_str), 15)  # SIGTERM
            except (ValueError, ProcessLookupError):
                continue
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return
