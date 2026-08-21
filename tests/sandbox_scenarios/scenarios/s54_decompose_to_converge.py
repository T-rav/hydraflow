"""s54 — decompose-to-converge: an auto-agent-exhausted stall is decomposed
into child issues instead of paging a human (ADR-0105).

Seeds issue #1 at ``hitl-escalation`` with the auto-agent attempt counter
already at the cap, so on the first tick the ``decompose_or_escalate`` terminal
fires. The DecompositionCouncil is driven by scripted transcripts (via the
``_mockworld_fake_llm`` sentinel wired in sandbox_main): a direction proposing a
2-child split, then a validation that APPROVEs. Expected: an auto-decomposed
epic + its children exist, and issue #1 is NOT marked ``human-required``.

#11298 (light lane ON by default): the decomposed children (#3, #4 — FakeGitHub
numbers deterministically, the epic is #2) are triaged by the default fake
(complexity 0 ≤ ``auto_agent_light_max_complexity``) and so route to the
single-session auto-agent instead of the staged plan pipeline. Their spawns are
scripted (``scripts["auto_agent"]``) to resolve — the sandbox's fake spawn seam
mints each child's PR through the PRPort and releases it to review — because
an UNSCRIPTED spawn is a deterministic crash under the air-gap (and, before the
seam existed, a real in-container ``claude`` that wedged this scenario on CLI
auth retries).
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
# Light-lane spawn outcome for each decomposed child (#11298): the seam mints
# the PR on ``agent/auto-agent-<n>`` and the decision routes the child to
# review. Keyed by the children's deterministic numbers (epic #2 → #3, #4).
_LIGHT_RESOLVED = {"status": "resolved", "diagnosis": "Child shipped in one session."}


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
        # The council's two seam calls (direction then validation), scripted;
        # plus the children's light-lane spawns (see module docstring).
        scripts={
            "decomposition": {1: [_DIRECTION, _VALIDATION]},
            "auto_agent": {3: [_LIGHT_RESOLVED], 4: [_LIGHT_RESOLVED]},
        },
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    # Proof of decompose-to-converge: the stuck issue #1 was split into child
    # issues that entered the pipeline, each carrying the auto-decomposed epic's
    # title in its ``epic`` field. Their appearance in /api/issues/history is the
    # observable end-to-end signal (the epic + the superseded #1 are not pipeline
    # work-items). >=2 children under the scripted epic title == the terminal
    # decomposed rather than paging a human.
    # timeout=180.0 (not the original 90.0): the flow needs a full 60s
    # sandbox_loop_interval tick just to reach cycle 2, plus council LLM
    # round-trips on top — observed CI durations of 86-90s left almost no
    # margin and the scenario flaked past 90s under ordinary runner
    # variance. 180s matches the tier used by other multi-cycle,
    # council-driven scenarios (s02/s03/s04/s08).
    epic_title = "Epic: split issue #1"
    payload = await api.wait_until(
        "/api/issues/history?limit=500",
        lambda p: (
            sum(1 for it in p.get("items", []) if it.get("epic") == epic_title) >= 2
        ),
        timeout=180.0,
    )
    children = [it for it in payload["items"] if it.get("epic") == epic_title]
    assert len(children) >= 2, (
        f"expected >=2 auto-decomposed children under {epic_title!r}, "
        f"saw {[(it.get('issue_number'), it.get('epic')) for it in payload['items']]}"
    )
    # None of the children should be human-required — the change converged via
    # decomposition, not a human hand-off.
    for child in children:
        labels = child.get("labels", []) or []
        assert "human-required" not in labels, (
            f"child #{child.get('issue_number')} unexpectedly human-required: {labels}"
        )
