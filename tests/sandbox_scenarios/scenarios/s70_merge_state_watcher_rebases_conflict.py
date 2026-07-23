"""s70 — MergeStateWatcherLoop actively rebases a conflicting PR.

Active-trigger upgrade of the s49 idle poll (#9543): the seed carries a PR
flagged ``mergeable: false`` (CONFLICTING), so a watcher cycle must actually
act — ``list_conflicting_prs`` surfaces it, ``update_pr_branch`` rebases it,
and the re-check reports it mergeable — not merely heartbeat. All PR I/O
routes through PRPort/FakeGitHub; the CH-2 approval-record reconciler (a raw
``gh`` boundary with no Fake seam) is config-disabled in the sandbox.

s49 keeps covering the idle/no-conflicts path; this scenario has its own NEW
ids per the active-trigger convention.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s70_merge_state_watcher_rebases_conflict"
DESCRIPTION = (
    "MergeStateWatcherLoop rebases a seeded CONFLICTING PR "
    "(details.rebased >= 1), not just a heartbeat."
)

# One constant pair across the seeded PR and the assertions.
_ISSUE = 8800
_PR = 8801


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["merge_state_watcher"],
        cycles_to_run=2,
        # Label-free so neither the HITL label nor SKIP_LABELS applies and no
        # other loop claims the PR; ``mergeable: false`` is the trigger.
        prs=[
            {
                "number": _PR,
                "issue_number": _ISSUE,
                "branch": f"agent/issue-{_ISSUE}",
                "mergeable": False,
            }
        ],
    )


async def assert_outcome(api, page) -> None:
    """A watcher cycle reports the conflicting PR checked and rebased."""

    def _rebased(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "merge_state_watcher"
            and (e.get("data", {}).get("details") or {}).get("rebased", 0) >= 1
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _rebased, timeout=90.0)

    watcher_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "merge_state_watcher"
    ]
    assert any(
        (e.get("data", {}).get("details") or {}).get("rebased", 0) >= 1
        for e in watcher_events
    ), (
        f"Expected merge_state_watcher to rebase seeded CONFLICTING PR "
        f"#{_PR} (details.rebased >= 1); worker events: {watcher_events!r}"
    )
