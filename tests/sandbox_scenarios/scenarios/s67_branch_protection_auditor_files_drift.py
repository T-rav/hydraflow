"""s67 — BranchProtectionAuditorLoop actively files a ruleset-drift issue.

Active-trigger upgrade of the s41 idle poll (#9543, unblocked by the #9644
FakeGitHub ruleset seam): the seed stands up a drifted live ruleset (a
non-canonical ``main protect``; ``staging protect`` absent entirely), the
composition root rebinds the auditor so the REAL ``audit_repo`` diff runs
against ``FakeGitHub.fetch_rulesets``, and the loop must actually file the
drift issue via ``PRPort.create_issue``.

This also retires the s41 blind spot: there the raw-``gh`` fetch errors under
the air-gap, ``_do_work`` returns ``{'error': True}``, and the heartbeat-only
assert passes anyway. Here the audit genuinely runs and its outcome is
asserted. s41 keeps covering registry wiring; this scenario has its own NEW id.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s67_branch_protection_auditor_files_drift"
DESCRIPTION = (
    "BranchProtectionAuditorLoop files a drift issue when seeded live "
    "rulesets diverge from the canonical contract (details.issue_created "
    "present), not just a heartbeat."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["branch_protection_auditor"],
        cycles_to_run=2,
        # Deliberately drifted: enforcement disabled + no rules on ``main
        # protect`` (canonical has enforcement active with required checks),
        # and ``staging protect`` missing outright — two independent drift
        # signals, so the audit reports drift regardless of how the canonical
        # contract evolves.
        rulesets={
            "main protect": {
                "name": "main protect",
                "target": "branch",
                "enforcement": "disabled",
                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
                "rules": [],
            }
        },
    )


async def assert_outcome(api, page) -> None:
    """An auditor cycle reports drift plus the filed drift-issue number."""

    def _drift_filed(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "branch_protection_auditor"
            and (e.get("data", {}).get("details") or {}).get("status") == "drift"
            and (e.get("data", {}).get("details") or {}).get("issue_created")
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _drift_filed, timeout=90.0)

    auditor_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "branch_protection_auditor"
    ]
    filed = [
        (e.get("data", {}).get("details") or {}).get("issue_created")
        for e in auditor_events
        if (e.get("data", {}).get("details") or {}).get("issue_created")
    ]
    assert filed, (
        "Expected branch_protection_auditor to file a ruleset-drift issue for "
        f"the seeded drifted rulesets; worker events: {auditor_events!r}"
    )
