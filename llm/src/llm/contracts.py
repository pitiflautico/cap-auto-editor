"""Pydantic contracts for v6/llm/.

Source of truth: INTERFACE.md (v1.0 FROZEN).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ProviderName = Literal["claude_pool", "anthropic_api", "gemini", "openai", "deepseek"]


class CompleteRequest(BaseModel):
    prompt: str
    system_prompt: str | None = None
    provider: ProviderName = "claude_pool"
    model: str = "haiku"
    timeout_s: int = 60
    max_turns: int = 3
    as_json: bool = False
    # Tool restrictions (claude_pool only). None = no restriction.
    # [] = explicitly NO tools (force pure-text generation, fastest path).
    # ["Bash", "Read"] = only those tools allowed.
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None


class CompleteResponse(BaseModel):
    text: str
    json_data: dict[str, Any] | None = None   # parsed JSON if as_json=True; named json_data to avoid shadowing BaseModel.json()
    success: bool
    duration_ms: int
    provider: ProviderName
    model: str
