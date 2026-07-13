"""s54 — decompose-to-converge: an auto-agent-exhausted stall is decomposed
into child issues instead of paging a human (ADR-0105).

Seeds issue #1 at ``hitl-escalation`` with the auto-agent attempt counter
already at the cap, so on the first tick the ``decompose_or_escalate`` terminal
fires. The DecompositionCouncil is driven by scripted transcripts (via the
``_mockworld_fake_llm`` sentinel wired in sandbox_main): a direction proposing a
2-child split, then a validation that APPROVEs. Expected: an auto-decomposed
epic + its children exist, and issue #1 is NOT marked ``human-required``.
"""

from __future__ import annotations

import json

from mockworld.seed import MockWorldSeed

NAME = "s54_decompose_to_converge"
DESCRIPTION = (
    "Auto-agent-exhausted stall is decomposed into child issues (epic + "
    "children created) rather than escalating to human-required."
)

_DIRECTION = json.dumps(
    {
        "epic_title": "Epic: split issue #1",
        "epic_body": "## Sub-issues\n\n- [ ] Child A\n- [ ] Child B",
        "children": [
            {"title": "Child A: extract the parser", "body": "Split out parsing."},
            {"title": "Child B: extract the renderer", "body": "Split out rendering."},
        ],
        "rationale": "Two independently shippable layers.",
    }
)
_VALIDATION = json.dumps(
    {
        "decision": "approve",
        "confidence": "high",
        "reasoning": "Sound, non-overlapping split.",
    }
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["auto_agent_preflight"],
        issues=[
            {
                "number": 1,
                "title": "Too-broad stalled change",
                "body": "A change that stalled and exhausted the auto-agent.",
                "labels": ["hitl-escalation", "diagnose-failed"],
            }
        ],
        # Start the auto-agent already at its cap so the decompose terminal
        # fires on the first tick (default auto_agent_max_attempts = 3).
        auto_agent_attempts={1: 3},
        # The council's two seam calls (direction then validation), scripted.
        scripts={"decomposition": {1: [_DIRECTION, _VALIDATION]}},
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    # The stuck issue is superseded by an auto-decomposed epic + children.
    # After decomposition, the tracker sees more than the one seeded issue
    # (epic + 2 children created via the terminal), and issue #1 is not
    # human-required.
    payload = await api.wait_until(
        "/api/issues/history?limit=500",
        lambda p: len(p.get("items", [])) >= 3,
        timeout=60.0,
    )
    items = payload["items"]
    assert len(items) >= 3, (
        f"expected epic + >=2 children created by decomposition, saw {len(items)}"
    )
    # Issue #1 must NOT be human-required (it was decomposed, not escalated).
    issue_1 = next((it for it in items if it.get("issue_number") == 1), None)
    assert issue_1 is not None
    labels_1 = issue_1.get("labels", []) or []
    assert "human-required" not in labels_1, (
        f"issue #1 should be decomposed, not escalated to a human; labels={labels_1}"
    )
