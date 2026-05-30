"""s09 — dependabot PR with green CI → auto-merged."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s09_dependabot_auto_merge"
DESCRIPTION = "Dependabot PR + green CI → DependabotMergeLoop merges without human."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        prs=[
            {
                "number": 100,
                "issue_number": 0,
                "branch": "dependabot/npm/foo-1.2.3",
                "ci_status": "pass",
                "merged": False,
                "labels": ["dependencies"],
            }
        ],
        loops_enabled=["dependabot_merge"],
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    events = await api.wait_until(
        "/api/events",
        lambda p: any(
            item.get("type") == "background_worker_status"
            and item.get("data", {}).get("worker") == "dependabot_merge"
            and item.get("data", {}).get("details", {}).get("merged", 0) >= 1
            for item in (p if isinstance(p, list) else [])
        ),
        timeout=45.0,
    )
    assert any(
        item.get("type") == "background_worker_status"
        and item.get("data", {}).get("worker") == "dependabot_merge"
        and item.get("data", {}).get("details", {}).get("merged", 0) >= 1
        for item in events
    )
