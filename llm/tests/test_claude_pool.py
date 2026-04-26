"""Tests for ClaudePool — all mocked, no live Claude calls."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm.claude_pool import ClaudePool, RunResult, run_sync
from llm.prompts import extract_json


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _make_assistant_msg(text: str):
    """Build a mock AssistantMessage with one text block."""
    block = MagicMock()
    block.text = text
    msg = MagicMock()
    msg.__class__.__name__ = "AssistantMessage"
    msg.content = [block]
    return msg


def _make_result_msg(success: bool = True):
    """Build a mock ResultMessage."""
    msg = MagicMock()
    msg.__class__.__name__ = "ResultMessage"
    msg.subtype = "success" if success else "error"
    return msg


async def _async_gen(*items):
    """Yield items from an async generator."""
    for item in items:
        yield item


# ── RunResult shape ───────────────────────────────────────────────────────────

def test_run_result_shape():
    r = RunResult(exit_code=0, output="hello", duration_ms=100, success=True)
    assert r.exit_code == 0
    assert r.output == "hello"
    assert r.success is True


def test_run_result_timeout_exit_code():
    r = RunResult(exit_code=124, output="[TIMEOUT]", duration_ms=60000, success=False)
    assert r.exit_code == 124
    assert r.success is False


# ── ClaudePool.run() mocked ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pool_run_success(monkeypatch):
    """Pool.run() accumulates assistant text and marks success=True."""
    import llm.claude_pool as cp_mod

    async def fake_run_query(prompt, **kwargs):
        return RunResult(exit_code=0, output="The answer is 42.", duration_ms=50, success=True)

    monkeypatch.setattr(cp_mod, "_run_query", fake_run_query)

    pool = ClaudePool(default_model="haiku")
    result = await pool.run("What is 6 * 7?", allowed_tools=[])
    assert result.success is True
    assert "42" in result.output
    assert result.duration_ms == 50
    assert pool._runs == 1


@pytest.mark.asyncio
async def test_pool_stats_accumulate():
    """pool.stats() tracks runs and total_ms."""
    import llm.claude_pool as cp_mod

    async def fake_run_query(prompt, **kwargs):
        return RunResult(exit_code=0, output="ok", duration_ms=200, success=True)

    orig = cp_mod._run_query
    cp_mod._run_query = fake_run_query
    try:
        pool = ClaudePool()
        await pool.run("first", allowed_tools=[])
        await pool.run("second", allowed_tools=[])
        stats = pool.stats()
        assert stats["runs"] == 2
        assert stats["total_ms"] == 400
    finally:
        cp_mod._run_query = orig


# ── extract_json ──────────────────────────────────────────────────────────────

def test_extract_json_plain():
    text = '{"key": "value", "num": 42}'
    result = extract_json(text)
    assert result == {"key": "value", "num": 42}


def test_extract_json_code_fence():
    text = '```json\n{"a": 1}\n```'
    result = extract_json(text)
    assert result == {"a": 1}


def test_extract_json_embedded_in_prose():
    text = 'Here is the result: {"status": "ok", "count": 3} — done.'
    result = extract_json(text)
    assert result == {"status": "ok", "count": 3}


def test_extract_json_none_on_garbage():
    result = extract_json("This has no JSON at all.")
    assert result is None


def test_extract_json_nested():
    text = '{"outer": {"inner": [1, 2, 3]}}'
    result = extract_json(text)
    assert result["outer"]["inner"] == [1, 2, 3]


# ── run_sync convenience ──────────────────────────────────────────────────────

def test_run_sync_calls_pool(monkeypatch):
    """run_sync() wraps asyncio.run correctly."""
    import llm.claude_pool as cp_mod

    async def fake_run_query(prompt, **kwargs):
        return RunResult(exit_code=0, output="sync ok", duration_ms=10, success=True)

    monkeypatch.setattr(cp_mod, "_run_query", fake_run_query)
    result = run_sync("hello", allowed_tools=[])
    assert result.output == "sync ok"
    assert result.success is True
