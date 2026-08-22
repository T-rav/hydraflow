"""s55 — nested decompose-to-converge (depth 2): a decomposed child that itself
stalls is re-decomposed, and the root epic converges through the epic-to-epic
lineage (ADR-0105 / #9757).

Flow (deterministic FakeGitHub numbering — create_issue = max(issues)+1):
- seed #1 (hitl-escalation, auto-agent exhausted) → decomposes into root epic
  E1 (#2) with children #3, #4 (hop 1, like s54).
- #11298 (light lane ON by default): every child is triaged by the default
  fake (complexity 0 ≤ ``auto_agent_light_max_complexity``), so PlanPhase
  routes it to the single-session auto-agent (claim label
  ``hydraflow-auto-light``) instead of the staged plan/implement pipeline.
- child #3's auto-agent counter is pre-seeded to the cap, so on its first
  light-lane tick the decompose-or-escalate terminal fires BEFORE any spawn:
  it decomposes into E2 (#5) with grandchildren #6, #7 (hop 2). Because #3 is
  a child of E1, E2 is stamped parent_epic=2, superseded_issue=3. (Pre-#11298
  the same hop was reached the long way round — #3 failed review three times,
  the diagnostic loop escalated it to hitl-escalation, and the exhausted
  counter decomposed it from there.)
- child #4 and grandchildren #6/#7 take one scripted light-lane spawn each
  (``scripts["auto_agent"]``): the sandbox's fake spawn seam mints the PR
  through the PRPort, the claim releases to review, the scripted review
  approves → merge/close. An UNSCRIPTED spawn is a deterministic crash under
  the air-gap (and, before the seam existed, a real in-container ``claude``
  that wedged this scenario on CLI auth retries — the children never
  completed and /api/epics never reached ``completed``).
- E2 closes once #6/#7 finish; its close propagates up the lineage so the root
  epic E1 (#2) converges only after the transitive grandchild work is done.

Asserts the achievable e2e signal — the nested decomposition occurs and the
root epic converges in the real docker stack. The premature-close *timing*
invariant (root held open while grandchildren live) is asserted precisely at
the MockWorld layer, where close ordering is controllable
(tests/scenarios/test_decompose_to_converge_scenario.py).
"""

from __future__ import annotations

import json

from mockworld.seed import MockWorldSeed

NAME = "s55_nested_decompose"

# Was quarantined under #9925 (born-racy, ~80% red 2026-07-18). Root cause was
# NOT a decompose/review race (the issue's original diagnosis) but the #9796
# DiscoverRunner/ShapeRunner air-gapped-sandbox wedge: with no discover/shape
# script seeded, those runners spawned a real `claude` and ran to agent_timeout,
# freezing the discover/shape phase loop so a child never reached
# review→escalate→decompose and the epic stalled at 50%. #9919 fixed that wedge
# (landed 28 min AFTER the quarantine, so nobody noticed it also fixed s55).
# Un-quarantined here after 31/31 consecutive green docker runs (19 local across
# plain/host-stress/CPU-cap + 12 on GitHub CI runners). See #9925.
DESCRIPTION = (
    "Depth-2 nested decompose: a stalled decomposed child re-decomposes and the "
    "root epic converges via epic-to-epic lineage."
)
# Docker-only (Tier 2). This drives ~5 loops over a full multi-hop pipeline for
# a runtime-created child (30 cycles) — impractical in the fast in-process
# parity harness (test_sandbox_parity), which is meant for light scenarios. The
# nested convergence LOGIC is covered in-process by the MockWorld tests in
# tests/scenarios/test_decompose_to_converge_scenario.py (real loop wiring, with
# the precise premature-close ordering assertion); this scenario adds the
# docker/container wiring confidence.
IN_PROCESS = False


def _direction(epic_title: str, a: str, b: str) -> str:
    return json.dumps(
        {
            "epic_title": epic_title,
            "epic_body": f"## Sub-issues\n\n- [ ] {a}\n- [ ] {b}",
            "children": [
                {"title": a, "body": f"{a} body."},
                {"title": b, "body": f"{b} body."},
            ],
            "rationale": "Two independently shippable layers.",
        }
    )


_APPROVE = json.dumps(
    {"decision": "approve", "confidence": "high", "reasoning": "Sound split."}
)
# Light-lane spawn outcome for each leaf child (#11298): resolved with no
# explicit pr_url → the seam mints the PR on ``agent/auto-agent-<n>``.
_LIGHT_RESOLVED = {"status": "resolved", "diagnosis": "Leaf shipped in one session."}

