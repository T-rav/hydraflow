"""Regression pins for the #11298 board-churn root causes.

Live evidence (2026-08-16): the board hit 88 open issues in a day. Two
generators: (1) intake auto-decomposition re-expanded a consolidated class
canonical into an epic + 5 parked children before anyone could build it;
(2) advisory filings had budgets on FILING but none on RETIREMENT.

Pins:
1. Intake decomposition is REMOVED (hardened from the original default-OFF
   flag): complex issues plan whole; the demand-driven ADR-0105 stall path
   (``preflight.decompose_terminal``) is the only decomposition mechanism.
2. The retirement valve defaults ON (budget 25, grace 2d) and its engine
   never touches protected classes.
"""

from __future__ import annotations

from types import SimpleNamespace

from config import HydraFlowConfig
from triage_phase import TriagePhase


def test_intake_decomposition_path_removed() -> None:
    """The #11298 root cause cannot recur: neither the flag nor the intake
    decomposition method exists any more. A reintroduction under the same
    names must consciously delete this pin."""
    assert "epic_decompose_on_intake_enabled" not in HydraFlowConfig.model_fields
    assert not hasattr(TriagePhase, "_maybe_decompose")


def test_triage_runner_has_no_intake_decomposition_seam() -> None:
    from triage import TriageRunner

    assert not hasattr(TriageRunner, "run_decomposition")


def test_retirement_valve_defaults() -> None:
    config = HydraFlowConfig()
    assert config.backlog_budget == 25
    assert config.backlog_budget_min_age_days == 2


import pytest  # noqa: E402


@pytest.mark.asyncio
async def test_valve_dry_run_closes_nothing() -> None:
    """BLOCKING review finding: dry-run (global or loop-level) must log
    picks and close nothing — the loop's own dry_run OR gate must fire
    before close_issue is ever called."""
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock

    from stale_issue_loop import StaleIssueLoop

    loop = object.__new__(StaleIssueLoop)
    config = HydraFlowConfig(dry_run=True, backlog_budget=1)
    loop._config = config
    created = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    issues = [
        {
            "number": n,
            "title": f"i{n}",
            "createdAt": created,
            "labels": [{"name": "hydraflow-find"}],
        }
        for n in (1, 2, 3)
    ]

    loop._prs = SimpleNamespace(
        list_all_issues=AsyncMock(return_value=issues),
        close_issue=AsyncMock(return_value=True),
        post_comment=AsyncMock(),
    )
    loop._state = SimpleNamespace(
        get_stale_issue_settings=lambda: SimpleNamespace(dry_run=False)
    )
    stats = await loop._scan_backlog_budget()
    assert stats["retired"] == 0
    loop._prs.post_comment.assert_not_awaited()
    loop._prs.close_issue.assert_not_awaited()
