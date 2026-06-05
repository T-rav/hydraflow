"""Shared Protocol + types for adversarial-pipeline agent adapters.

The earlier-adversarial pipeline (AssumptionSurfacer, PlanCouncil,
SpecACGenerator, SpecJudge) each take an agent satisfying the same
two-string-in, JSON-string-out contract. Extracting that Protocol once
keeps the four adversarial stages testable with a single fake.

Per Task 5/6 reflections this is the natural extraction point. No
behavior change — just a shared Protocol so call sites can type against
``AgentLike`` from one place.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol


class AgentLike(Protocol):
    """Two-string-in, string-out adversarial-stage agent contract.

    Implementations return a JSON-encoded string. Each adversarial-stage
    adapter is responsible for parsing the JSON and turning failures into
    soft outputs (empty findings list or synthetic high-severity
    concern) so a malformed agent reply never crashes the wiring.
    """

    async def run(self, system_prompt: str, user_message: str) -> str: ...


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def _first_json_object(text: str) -> str | None:
    """Return the first balanced top-level ``{...}`` object substring, or None."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json(raw: str) -> Any:
    """Parse JSON from an adversarial agent's reply, tolerating fences/prose.

    The lightweight agent path returns the model's free-form stdout, which
    commonly wraps the JSON in a ```` ```json ```` fence or prepends prose. This
    tries a direct parse, then strips a surrounding markdown fence, then falls
    back to the first balanced ``{...}`` object.

    Raises ``json.JSONDecodeError`` when no JSON can be recovered (including
    empty/whitespace-only input) so callers' existing fail-closed
    ``except json.JSONDecodeError`` paths still fire.
    """
    text = (raw or "").strip()
    if not text:
        raise json.JSONDecodeError("empty agent output", raw or "", 0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = _FENCE_RE.match(text)
    if fence:
        inner = fence.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            text = inner
    obj = _first_json_object(text)
    if obj is not None:
        return json.loads(obj)
    raise json.JSONDecodeError("no JSON object found in agent output", text, 0)
