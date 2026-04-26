"""Tests for provider registry and dispatch logic."""
from __future__ import annotations

import pytest

from llm.contracts import CompleteRequest, CompleteResponse
from llm.providers import complete, dispatch, DEFAULT_PROVIDER, _REGISTRY


# ── Registry tests ────────────────────────────────────────────────────────────

def test_default_provider_is_claude_pool():
    assert DEFAULT_PROVIDER == "claude_pool"


def test_registry_has_all_providers():
    assert set(_REGISTRY.keys()) == {"claude_pool", "anthropic_api", "gemini", "openai"}


def test_dispatch_bad_name_raises():
    req = CompleteRequest(prompt="hello", provider="claude_pool")
    req.provider = "nonexistent"  # bypass literal validation
    with pytest.raises(ValueError, match="Unknown provider"):
        dispatch(req)


def test_stub_providers_raise_not_implemented():
    """anthropic_api, gemini, openai are stubs that raise NotImplementedError."""
    for provider_name in ("anthropic_api", "gemini", "openai"):
        req = CompleteRequest(prompt="test", provider="claude_pool")
        # call handler directly
        handler = _REGISTRY[provider_name]
        with pytest.raises(NotImplementedError):
            handler(req)


def test_complete_request_defaults():
    req = CompleteRequest(prompt="hello")
    assert req.provider == "claude_pool"
    assert req.model == "haiku"
    assert req.timeout_s == 60
    assert req.max_turns == 3
    assert req.as_json is False


def test_complete_response_fields():
    resp = CompleteResponse(
        text="hello",
        json_data={"key": "val"},
        success=True,
        duration_ms=123,
        provider="claude_pool",
        model="haiku",
    )
    assert resp.success is True
    assert resp.json_data == {"key": "val"}
    assert resp.duration_ms == 123
