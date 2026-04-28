"""Tests for hf_designer (no real LLM / hyperframes calls)."""
from __future__ import annotations

import pytest

from hf_designer.designer import (
    SLIDE_PROMPT,
    MOCKUP_PROMPT,
    _build_user_prompt,
    _extract_html,
    design,
)


# ── Prompt loading ─────────────────────────────────────────────────


def test_slide_prompt_has_all_layouts():
    """Smoke check: the system prompt actually mentions the 5 slide layouts."""
    for layout in ("STAT", "COMPARISON", "LIST", "RANKING", "PROGRESS"):
        assert layout in SLIDE_PROMPT, f"{layout!r} missing from slide_prompt.md"


def test_mockup_prompt_has_all_layouts():
    for layout in ("QUOTE", "THESIS", "MANIFESTO", "KICKER"):
        assert layout in MOCKUP_PROMPT, f"{layout!r} missing from mockup_prompt.md"


# ── User-prompt assembly ───────────────────────────────────────────


def test_user_prompt_contains_brief_layout_duration():
    p = _build_user_prompt(brief="2.5M downloads",
                           layout="split_top", duration_s=4.5)
    assert "BRIEF: 2.5M downloads" in p
    assert "LAYOUT: split_top" in p
    assert "DURATION: 4.5s" in p
    assert "Emit the HTML document now." in p
    assert "PALETTE" not in p          # no palette → not mentioned


def test_user_prompt_includes_palette_when_given():
    p = _build_user_prompt(
        brief="x", layout="fullscreen", duration_s=6.0,
        palette={"bg": "#fff", "fg": "#000", "accent": "#4285F4"},
    )
    assert "PALETTE" in p
    assert "#4285F4" in p


# ── HTML extraction ────────────────────────────────────────────────


def test_extract_html_from_fenced_block():
    raw = "Sure, here you go:\n\n```html\n<!doctype html><html><body>x</body></html>\n```\n"
    out = _extract_html(raw)
    assert out is not None
    assert out.startswith("<!doctype html>")
    assert out.endswith("</html>")


def test_extract_html_falls_back_to_bare_block():
    """Even without a fence, accept a bare <!doctype html>...</html>."""
    raw = "I cannot use code fences but: <!doctype html><html></html> done"
    out = _extract_html(raw)
    assert out is not None
    assert out.startswith("<!doctype html>")


def test_extract_html_returns_none_when_absent():
    assert _extract_html("just text, no html here") is None
    assert _extract_html("") is None


# ── design() with a stubbed LLM ────────────────────────────────────


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace `llm.claude_pool.run_sync` with a controllable fake.

    Yields a `set_response(text, success=True, exit_code=0)` setter so
    each test composes the LLM behaviour it wants.
    """
    state = {"text": "", "success": True, "exit_code": 0,
             "calls": []}

    class _FakeResult:
        def __init__(self, output, success, exit_code):
            self.output = output
            self.success = success
            self.exit_code = exit_code
            self.duration_ms = 10

    def _fake_run_sync(prompt, **kwargs):
        state["calls"].append({"prompt": prompt, "kwargs": kwargs})
        return _FakeResult(state["text"], state["success"], state["exit_code"])

    import llm.claude_pool
    monkeypatch.setattr(llm.claude_pool, "run_sync", _fake_run_sync)

    def setter(text, *, success=True, exit_code=0):
        state["text"] = text
        state["success"] = success
        state["exit_code"] = exit_code

    setter.calls = state["calls"]
    yield setter


def test_design_slide_returns_html(fake_llm):
    fake_llm("```html\n<!doctype html><html><body>SLIDE</body></html>\n```")
    out = design(brief="Big metric", kind="slide", duration_s=5.0)
    assert "SLIDE" in out
    # Verify the system prompt was the slide one (not mockup)
    call = fake_llm.calls[-1]
    sp = call["kwargs"].get("system_prompt") or ""
    assert "SENIOR MOTION DESIGNER" in sp
    assert "STAT" in sp                # slide-prompt-specific marker


def test_design_mockup_uses_mockup_prompt(fake_llm):
    fake_llm("<!doctype html><html><body>QUOTE</body></html>")
    design(brief="A short manifesto", kind="mockup", duration_s=4.0)
    sp = fake_llm.calls[-1]["kwargs"].get("system_prompt") or ""
    assert "QUOTE" in sp and "THESIS" in sp


def test_design_invalid_kind_raises():
    with pytest.raises(ValueError):
        design(brief="x", kind="bogus")          # type: ignore[arg-type]


def test_design_raises_when_llm_emits_no_html(fake_llm):
    fake_llm("Sorry, I can't help with this request.")
    with pytest.raises(RuntimeError, match="did not emit HTML"):
        design(brief="x", kind="slide")


def test_design_raises_when_llm_call_fails(fake_llm):
    fake_llm("rate limit", success=False, exit_code=124)
    with pytest.raises(RuntimeError, match="LLM call failed"):
        design(brief="x", kind="slide")


def test_design_passes_palette_through(fake_llm):
    fake_llm("<!doctype html><html></html>")
    design(brief="x", kind="slide",
           palette={"accent": "#4285F4", "bg": "#fff"})
    user = fake_llm.calls[-1]["prompt"]
    assert "#4285F4" in user
