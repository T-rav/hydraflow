"""s77 — StaleIssueGCLoop closes a stale HITL issue but SKIPS a fresh one.

Active-trigger scenario for #9544: before the per-issue seeded ``updated_at``
(seed field consumed by both loaders' ``FakeGitHub.add_issue``),
``FakeIssue.updated_at`` was a hard-coded ``2026-01-01T00:00:00Z`` constant —
every seeded issue read as equally stale (or equally fresh, depending on the
scenario's clock), so the "a fresh issue is skipped" branch of
``StaleIssueGCLoop._do_work`` was untestable. This scenario seeds TWO HITL
issues — one far past ``stale_issue_threshold_days`` (default 14) and one
touched an hour ago — so a GC cycle must genuinely discriminate between them:
close the stale one, skip the fresh one.

Timestamps are computed relative to real wall-clock ``datetime.now(UTC)`` at
seed-build time (mirroring the ``last_activity_age_days`` relative-offset
convention used by the epic_states materializer) so the seed never rots —
``StaleIssueGCLoop`` reads real time directly, unlike the age-offset
materializer fields that back-date state at boot.

No idle-poll counterpart exists yet for ``stale_issue_gc`` in the sandbox
catalog; this is its first scenario.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mockworld.seed import MockWorldSeed

NAME = "s77_stale_issue_gc_skips_fresh_issue"
DESCRIPTION = (
    "StaleIssueGCLoop closes a seeded far-past-threshold HITL issue "
    "(details.closed >= 1) but skips a seeded fresh one "
    "(details.skipped >= 1), proving the fresh-issue-is-skipped branch."
)

# Distinct constant issue numbers across the seed and the assertions.
_STALE_ISSUE = 7701
_FRESH_ISSUE = 7702

_HITL_LABEL = "hydraflow-hitl"


def seed() -> MockWorldSeed:
    now = datetime.now(UTC)
    # 400 days >> any realistic stale_issue_threshold_days (default 14), so
    # this issue is stale regardless of config drift.
    stale_updated_at = (now - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # 1 hour << the threshold, so this issue reads as fresh regardless.
    fresh_updated_at = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return MockWorldSeed(
        loops_enabled=["stale_issue_gc"],
        cycles_to_run=2,
        issues=[
            {
                "number": _STALE_ISSUE,
                "title": "Stale HITL escalation",
                "body": "No activity in a very long time.",
                "labels": [_HITL_LABEL],
                "updated_at": stale_updated_at,
            },
            {
                "number": _FRESH_ISSUE,
                "title": "Fresh HITL escalation",
                "body": "Touched an hour ago.",
                "labels": [_HITL_LABEL],
                "updated_at": fresh_updated_at,
            },
        ],
    )


async def assert_outcome(api, page) -> None:
    """A stale_issue_gc cycle closes the stale issue and skips the fresh one."""

    def _acted(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "stale_issue_gc"
            and (e.get("data", {}).get("details") or {}).get("closed", 0) >= 1
            and (e.get("data", {}).get("details") or {}).get("skipped", 0) >= 1
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _acted, timeout=90.0)

    gc_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "stale_issue_gc"
    ]
    assert any(
        (e.get("data", {}).get("details") or {}).get("closed", 0) >= 1
        for e in gc_events
    ), (
        f"Expected stale_issue_gc to close the seeded stale issue "
        f"#{_STALE_ISSUE} (details.closed >= 1); worker events: {gc_events!r}"
    )
    assert any(
        (e.get("data", {}).get("details") or {}).get("skipped", 0) >= 1
        for e in gc_events
    ), (
        f"Expected stale_issue_gc to skip the seeded fresh issue "
        f"#{_FRESH_ISSUE} (details.skipped >= 1); worker events: {gc_events!r}"
    )
