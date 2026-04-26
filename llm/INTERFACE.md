# llm/ — Shared LLM Provider Package

> **STATUS: FROZEN v1.0 — 2026-04-24**
>
> Interface contract for v6/llm/. Any implementation of this package must
> respect the inputs, outputs, and guarantees described here.
> Interface changes require updating this document first and bumping the version.

---

## Purpose

Provide a unified, provider-agnostic LLM completion interface for all myavatar v6
phases. Consumers call `complete(prompt, ...)` without caring which provider is
configured. Provider selection is explicit per call, not hidden.

---

## API Surface

### `complete()` — High-level entry point

```python
from llm import complete

result = complete(
    prompt="...",
    system_prompt="...",         # optional
    provider="claude_pool",      # default
    model="haiku",               # provider-specific
    timeout_s=60,
    max_turns=3,
    as_json=True,                # attempt JSON parse; result.json is dict or None
)
# → CompleteResponse(text, json, success, duration_ms, provider, model)
```

**`as_json=True` contract**: the helper calls `extract_json()` on the raw text.
If parsing fails, `json` is `None` and `text` is still the raw string. Never raises.

### `ClaudePool` — Low-level escape hatch

```python
from llm import ClaudePool

pool = ClaudePool(default_model="haiku")
result = await pool.run("prompt", system_prompt="...", timeout_s=30)
# → RunResult(exit_code, output, duration_ms, success)
```

### `extract_json(text: str) -> dict | None`

Extracts first JSON object from LLM output. Handles:
- Raw JSON
- Markdown code fences (` ```json ... ``` `)
- JSON embedded in prose

Returns `None` on parse failure.

---

## Providers

| Name | Status | Auth | Notes |
|---|---|---|---|
| `claude_pool` | **IMPLEMENTED** | None — uses Claude Code subscription | **Recommended default.** Wraps `claude-code-sdk`. No API key, no metered cost. |
| `anthropic_api` | STUB | `ANTHROPIC_API_KEY` env var | Raises `NotImplementedError`. Implement `_handle_anthropic_api` in `providers.py`. |
| `gemini` | STUB | — | Raises `NotImplementedError`. |
| `openai` | STUB | — | Raises `NotImplementedError`. |

**Why `claude_pool` is the default**: it uses the existing Claude Code subscription,
not the metered API. Cost is zero at the margin. For production pipelines that need
parallelism at scale, switch to `anthropic_api` with a key.

---

## How to add a provider (2 steps)

1. Write a handler `_handle_myprovider(req: CompleteRequest) -> CompleteResponse` in `providers.py`.
2. Add it to `_REGISTRY`: `"myprovider": _handle_myprovider`.

That's it. No changes to `__init__.py` or any consumer.

---

## Contracts (Pydantic models)

### `CompleteRequest`

| Field | Type | Default | Description |
|---|---|---|---|
| `prompt` | `str` | required | User prompt |
| `system_prompt` | `str \| None` | `None` | System instructions |
| `provider` | `ProviderName` | `"claude_pool"` | Provider to use |
| `model` | `str` | `"haiku"` | Provider-specific model name |
| `timeout_s` | `int` | `60` | Wall-clock timeout |
| `max_turns` | `int` | `3` | Max agentic turns (claude_pool only) |
| `as_json` | `bool` | `False` | Parse response as JSON |

### `CompleteResponse`

| Field | Type | Description |
|---|---|---|
| `text` | `str` | Raw LLM output |
| `json` | `dict \| None` | Parsed JSON if `as_json=True` and parse succeeded |
| `success` | `bool` | Provider-level success flag |
| `duration_ms` | `int` | Wall-clock duration |
| `provider` | `ProviderName` | Provider used |
| `model` | `str` | Model used |

### `RunResult` (ClaudePool internal)

| Field | Type | Description |
|---|---|---|
| `exit_code` | `int` | 0=success, 1=failure, 124=timeout |
| `output` | `str` | Concatenated assistant text |
| `duration_ms` | `int` | Wall-clock ms |
| `success` | `bool` | True if SDK reported success |

---

## Dependencies

- `claude-code-sdk` — used by `claude_pool` provider
- `pydantic>=2.0` — contracts

No other runtime dependencies. Stubs have no dependencies.
