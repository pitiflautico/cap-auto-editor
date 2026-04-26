"""Provider registry + dispatch for v6/llm/.

Adding a new provider: 2 lines — add a handler function and register it
in _REGISTRY below.

Registered providers:
  claude_pool   — IMPLEMENTED. Uses claude-code-sdk + Claude Code subscription.
                  No API key needed. Recommended default.
  anthropic_api — STUB. Requires ANTHROPIC_API_KEY env var. Not wired.
  gemini        — STUB. Not wired.
  openai        — STUB. Not wired.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from .contracts import CompleteRequest, CompleteResponse, ProviderName
from .prompts import extract_json


# ── Provider handlers ─────────────────────────────────────────────────────────

def _handle_claude_pool(req: CompleteRequest, *,
                         on_text=None, on_thinking=None) -> CompleteResponse:
    """Execute via ClaudePool (claude-code-sdk). No API key needed."""
    from .claude_pool import ClaudePool

    if req.allowed_tools is None:
        raise TypeError(
            "complete(): allowed_tools is required for claude_pool. "
            "Pass [] for pure-text generation (fastest), or a whitelist like ['Read']."
        )
    pool = ClaudePool(default_model=req.model)
    t0 = time.monotonic()
    result = asyncio.run(pool.run(
        prompt=req.prompt,
        model=req.model,
        system_prompt=req.system_prompt,
        max_turns=req.max_turns,
        timeout_s=req.timeout_s,
        allowed_tools=req.allowed_tools,
        disallowed_tools=req.disallowed_tools,
        on_text=on_text,
        on_thinking=on_thinking,
    ))
    duration_ms = int((time.monotonic() - t0) * 1000)

    parsed_json: dict[str, Any] | None = None
    if req.as_json:
        parsed_json = extract_json(result.output)

    return CompleteResponse(
        text=result.output,
        json_data=parsed_json,
        success=result.success,
        duration_ms=duration_ms,
        provider=req.provider,
        model=req.model,
    )


def _handle_anthropic_api(req: CompleteRequest) -> CompleteResponse:
    raise NotImplementedError(
        "anthropic_api provider not wired yet; "
        "set ANTHROPIC_API_KEY and implement v6/llm/src/llm/providers.py::_handle_anthropic_api"
    )


def _handle_gemini(req: CompleteRequest) -> CompleteResponse:
    raise NotImplementedError(
        "gemini provider not wired yet; implement v6/llm/src/llm/providers.py::_handle_gemini"
    )


def _handle_openai(req: CompleteRequest) -> CompleteResponse:
    raise NotImplementedError(
        "openai provider not wired yet; implement v6/llm/src/llm/providers.py::_handle_openai"
    )


def _handle_deepseek(req: CompleteRequest, *,
                      on_text=None, on_thinking=None) -> CompleteResponse:
    """Execute via DeepSeek (OpenAI-compatible API). Requires DEEPSEEK_API_KEY in env."""
    from .deepseek import complete_deepseek, DEFAULT_MODEL

    # Allow caller-provided model; default to v4-flash.
    model = req.model if req.model and req.model != "haiku" else DEFAULT_MODEL

    text, success, duration_ms = complete_deepseek(
        prompt=req.prompt,
        system_prompt=req.system_prompt,
        model=model,
        timeout_s=req.timeout_s,
        as_json=req.as_json,
        on_text=on_text,
        on_thinking=on_thinking,
    )

    parsed_json: dict[str, Any] | None = None
    if req.as_json:
        parsed_json = extract_json(text)

    return CompleteResponse(
        text=text,
        json_data=parsed_json,
        success=success,
        duration_ms=duration_ms,
        provider="deepseek",
        model=model,
    )


# ── Registry ──────────────────────────────────────────────────────────────────

_REGISTRY: dict[ProviderName, Callable[[CompleteRequest], CompleteResponse]] = {
    "claude_pool": _handle_claude_pool,
    "anthropic_api": _handle_anthropic_api,
    "gemini": _handle_gemini,
    "openai": _handle_openai,
    "deepseek": _handle_deepseek,
}

DEFAULT_PROVIDER: ProviderName = "claude_pool"


def dispatch(req: CompleteRequest, *, on_text=None, on_thinking=None) -> CompleteResponse:
    """Route a CompleteRequest to the appropriate provider handler."""
    handler = _REGISTRY.get(req.provider)
    if handler is None:
        known = ", ".join(_REGISTRY.keys())
        raise ValueError(f"Unknown provider {req.provider!r}. Known: {known}")
    # Providers that support streaming callbacks.
    if req.provider in ("claude_pool", "deepseek"):
        return handler(req, on_text=on_text, on_thinking=on_thinking)
    return handler(req)


def complete(
    prompt: str,
    *,
    allowed_tools: list[str],
    system_prompt: str | None = None,
    provider: ProviderName = DEFAULT_PROVIDER,
    model: str = "haiku",
    timeout_s: int = 60,
    max_turns: int = 3,
    as_json: bool = False,
    disallowed_tools: list[str] | None = None,
    on_text=None,
    on_thinking=None,
) -> CompleteResponse:
    """High-level completion entry point.

    Args:
        prompt:        User-facing prompt text.
        system_prompt: Optional system instructions.
        provider:      One of claude_pool (default), anthropic_api, gemini, openai.
        model:         Provider-specific model name (e.g. "haiku", "sonnet").
        timeout_s:     Wall-clock timeout per query.
        max_turns:     Max agentic turns (claude_pool only).
        as_json:       If True, attempt to parse response as JSON dict.
                       On parse failure, json field is None, text is still returned.

    Returns:
        CompleteResponse with text, json (if as_json), success, duration_ms,
        provider, model.
    """
    req = CompleteRequest(
        prompt=prompt,
        system_prompt=system_prompt,
        provider=provider,
        model=model,
        timeout_s=timeout_s,
        max_turns=max_turns,
        as_json=as_json,
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
    )
    return dispatch(req, on_text=on_text, on_thinking=on_thinking)
