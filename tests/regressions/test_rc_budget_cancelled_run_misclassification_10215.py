"""Regression #10215: RCBudgetLoop must not misreport a hung RC run.

Issue #10215 was filed as a "duration regression: 2729s vs 7s (median)",
but the run that tripped it had in fact HUNG (its Browser Scenarios job was
force-cancelled by GH Actions' own 45-minute job timeout, not slow). Two
distinct detector defects let that misfire happen and would have kept it
from ever properly recovering:

1. A cancelled run's wall-clock duration is a cancellation-timing
   artifact, not real work — but `_fetch_recent_runs` counted it exactly
   like a normal completed run, letting it become "current" (a false
   regression) and pollute the rolling-median/spike-max baselines.
2. Once a `rc_budget:{kind}` dedup key was set on the first fire, nothing
   ever cleared it short of a HUMAN-closed `rc-duration-stuck` escalation
   — which itself requires 3 unresolved attempts, structurally
   unreachable while the very first fire's key blocks every subsequent
   tick's `if key in dedup: continue` guard. Closing the first-tier
   `rc-duration-regression` issue did nothing, so the detector went blind
   after firing once.

Mirrors the sibling `test_scenario_browser_timeout_guard_10215.py`
regression (the CI-side mitigation for the same incident).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.test_rc_budget_loop import _loop, loop_env  # noqa: F401


async def test_cancelled_run_is_never_misreported_as_duration_regression(
    loop_env,
) -> None:
    """Replays the #10215 incident shape end-to-end through `_do_work`: 6
    healthy 300s runs plus a newest run CANCELLED after ~2715s (a GH
    Actions job-timeout kill). The cancelled run must be excluded from
    duration analysis entirely — it must not become "current" and must
    not count toward `runs_seen` — so no false regression issue files.
    """
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_job_breakdown = AsyncMock(return_value=[])
    loop._fetch_junit_tests = AsyncMock(return_value=[])

    healthy = [
        {
            "id": 1000 + i,
            "url": f"https://example/run/{1000 + i}",
            "status": "completed",
            "conclusion": "success",
            "created_at": f"2026-07-{14 + i:02d}T00:00:00Z",
            "run_started_at": f"2026-07-{14 + i:02d}T00:00:00Z",
            "updated_at": f"2026-07-{14 + i:02d}T00:05:00Z",
        }
        for i in range(1, 7)
    ]
    hung = {
        "id": 2000,
        "url": "https://example/run/2000",
        "status": "completed",
        "conclusion": "cancelled",
        "created_at": "2026-07-22T02:16:51Z",
        "run_started_at": "2026-07-22T01:31:51Z",
        "updated_at": "2026-07-22T02:16:51Z",
    }
    loop._github_cache.get_rc_workflow_runs = AsyncMock(return_value=[*healthy, hung])

    stats = await loop._do_work()

    assert stats["status"] == "ok", stats
    assert stats["runs_seen"] == 6, stats
    assert stats["filed"] == 0, stats
    _, _, pr, _ = loop_env
    pr.create_issue.assert_not_awaited()


async def test_closed_regression_issue_does_not_reset_attempts_to_zero(
    loop_env,
) -> None:
    """Before the fix, nothing cleared a fired `rc_budget:{kind}` dedup
    key short of a HUMAN-closed `rc-duration-stuck` escalation — which
    requires attempts>=3, unreachable while attempt #1's own key blocks
    every later tick. Closing the first-tier `rc-duration-regression`
    issue must clear the dedup key so a 2nd firing can occur, but must
    NOT reset the attempts counter back to 0 — otherwise the 3-attempt
    escalation ladder can never be climbed.
    """
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"rc_budget:median"}
    loop = _loop(loop_env)

    pr.list_closed_issues_by_label.return_value = [
        {
            "number": 1,
            "title": "RC gate duration regression: 2729s vs 7s (median)",
            "body": "",
            "labels": [],
        }
    ]

    await loop._reconcile_closed_regressions()

    dedup.set_all.assert_called_once_with(set())
    state.clear_rc_budget_attempts.assert_not_called()
