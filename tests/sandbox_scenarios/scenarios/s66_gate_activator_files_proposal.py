"""s66 — GateActivatorLoop actively files a gate-activation proposal issue.

Active-trigger upgrade of the s45 idle poll (#9543): the seed scripts one
activatable planned gate, the composition root swaps the loop's ``detector=``
injection point for a closure returning it (the repo baked into the sandbox
image is steady-state — every gate active — so the production detector can
never propose), and the loop must actually file the proposal issue through
``PRPort.create_issue`` (served by FakeGitHub).

s45 keeps covering the idle/steady-state path; this scenario has its own NEW
id per the active-trigger convention.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s66_gate_activator_files_proposal"
DESCRIPTION = (
    "GateActivatorLoop files an activation issue for a seeded planned-but-"
    "enforceable gate (details.issue_created present), not just a heartbeat."
)

# One constant gate name across the seed and any debugging of the filed issue.
_GATE = "mockworld-scenarios"


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["gate_activator"],
        cycles_to_run=2,
        gate_activations=[
            {
                "name": _GATE,
                "dimension": "tests",
                "required_on": ["main", "staging"],
                "workflow": "test.yml",
                "job": "scenario-tests",
                "make_target": "scenario",
            }
        ],
    )


async def assert_outcome(api, page) -> None:
    """A gate_activator cycle reports the filed proposal issue number."""

    def _proposal_filed(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "gate_activator"
            and (e.get("data", {}).get("details") or {}).get("status") == "proposals"
            and (e.get("data", {}).get("details") or {}).get("issue_created")
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _proposal_filed, timeout=90.0)

    activator_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "gate_activator"
    ]
    filed = [
        (e.get("data", {}).get("details") or {}).get("issue_created")
        for e in activator_events
        if (e.get("data", {}).get("details") or {}).get("issue_created")
    ]
    assert filed, (
        f"Expected gate_activator to file an activation issue for the seeded "
        f"gate {_GATE!r} (details.issue_created); worker events: "
        f"{activator_events!r}"
    )
