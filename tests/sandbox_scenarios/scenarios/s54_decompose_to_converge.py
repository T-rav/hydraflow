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
        # #11298: lane-on makes this flow SERIALIZED, not merely slower.
        # AutoAgentPreflightLoop is single-issue-per-tick (see its module
        # docstring + ``_do_work``: ``_select_dispatchable_issue`` returns ONE
        # issue and ``_process_one`` handles just that one). Under lane-on,
        # PlanPhase._route_light_lane claims each decomposed child with
        # ``hydraflow-auto-light`` and stops the plan flow, so BOTH children
        # come back to this same loop for their spawn — one child per tick.
        # The flow therefore needs THREE preflight ticks, not one:
        #   tick 1  decompose #1 -> epic #2 + children #3, #4
        #   tick 2  light-lane spawn for child #3
        #   tick 3  light-lane spawn for child #4
        # Pre-lane-on, the children fanned out across the concurrent phase
        # orchestrators after a single decompose tick, so one tick was enough.
        # At the default 60s cadence those three ticks put the SECOND child at
        # t>=180s — exactly the predicate budget, i.e. a guaranteed race. It
        # duly lost on CI (run 32536667685): child #3 landed in history at
        # tick 2 + 2s, child #4's spawn finished ~1s AFTER the 180s predicate
        # gave up ("1 failed in 181.18s").
        # Fix the SERIALIZATION, not the clock: tick every 6s (the cadence s55
        # already proves in CI for the identical hop-1 decompose) so the three
        # serialized ticks cost ~20s instead of ~180s. The assertion budget
        # below is unchanged and now carries ~8x margin rather than none.
        sandbox_loop_interval=6,
        # In-process parity tier (test_sandbox_parity) only — the docker
        # sandbox ticks continuously and ignores this. Raised 2 -> 6 to match
        # the three serialized ticks above (at 2 the in-process tier could
        # never reach the second child's dispatch either).
        cycles_to_run=6,
    )


async def assert_outcome(api, page) -> None:
    # Proof of decompose-to-converge: the stuck issue #1 was split into child
    # issues that entered the pipeline, each carrying the auto-decomposed epic's
    # title in its ``epic`` field. Their appearance in /api/issues/history is the
    # observable end-to-end signal (the epic + the superseded #1 are not pipeline
    # work-items). >=2 children under the scripted epic title == the terminal
    # decomposed rather than paging a human.
    # timeout=180.0 (not the original 90.0), matching the tier other
    # multi-cycle, council-driven scenarios use (s02/s03/s04/s08). The budget
    # is NOT what makes this deterministic — the seed's 6s
    # sandbox_loop_interval is. Under #11298 lane-on this flow needs three
    # SERIALIZED AutoAgentPreflightLoop ticks (decompose, then one light-lane
    # spawn per child, because the loop is single-issue-per-tick); see the
    # seed for the full derivation. At 6s those cost ~20s, so 180s is headroom
    # rather than the thing being raced against.
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
