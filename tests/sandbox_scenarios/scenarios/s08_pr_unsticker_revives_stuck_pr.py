"""s08 — PR with no activity → PRUnstickerLoop triggers auto-resync."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s08_pr_unsticker_revives_stuck_pr"
DESCRIPTION = "Stale PR detected → auto-resync triggers → PR moves."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {
                "number": 1,
                "title": "t",
                "body": "b",
                # HITL-escalated: PRUnstickerLoop only processes issues carrying
                # the hitl_label (it calls list_hitl_items(hitl_label) and unsticks
                # those with a linked PR). The stuck PR #100 links to this issue.
                "labels": ["hydraflow-hitl"],
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
    history = await api.wait_until(
        "/api/events",
        lambda p: any(
            e.get("type") == "hitl_update"
            and e.get("data", {}).get("action") == "unstick_resolved"
            for e in p
        ),
        timeout=180.0,
    )
    assert any(
        e.get("type") == "hitl_update"
        and e.get("data", {}).get("action") == "unstick_resolved"
        for e in history
    )
