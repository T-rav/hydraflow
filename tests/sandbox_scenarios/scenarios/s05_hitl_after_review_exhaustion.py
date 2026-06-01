"""s05 — 3 review failures → issue is escalated into diagnostic review."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s05_hitl_after_review_exhaustion"
DESCRIPTION = "3 review failures → review-cap escalation is routed to diagnostics."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]}
        ],
        scripts={
            "plan": {1: [{"success": True}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"}] * 4},
            "review": {
                1: [
                    {"verdict": "request-changes", "comments": ["bad 1"]},
                    {"verdict": "request-changes", "comments": ["bad 2"]},
                    {"verdict": "request-changes", "comments": ["bad 3"]},
                ]
            },
        },
        cycles_to_run=10,
    )


async def assert_outcome(api, page) -> None:
    await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "hitl_escalation"
            and e.get("data", {}).get("issue") == 1
            and e.get("data", {}).get("status") == "diagnostic"
            and e.get("data", {}).get("cause") == "review_fix_cap_exceeded"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=120.0,
    )
