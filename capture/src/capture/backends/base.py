"""Backend protocol for capture/.

Every backend takes a CaptureRequest + an output directory rooted at
``out_dir/captures/<slug>/`` and returns a fully populated
CaptureResult. The orchestrator owns retry/classification; backends
only run one attempt and classify their own errors.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from capture.contracts import CaptureRequest, CaptureResult


class Backend(Protocol):
    name: str

    def accepts(self, request: CaptureRequest, content_type: str | None) -> bool:
        """True if this backend should handle ``request``.

        ``content_type`` is the HEAD-probed MIME (None if HEAD failed or
        the orchestrator skipped the precheck).
        """
        ...

    def capture(
        self,
        request: CaptureRequest,
        artifact_dir: Path,
    ) -> CaptureResult:
        """Run one attempt. Must write artifacts inside ``artifact_dir``
        and return a CaptureResult. Errors are captured as failed
        results, not raised — the orchestrator decides whether to
        retry based on ``error_class``.
        """
        ...
