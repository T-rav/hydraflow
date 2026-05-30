"""s08 — PRUnstickerLoop is registered and emits worker status."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s08_pr_unsticker_revives_stuck_pr"
DESCRIPTION = "PRUnstickerLoop ticks in MockWorld and reports worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {
                "number": 1,
                "title": "t",
                "body": "b",
                "labels": ["hydraflow-implementing"],
            }
        ],
        prs=[
            {
                "number": 100,
                "issue_number": 1,
                "branch": "hf/issue-1",
                "ci_status": "pass",
                "merged": False,
                "labels": ["wip"],
            }
        ],
        loops_enabled=["pr_unsticker"],
        cycles_to_run=4,
    )


async def assert_outcome(api, page) -> None:
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "pr_unsticker"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )
    unsticker_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "pr_unsticker"
    ]
    assert unsticker_events
