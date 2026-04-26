"""claude_pool.py — Ported from v4/pipeline_v4_frozen_20260423/claude_pool.py.

Wraps claude-code-sdk's query() for running Claude agents from Python.
No API key needed — uses the Claude Code subscription.

Usage:
    pool = ClaudePool()
    result = await pool.run("Analyze this", model="haiku")

    # Sync convenience wrapper:
    result = run_sync("Analyze this", model="haiku")
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("claude_pool")


@dataclass
class RunResult:
    """Result from a pool.run() call."""
    exit_code: int          # 0=success, 1=failure, 124=timeout
    output: str             # Concatenated assistant text
    duration_ms: int        # Wall-clock ms
    success: bool


async def _run_query(
    prompt: str,
    *,
    allowed_tools: list[str],
    model: str = "haiku",
    cwd: str | None = None,
    disallowed_tools: list[str] | None = None,
    max_turns: int = 3,
    timeout_s: int = 60,
    system_prompt: str | None = None,
    on_text: Callable[[str], None] | None = None,
    on_thinking: Callable[[str], None] | None = None,
) -> RunResult:
    """Run a single query via claude-code-sdk.

    `allowed_tools` is REQUIRED. Pass `[]` for pure-text generation
    (fastest, no agentic exploration). Pass a list of tool names to
    permit a specific subset (e.g. ["Read"]). Without restriction
    the LLM may spend turns running Bash/Read/Grep before answering.
    """
    if allowed_tools is None:
        raise TypeError(
            "claude_pool: allowed_tools is required. Pass [] for pure-text "
            "generation, or a list of tool names like ['Read']."
        )
    from claude_code_sdk import (
        query, ClaudeCodeOptions,
        AssistantMessage, ResultMessage,
    )
    from claude_code_sdk._errors import MessageParseError

    # Patch SDK to skip unknown message types (e.g. rate_limit_event)
    import claude_code_sdk._internal.client as _sdk_client
    _original_parse = _sdk_client.parse_message

    def _tolerant_parse(data):
        try:
            return _original_parse(data)
        except MessageParseError:
            return None  # skip unknown types

    _sdk_client.parse_message = _tolerant_parse

    # The claude-code-sdk uses `if self._options.allowed_tools:` (truthy)
    # to decide whether to pass --allowedTools to the CLI. An empty list
    # is falsy, so allowed_tools=[] would silently grant all tools.
    # To force pure-text generation we pass an explicit disallowed list
    # covering every default tool of Claude Code.
    _ALL_DEFAULT_TOOLS = [
        "Bash", "BashOutput", "KillBash",
        "Read", "Write", "Edit", "NotebookEdit",
        "Glob", "Grep",
        "Task", "TodoWrite", "ExitPlanMode",
        "WebFetch", "WebSearch",
        "Skill", "ToolSearch",
        "ListMcpResources", "ReadMcpResource",
    ]
    effective_disallowed = list(disallowed_tools or [])
    if not allowed_tools:  # explicit [] from caller
        # Block all tools — pure-text mode.
        for t in _ALL_DEFAULT_TOOLS:
            if t not in effective_disallowed:
                effective_disallowed.append(t)

    # Strip user-level MCP servers so the LLM doesn't get 100+ tools listed
    # in its system prompt (each adds ~200 input tokens via cache_creation).
    # Path is created on-demand; safe to recreate.
    import os
    _empty_mcp = "/tmp/_claude_pool_empty_mcp.json"
    if not os.path.exists(_empty_mcp):
        with open(_empty_mcp, "w") as f:
            f.write('{"mcpServers":{}}')

    start = time.monotonic()
    opts = ClaudeCodeOptions(
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
        system_prompt=system_prompt,
        allowed_tools=allowed_tools if allowed_tools else None,
        # extra_args goes through verbatim to the CLI: --mcp-config and
        # --strict-mcp-config disable user-level MCP servers (saves ~10K
        # cache_creation tokens per uncached call).
        extra_args={
            "mcp-config": _empty_mcp,
            "strict-mcp-config": None,
            # Default Sonnet uses extended thinking which can stall the
            # stream for minutes on complex JSON prompts. "low" effort
            # produces minimal thinking and emits text fast.
            "effort": "low",
        },
    )
    # Default cwd to /tmp to avoid project-specific .claude/ overhead.
    opts.cwd = cwd or "/tmp"
    if effective_disallowed:
        opts.disallowed_tools = effective_disallowed

    output = ""
    success = False

    async def _consume():
        nonlocal output, success
        async for msg in query(prompt=prompt, options=opts):
            if msg is None:
                continue  # skipped unknown message type
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    # Extended thinking block (Claude reasoning)
                    if hasattr(block, "thinking") and on_thinking is not None:
                        try:
                            on_thinking(block.thinking)
                        except Exception:
                            pass
                    # Visible text output
                    if hasattr(block, "text"):
                        output += block.text
                        if on_text is not None:
                            try:
                                on_text(block.text)
                            except Exception:
                                pass
            elif isinstance(msg, ResultMessage):
                success = msg.subtype == "success"

    try:
        await asyncio.wait_for(_consume(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return RunResult(
            exit_code=124,
            output=output + "\n[TIMEOUT]",
            duration_ms=int((time.monotonic() - start) * 1000),
            success=False,
        )
    except Exception as e:
        output += f"\n[ERROR] {e}"

    return RunResult(
        exit_code=0 if success else 1,
        output=output,
        duration_ms=int((time.monotonic() - start) * 1000),
        success=success,
    )


class ClaudePool:
    """Lightweight pool for running Claude SDK queries.

    Mirrors the agentio-v2 SessionPool pattern but in Python.
    Uses the Claude Code subscription — no API key needed.
    """

    def __init__(self, default_model: str = "haiku", default_cwd: str | None = None):
        self.default_model = default_model
        self.default_cwd = default_cwd
        self._runs = 0
        self._total_ms = 0

    async def run(
        self,
        prompt: str,
        *,
        allowed_tools: list[str],
        model: str | None = None,
        cwd: str | None = None,
        disallowed_tools: list[str] | None = None,
        max_turns: int = 3,
        timeout_s: int = 60,
        system_prompt: str | None = None,
        on_text: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
    ) -> RunResult:
        """Run a prompt and return the result.

        `allowed_tools` is REQUIRED. Pass `[]` to disable tools entirely
        (pure-text generation, fastest path) or a whitelist like ["Read"].
        """
        if allowed_tools is None:
            raise TypeError(
                "ClaudePool.run: allowed_tools is required. Pass [] for "
                "pure-text generation, or a list of tool names."
            )
        result = await _run_query(
            prompt=prompt,
            model=model or self.default_model,
            cwd=cwd or self.default_cwd,
            allowed_tools=allowed_tools,
            disallowed_tools=disallowed_tools,
            max_turns=max_turns,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            on_text=on_text,
            on_thinking=on_thinking,
        )
        self._runs += 1
        self._total_ms += result.duration_ms
        return result

    async def run_vision(
        self,
        image_path: str,
        prompt: str,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        timeout_s: int = 60,
    ) -> RunResult:
        """Run a vision analysis on an image file.

        Claude reads the image natively via its Read tool.
        """
        abs_path = str(Path(image_path).resolve())
        full_prompt = (
            f"Read the image at {abs_path} and analyze it.\n\n"
            f"{prompt}"
        )
        return await self.run(
            full_prompt,
            model=model,
            allowed_tools=["Read"],
            max_turns=3,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
        )

    def stats(self) -> dict:
        return {"runs": self._runs, "total_ms": self._total_ms}


# ── Sync helpers ─────────────────────────────────────────────────────────────

def run_sync(prompt: str, **kwargs) -> RunResult:
    """Synchronous wrapper around ClaudePool.run()."""
    pool = ClaudePool()
    return asyncio.run(pool.run(prompt, **kwargs))


def run_vision_sync(image_path: str, prompt: str, **kwargs) -> RunResult:
    """Synchronous wrapper for vision analysis."""
    pool = ClaudePool()
    return asyncio.run(pool.run_vision(image_path, prompt, **kwargs))
