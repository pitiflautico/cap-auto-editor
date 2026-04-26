"""DeepSeek provider — OpenAI-compatible API.

Uses the DeepSeek public API (https://api.deepseek.com/v1) with the
official `openai` SDK pointed at their endpoint.

Requires `DEEPSEEK_API_KEY` in env (or in `.env` at the project root).
Models (April 2026):
  - deepseek-v4-flash  (efficient, 284B MoE, 1M context, default)
  - deepseek-v4-pro    (frontier, 1.6T MoE, 1M context)
  - deepseek-chat / deepseek-reasoner  (deprecated 2026/07/24)
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("llm.deepseek")

DEFAULT_MODEL = "deepseek-v4-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


def _load_env_file() -> None:
    """Best-effort load DEEPSEEK_API_KEY from project .env if not already set."""
    if os.environ.get("DEEPSEEK_API_KEY"):
        return
    # Walk up from this file looking for a .env up to the project root.
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == "DEEPSEEK_API_KEY" and v:
                        os.environ["DEEPSEEK_API_KEY"] = v
                        return
            except Exception:
                pass


def _get_client():
    """Lazy-import openai and return a configured client."""
    _load_env_file()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY not set. Add it to .env at the project root, "
            "or export it in the shell."
        )
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError(
            "openai SDK is required for the deepseek provider. "
            "Install it: pip install openai"
        ) from e
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)


def complete_deepseek(
    prompt: str,
    *,
    system_prompt: str | None = None,
    model: str = DEFAULT_MODEL,
    timeout_s: int = 300,
    as_json: bool = False,
    on_text=None,
    on_thinking=None,
    thinking: bool = False,
    reasoning_effort: str | None = None,
    stream: bool = False,
) -> tuple[str, bool, int]:
    """Run a DeepSeek completion. Returns (text, success, duration_ms).

    Defaults follow https://api-docs.deepseek.com:
      - thinking=False  → standard mode (omit the `thinking` param).
      - thinking=True   → extended thinking ({"type":"enabled"}).
      - reasoning_effort: "low"|"medium"|"high"|"max" when thinking=True.
      - stream=False    → single response (more reliable; SSE often hits
        intermediate timeouts on long JSON outputs). Set stream=True if
        you want token-by-token via on_text.
    """
    client = _get_client()

    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    extra: dict[str, Any] = {
        # deepseek-v4-flash supports up to 64K output tokens. Allow plenty
        # of room for long structured JSON (40+ beats × broll_hints).
        "max_tokens": 32000,
    }
    if as_json:
        extra["response_format"] = {"type": "json_object"}
    if thinking:
        extra["thinking"] = {"type": "enabled"}
        if reasoning_effort:
            extra["reasoning_effort"] = reasoning_effort

    t0 = time.monotonic()
    text_parts: list[str] = []
    success = False
    try:
        if stream:
            stream_resp = client.chat.completions.create(
                model=model, messages=messages, stream=True,
                timeout=timeout_s, **extra,
            )
            for chunk in stream_resp:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                rc = getattr(delta, "reasoning_content", None)
                if rc and on_thinking is not None:
                    try: on_thinking(rc)
                    except Exception: pass
                chunk_text = getattr(delta, "content", None)
                if chunk_text:
                    text_parts.append(chunk_text)
                    if on_text is not None:
                        try: on_text(chunk_text)
                        except Exception: pass
        else:
            resp = client.chat.completions.create(
                model=model, messages=messages, stream=False,
                timeout=timeout_s, **extra,
            )
            choice = resp.choices[0]
            rc = getattr(choice.message, "reasoning_content", None)
            if rc and on_thinking is not None:
                try: on_thinking(rc)
                except Exception: pass
            content = choice.message.content or ""
            text_parts.append(content)
            if on_text is not None and content:
                try: on_text(content)
                except Exception: pass
        success = True
    except Exception as exc:
        log.warning("DeepSeek call failed: %s", exc)
        text_parts.append(f"\n[ERROR] {type(exc).__name__}: {exc}")
        success = False

    duration_ms = int((time.monotonic() - t0) * 1000)
    return "".join(text_parts), success, duration_ms
