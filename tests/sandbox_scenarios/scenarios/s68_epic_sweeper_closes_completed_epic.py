"""s68 — EpicSweeperLoop actively closes an epic whose children are all done.

Active-trigger upgrade of the s23 idle poll (#9543): the seed carries an open
epic (checkbox body ref) whose single child issue is already closed, so a
sweep cycle must actually close the epic — check the checkbox, label it
fixed, comment, and ``close_issue`` through PRPort — not merely heartbeat.
Everything routes through FakeIssueFetcher/FakeGitHub; no network reads.

s23 keeps covering the idle/no-epics path; this scenario has its own NEW ids
per the active-trigger convention.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s68_epic_sweeper_closes_completed_epic"
DESCRIPTION = (
    "EpicSweeperLoop auto-closes a seeded epic whose only sub-issue is closed "
    "(details.swept >= 1), not just a heartbeat."
)

# One constant pair across the seed body's checkbox ref and the assertions.
_CHILD = 7401
_EPIC = 7402


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["epic_sweeper"],
        cycles_to_run=2,
        issues=[
            {
                # Closed, label-free child: only the sweeper's by-number fetch
                # sees it; the pipeline's store refresh never picks it up.
                "number": _CHILD,
                "title": "Child work item (done)",
                "body": "Completed and closed.",
                "labels": [],
                "state": "closed",
            },
            {
                # ``hydraflow-epic`` is not a pipeline lifecycle label, so the
                # epic is visible to the sweeper's label fetch only.
                "number": _EPIC,
                "title": "Epic: one-child rollup",
                "body": f"## Sub-issues\n\n- [ ] #{_CHILD}\n",
                "labels": ["hydraflow-epic"],
                "state": "open",
            },
        ],
    )


async def assert_outcome(api, page) -> None:
    """A sweep cycle reports the epic checked and swept (auto-closed)."""

    def _swept(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "epic_sweeper"
            and (e.get("data", {}).get("details") or {}).get("swept", 0) >= 1
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _swept, timeout=90.0)

    sweep_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "epic_sweeper"
    ]
    assert any(
        (e.get("data", {}).get("details") or {}).get("swept", 0) >= 1
        for e in sweep_events
    ), (
        f"Expected epic_sweeper to auto-close epic #{_EPIC} (its only child "
        f"#{_CHILD} is closed) with details.swept >= 1; worker events: "
        f"{sweep_events!r}"
    )
