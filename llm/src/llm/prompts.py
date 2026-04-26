"""Shared prompt helpers for v6/llm/.

Utilities used across providers for JSON extraction and prompt assembly.
"""
from __future__ import annotations

import json
import re


def extract_json(text: str) -> dict | None:
    """Extract first JSON object from LLM text output.

    Handles:
    - Raw JSON
    - Markdown code blocks (```json ... ```)
    - JSON embedded in surrounding prose
    """
    cleaned = text.strip()

    # Strip markdown code fence if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```\w*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()

    # Try direct parse first (clean JSON)
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Find the outermost JSON object via brace matching
    start = cleaned.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(cleaned[start:], start=start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return None

    return None


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, adding ellipsis if cut."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"
