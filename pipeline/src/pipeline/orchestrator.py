"""Pipeline orchestrator — planner + runner."""
from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from pipeline.contracts import (
    ManifestPhase,
    PhaseDescriptor,
    PhaseResult,
    PipelineManifest,
    RunContext,
    RunResult,
)
from pipeline.registry import PIPELINE_PHASES
from pipeline.tracer import OrchestratorTracer


# ── Topological sort ────────────────────────────────────────────────

def _topo_sort(descriptors: list[PhaseDescriptor]) -> list[PhaseDescriptor]:
    """Kahn's algorithm. Raises ValueError on cycle."""
    name_map = {d.name: d for d in descriptors}
    in_degree = {d.name: 0 for d in descriptors}
    for d in descriptors:
        for dep in d.depends_on:
            if dep in in_degree:
                in_degree[d.name] += 1

    queue = [d for d in descriptors if in_degree[d.name] == 0]
    queue.sort(key=lambda d: d.order)
    result = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for d in sorted(descriptors, key=lambda x: x.order):
            if node.name in d.depends_on:
                in_degree[d.name] -= 1
                if in_degree[d.name] == 0:
                    queue.append(d)
    if len(result) != len(descriptors):
        raise ValueError("Cycle detected in phase dependency graph")
    return result


# ── Audio extraction ─────────────────────────────────────────────────

def _extract_audio(video: Path, run_dir: Path) -> Path:
    """Extract mono 16kHz WAV from video. Returns path to wav."""
    wav = run_dir / "audio.wav"
    if wav.exists():
        return wav
    cmd = [
        "ffmpeg", "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000",
        str(wav), "-y",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}):\n{result.stderr}")
    return wav


# ── Manifest writer ──────────────────────────────────────────────────

def _write_manifest(
    run_dir: Path,
    run_name: str,
    video: Path | None,
    sources: Path | None,
    phases: list[PhaseDescriptor],
) -> None:
    manifest = PipelineManifest(
        run_name=run_name,
        created_at=datetime.now(tz=timezone.utc),
        video_input=str(video) if video else "",
        sources_input=str(sources) if sources else None,
        phases=[d.to_manifest_phase() for d in phases],
    )
    (run_dir / "pipeline_manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )


# ── Phase runner ─────────────────────────────────────────────────────

def _run_phase(
    descriptor: PhaseDescriptor,
    ctx: RunContext,
    run_dir: Path,
    tracer: OrchestratorTracer,
) -> PhaseResult:
    phase_dir = run_dir / descriptor.out_subdir
    phase_dir.mkdir(parents=True, exist_ok=True)

    extra_args = descriptor.cli_args(ctx, phase_dir)
    cmd = descriptor.cli_command + extra_args
    stdout_log = phase_dir / "stdout.log"
    stderr_log = phase_dir / "stderr.log"

    t0 = time.monotonic()
    pid = None
    proc = None

    try:
        with stdout_log.open("w") as fout, stderr_log.open("w") as ferr:
            proc = subprocess.Popen(
                cmd,
                stdout=fout,
                stderr=ferr,
            )
            pid = proc.pid
            tracer.phase_launched(descriptor.name, cmd, pid)

            try:
                proc.wait(timeout=descriptor.timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                duration_ms = int((time.monotonic() - t0) * 1000)
                tracer.phase_failed(descriptor.name, duration_ms, "timeout")
                return PhaseResult(
                    name=descriptor.name,
                    ok=False,
                    exit_code=None,
                    duration_ms=duration_ms,
                    error="timeout",
                )

        duration_ms = int((time.monotonic() - t0) * 1000)
        exit_code = proc.returncode
        if exit_code == 0:
            tracer.phase_completed(descriptor.name, duration_ms, exit_code)
            return PhaseResult(name=descriptor.name, ok=True, exit_code=exit_code, duration_ms=duration_ms)
        else:
            tracer.phase_failed(descriptor.name, duration_ms, f"exit_code={exit_code}")
            return PhaseResult(
                name=descriptor.name,
                ok=False,
                exit_code=exit_code,
                duration_ms=duration_ms,
                error=f"exit_code={exit_code}",
            )

    except KeyboardInterrupt:
        if proc is not None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        duration_ms = int((time.monotonic() - t0) * 1000)
        tracer.phase_failed(descriptor.name, duration_ms, "interrupted")
        raise


# ── Main run entrypoint ───────────────────────────────────────────────

def run(
    run_dir: Path,
    run_name: str,
    video: Path | None,
    sources: Path | None,
    phases_filter: list[str] | None = None,
) -> RunResult:
    """Execute the pipeline. Returns RunResult."""
    # Ensure run_dir exists
    run_dir.mkdir(parents=True, exist_ok=True)

    # Select and sort phases
    candidates = PIPELINE_PHASES
    if phases_filter:
        candidates = [d for d in candidates if d.name in phases_filter]
    ordered = _topo_sort(candidates)

    # Write manifest first
    _write_manifest(run_dir, run_name, video, sources, ordered)

    tracer = OrchestratorTracer(run_dir)
    tracer.run_start(run_name, str(video) if video else None, str(sources) if sources else None)

    t_run_start = time.monotonic()

    # Extract audio if video is present and polish is in the plan
    ctx = RunContext(
        run_dir=run_dir,
        run_name=run_name,
        video=video,
        sources=sources,
        audio_wav=None,
    )

    needs_audio = any(d.name == "polish" for d in ordered) and video is not None
    if needs_audio:
        suffix = video.suffix.lower()
        if suffix in (".webm", ".mp4", ".mov", ".mkv", ".avi"):
            try:
                wav = _extract_audio(video, run_dir)
                ctx = RunContext(
                    run_dir=run_dir,
                    run_name=run_name,
                    video=video,
                    sources=sources,
                    audio_wav=wav,
                )
            except RuntimeError as exc:
                # non-fatal: polish will proceed without audio
                print(f"[pipeline] Warning: audio extraction failed: {exc}", file=sys.stderr)

    # Track completed phase names for dependency checking
    completed: set[str] = set()
    phase_results: list[PhaseResult] = []
    run_ok = True

    for descriptor in ordered:
        # Check deps satisfied
        missing_deps = [dep for dep in descriptor.depends_on if dep not in completed]
        if missing_deps:
            # deps failed or skipped — skip this phase
            result = PhaseResult(
                name=descriptor.name,
                ok=False,
                error=f"skipped — missing deps: {missing_deps}",
            )
            phase_results.append(result)
            run_ok = False
            continue

        attempt = 0
        max_attempts = max(1, descriptor.retry_max + 1)
        while attempt < max_attempts:
            attempt += 1
            result = _run_phase(descriptor, ctx, run_dir, tracer)
            if result.ok:
                break
            if attempt < max_attempts and descriptor.on_failure == "retry":
                print(f"[pipeline] Retrying {descriptor.name} (attempt {attempt}/{max_attempts}) in 5s…", file=sys.stderr)
                time.sleep(5)

        phase_results.append(result)

        if result.ok:
            completed.add(descriptor.name)
        else:
            run_ok = False
            if descriptor.on_failure == "abort":
                # abort: stop pipeline
                break
            elif descriptor.on_failure == "skip":
                # skip: continue without this phase completed
                continue

    run_duration_ms = int((time.monotonic() - t_run_start) * 1000)
    tracer.run_done(ok=run_ok, duration_ms=run_duration_ms)

    return RunResult(
        run_name=run_name,
        ok=run_ok,
        phases=phase_results,
        duration_ms=run_duration_ms,
    )
