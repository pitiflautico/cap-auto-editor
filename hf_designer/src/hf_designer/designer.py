"""LLM designer — turns a brief into a self-contained HTML+GSAP doc.

Two prompt families live next to this file:
  • slide_prompt.md  — five layouts (stat / comparison / list / ranking / progress)
  • mockup_prompt.md — four layouts (quote / thesis / manifesto / kicker)

Adapted from `pipeline_v4_frozen_20260423/v4/hf_designer/designer.py` —
the only behavioural changes are:
  • dispatched through `llm.run_sync` (Claude Code SDK pool) instead of
    the v4 CLI subprocess wrapper.
  • the LLM is run with `allowed_tools=[]` (pure text generation, no
    agentic exploration) and ``model="sonnet"`` by default.
  • prompt text files ship inside the wheel via hatch force-include.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

log = logging.getLogger("hf_designer.designer")


_HERE = Path(__file__).resolve().parent
SLIDE_PROMPT = (_HERE / "slide_prompt.md").read_text(encoding="utf-8")
MOCKUP_PROMPT = (_HERE / "mockup_prompt.md").read_text(encoding="utf-8")


SlideKind = Literal["slide", "mockup"]
Layout = Literal["fullscreen", "split_top", "split_bottom"]


def _build_user_prompt(*, brief: str, layout: str, duration_s: float,
                        palette: dict | None = None) -> str:
    parts = [
        f"BRIEF: {brief}",
        f"LAYOUT: {layout}",
        f"DURATION: {duration_s:.1f}s",
    ]
    if palette:
        palette_lines = [f"  {k}: {v}" for k, v in palette.items()]
        parts.append("PALETTE (override editorial default):\n" +
                     "\n".join(palette_lines))
    parts.append("\nEmit the HTML document now.")
    return "\n\n".join(parts)


_HTML_FENCED_RE = re.compile(
    r"```(?:html)?\s*(<!doctype html.*?</html>)\s*```",
    re.DOTALL | re.IGNORECASE,
)
_HTML_BARE_RE = re.compile(
    r"(<!doctype html.*?</html>)",
    re.DOTALL | re.IGNORECASE,
)


def _extract_html(raw: str) -> str | None:
    """Pull out the first ``<!doctype html>...</html>`` block.

    Tries a fenced ```html ... ``` block first (what the prompt asks
    for), then falls back to a bare match for resilience to misbehaved
    LLM outputs.
    """
    m = _HTML_FENCED_RE.search(raw)
    if m:
        return m.group(1)
    m = _HTML_BARE_RE.search(raw)
    if m:
        return m.group(1)
    return None


def design(
    *,
    brief: str,
    kind: SlideKind,
    layout: Layout = "fullscreen",
    duration_s: float = 6.0,
    palette: dict | None = None,
    model: str = "sonnet",
    timeout_s: int = 240,
) -> str:
    """Generate one HTML+GSAP card. Returns the raw HTML string.

    Raises:
        ValueError    if `kind` is not "slide" or "mockup".
        RuntimeError  if the LLM did not emit an extractable HTML block
                      (truncated / refused / wrapped in prose).
    """
    if kind not in ("slide", "mockup"):
        raise ValueError(f"kind must be 'slide' or 'mockup', got {kind!r}")
    system = SLIDE_PROMPT if kind == "slide" else MOCKUP_PROMPT
    user_prompt = _build_user_prompt(
        brief=brief, layout=layout, duration_s=duration_s, palette=palette,
    )

    # Imported lazily so importing the package doesn't pull the SDK
    # transitively in unit tests that monkeypatch `_run_llm`.
    from llm.claude_pool import run_sync

    res = run_sync(
        user_prompt,
        allowed_tools=[],
        model=model,
        timeout_s=timeout_s,
        max_turns=1,
        system_prompt=system,
    )
    if not res.success:
        raise RuntimeError(
            f"hf_designer LLM call failed (exit_code={res.exit_code}, "
            f"duration_ms={res.duration_ms}): {res.output[:300]!r}"
        )
    html = _extract_html(res.output)
    if html is None:
        raise RuntimeError(
            f"hf_designer did not emit HTML. Raw head: {res.output[:300]!r}"
        )
    return html
