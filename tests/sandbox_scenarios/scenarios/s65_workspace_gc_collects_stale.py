"""s65 — WorkspaceGCLoop actively collects a seeded stale worktree.

Active-trigger upgrade of the s46 idle poll (#9543): the seed registers a
tracked worktree for an issue that FakeGitHub reports closed, so a GC cycle
must actually collect it — not merely heartbeat. Proves the closed-issue GC
decision runs end-to-end on the air-gapped network now that
``WorkspaceGCLoop._get_issue_state`` routes through ``PRPort.get_issue_state``
(served by FakeGitHub) instead of a raw ``gh api`` subprocess.

s46 keeps covering the idle/steady-state path; per the active-trigger
convention this scenario has its own NEW id and issue number.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s65_workspace_gc_collects_stale"
DESCRIPTION = (
    "WorkspaceGCLoop collects a seeded stale worktree whose issue is closed "
    "(details.collected >= 1), not just a heartbeat."
)

# One constant issue number across the seed's issues / stale_workspaces and
# the assertion — the seed-alignment convention for active scenario families.
_ISSUE = 7301


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["workspace_gc"],
        cycles_to_run=2,
        # Closed and label-free: the pipeline's store refresh only pulls open
        # ``hydraflow-*``-labelled issues, so only the GC loop sees this one.
        issues=[
            {
                "number": _ISSUE,
                "title": "Done issue with a leaked worktree",
                "body": "Merged manually; the worktree leaked.",
                "labels": [],
                "state": "closed",
            }
        ],
        stale_workspaces=[{"number": _ISSUE, "branch": f"agent/issue-{_ISSUE}"}],
    )


async def assert_outcome(api, page) -> None:
    """A workspace_gc cycle reports at least one collected worktree."""

    def _collected(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "workspace_gc"
            and (e.get("data", {}).get("details") or {}).get("collected", 0) >= 1
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _collected, timeout=90.0)

    gc_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "workspace_gc"
    ]
    assert any(
        (e.get("data", {}).get("details") or {}).get("collected", 0) >= 1
        for e in gc_events
    ), (
        f"Expected a workspace_gc cycle with details.collected >= 1 for the "
        f"seeded stale worktree (issue #{_ISSUE}); worker events: {gc_events!r}"
    )