# Hop 1: root #1 → E1 (#2) [#3, #4]. Hop 2: child #3 → E2 (#5) [#6, #7].
_DIR1 = _direction("Epic: split issue #1", "Child A", "Child B")
_DIR2 = _direction("Epic: split the stalled child", "Grandchild A", "Grandchild B")


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=[
            "diagnostic",
            "auto_agent_preflight",
            "epic_sweeper",
            "github_cache",
        ],
        issues=[
            {
                "number": 1,
                "title": "Too-broad stalled change",
                "body": "A change that stalled and exhausted the auto-agent.",
                "labels": ["hitl-escalation", "diagnose-failed"],
            }
        ],
        # #1 exhausted → hop-1 decompose immediately. #3 pre-loaded to the cap so
        # that once the pipeline drives it to hitl-escalation it decomposes on the
        # first auto-agent tick (hop 2). Counters are keyed by number, so the
        # predictable child #3 can be pre-seeded before it exists.
        auto_agent_attempts={1: 3, 3: 3},
        scripts={
            "decomposition": {1: [_DIR1, _APPROVE], 3: [_DIR2, _APPROVE]},
            # Children start at hydraflow-find; triage them to ready. The
            # default complexity (0) routes every child to the light lane.
            "triage": {
                3: [{"ready": True}],
                4: [{"ready": True}],
                6: [{"ready": True}],
                7: [{"ready": True}],
            },
            # Light-lane spawns (#11298). #3 has NO spawn script: it is at the
            # attempt cap, so its first tick decomposes (hop 2) before any
            # spawn would happen. #4, #6, #7 resolve in one session each.
            "auto_agent": {
                4: [_LIGHT_RESOLVED],
                6: [_LIGHT_RESOLVED],
                7: [_LIGHT_RESOLVED],
            },
            # The light-lane PRs still go through the review stage: #4, #6,
            # #7 pass → merge/close.
            "review": {
                4: [{"verdict": "approve", "comments": []}],
                6: [{"verdict": "approve", "comments": []}],
                7: [{"verdict": "approve", "comments": []}],
            },
        },
        cycles_to_run=30,
        # This flow is long (two full pipeline runs + two decompose hops); at the
        # default 60s caretaker cadence it can't finish within CI's slower
        # runners. Tick every 6s so the many stages advance fast enough. Only
        # affects this scenario (other seeds keep the 60s default).
        sandbox_loop_interval=6,
    )


async def assert_outcome(api, page) -> None:
    # Tier-2 (docker wiring) signal: the depth-2 nested decomposition executes
    # end-to-end and every leaf converges. Two epics exist — the root E1 (#2)
    # and the second-hop E2 (#5, carved from the stalled child #3) — and BOTH
    # reach `completed` (all their children resolved), with E2's grandchildren
    # merged. That proves the full nested-decompose flow runs in the real stack:
    # hop-1 decompose, a child re-decomposing (hop-2), and the whole tree's leaf
    # work reaching done.
    #
    # NOTE: the premature-close *timing* invariant — a root held open while its
    # grandchildren are still live — is asserted precisely at the MockWorld
    # layer (tests/scenarios/test_decompose_to_converge_scenario.py), where
    # close ordering is controllable. The async sandbox cannot deterministically
    # order closures, so it verifies convergence, not ordering.
    def _both_epics_completed(payload: object) -> bool:
        epics = payload if isinstance(payload, list) else []
        completed = [e for e in epics if e.get("status") == "completed"]
        return len(completed) >= 2

    epics = await api.wait_until("/api/epics", _both_epics_completed, timeout=240.0)
    completed = [e for e in epics if e.get("status") == "completed"]
    assert len(completed) >= 2, (
        "expected the root epic AND the second-hop epic to both reach "
        f"'completed' (depth-2 nested decompose converged), saw "
        f"{[(e.get('epic_number'), e.get('status')) for e in epics]}"
    )
    # The second-hop epic's grandchildren actually merged (leaf work done).
    second_hop = next(
        (e for e in completed if e.get("title") == "Epic: split the stalled child"),
        None,
    )
    assert second_hop is not None, f"second-hop epic missing: {completed!r}"
    assert second_hop.get("merged_children") == second_hop.get("total_children"), (
        f"grandchildren not all merged: {second_hop!r}"
    )
