"""Pydantic contracts for the pipeline orchestrator."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Literal

from pydantic import BaseModel, field_validator


# ── RenderArtifact ──────────────────────────────────────────────────

VALID_ARTIFACT_TYPES = frozenset(
    {"transcript", "json_table", "image_gallery", "text_preview", "key_value",
     "iframe", "timeline"}
)


class RenderArtifact(BaseModel):
    """Descriptor for a single piece of renderable output in the viewer."""

    type: Literal["transcript", "json_table", "image_gallery", "text_preview",
                  "key_value", "iframe", "timeline"]
    title: str
    path: str | None = None          # relative to phase out_subdir
    path_pattern: str | None = None  # glob relative to phase out_subdir
    options: dict[str, Any] = {}

    @field_validator("type")
    @classmethod
    def check_type(cls, v: str) -> str:
        if v not in VALID_ARTIFACT_TYPES:
            raise ValueError(f"Invalid artifact type {v!r}. Must be one of: {sorted(VALID_ARTIFACT_TYPES)}")
        return v


# ── RunContext ──────────────────────────────────────────────────────

class RunContext(BaseModel):
    """Everything a phase descriptor needs to build its CLI args."""

    run_dir: Any          # Path
    run_name: str
    video: Any | None     # Path | None
    sources: Any | None   # Path | None
    audio_wav: Any | None = None   # Path | None — set after audio extraction

    @property
    def phase_out_dir(self) -> Any:
        """Not directly useful on RunContext — descriptors compute per-phase."""
        return self.run_dir


# ── ManifestPhase (serialisable subset of PhaseDescriptor) ─────────

class ManifestPhase(BaseModel):
    """Serialisable representation of a phase for pipeline_manifest.json."""

    name: str
    display_name: str
    order: int
    out_subdir: str
    depends_on: list[str]
    render_artifacts: list[RenderArtifact]


# ── PipelineManifest ────────────────────────────────────────────────

class PipelineManifest(BaseModel):
    """Written once at run start; reader is the viewer."""

    schema_version: str = "1.0.0"
    run_name: str
    created_at: datetime
    video_input: str
    sources_input: str | None = None
    phases: list[ManifestPhase]


# ── PhaseDescriptor (runtime — not serialised directly) ────────────

class PhaseDescriptor(BaseModel):
    """Full descriptor including callable — lives only in registry, not on disk."""

    name: str
    display_name: str
    order: int
    out_subdir: str
    cli_command: list[str]
    # Not stored on disk — excluded from model_dump; callable
    cli_args: Any  # Callable[[RunContext, Path], list[str]]
    depends_on: list[str]
    on_failure: Literal["abort", "skip", "retry"] = "abort"
    retry_max: int = 0
    timeout_s: int = 600
    render_artifacts: list[RenderArtifact]

    model_config = {"arbitrary_types_allowed": True}

    def to_manifest_phase(self) -> ManifestPhase:
        return ManifestPhase(
            name=self.name,
            display_name=self.display_name,
            order=self.order,
            out_subdir=self.out_subdir,
            depends_on=self.depends_on,
            render_artifacts=self.render_artifacts,
        )


# ── RunResult ───────────────────────────────────────────────────────

class PhaseResult(BaseModel):
    name: str
    ok: bool
    exit_code: int | None = None
    duration_ms: int | None = None
    error: str | None = None


class RunResult(BaseModel):
    run_name: str
    ok: bool
    phases: list[PhaseResult]
    duration_ms: int | None = None
