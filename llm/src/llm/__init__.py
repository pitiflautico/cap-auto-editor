"""llm — Shared LLM provider package for myavatar v6.

See INTERFACE.md for the frozen contract (v1.0).

Quick start:
    from llm import complete, ClaudePool, Provider

    # High-level (recommended):
    result = complete("Summarize this paragraph: ...", provider="claude_pool", model="haiku")

    # Low-level escape hatch:
    pool = ClaudePool(default_model="haiku")
"""
from .claude_pool import ClaudePool, RunResult, run_sync, run_vision_sync
from .contracts import CompleteRequest, CompleteResponse, ProviderName as Provider
from .providers import complete
from .prompts import extract_json

__version__ = "1.0.0"

__all__ = [
    "complete",
    "ClaudePool",
    "RunResult",
    "run_sync",
    "run_vision_sync",
    "CompleteRequest",
    "CompleteResponse",
    "Provider",
    "extract_json",
]
