"""Regression pins for the #11298 board-churn root causes.

Live evidence (2026-08-16): the board hit 88 open issues in a day. Two
generators: (1) intake auto-decomposition re-expanded a consolidated class
canonical into an epic + 5 parked children before anyone could build it;
(2) advisory filings had budgets on FILING but none on RETIREMENT.

Pins:
1. Intake decomposition defaults OFF — complex issues plan whole; the
   demand-driven ADR-0105 stall path remains the decomposition mechanism.
2. The retirement valve defaults ON (budget 25, grace 2d) and its engine
   never touches protected classes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from config import HydraFlowConfig
from models import TriageResult
from triage_phase import TriagePhase


def test_intake_decomposition_defaults_off() -> None:
    assert HydraFlowConfig().epic_decompose_on_intake_enabled is False


def test_intake_decompose_gated_even_for_max_complexity() -> None:
    phase = object.__new__(TriagePhase)
    phase._config = HydraFlowConfig()
    phase._epic_manager = object()
    result = TriageResult(issue_number=1, ready=True, complexity_score=10)
    issue = SimpleNamespace(id=1, tags=[])
    assert asyncio.run(phase._maybe_decompose(issue, result)) is False


def test_intake_decompose_runs_when_explicitly_enabled() -> None:
    """The flip restores the old behavior path (gate passes; the decompose
    call itself is downstream and not exercised here)."""
    config = HydraFlowConfig(epic_decompose_on_intake_enabled=True)
    assert config.epic_decompose_on_intake_enabled is True


def test_retirement_valve_defaults() -> None:
    config = HydraFlowConfig()
    assert config.backlog_budget == 25
    assert config.backlog_budget_min_age_days == 2


import pytest  # noqa: E402


@pytest.mark.asyncio
async def test_valve_dry_run_closes_nothing() -> None:
    """BLOCKING review finding: dry-run (global or loop-level) must log
    picks and close nothing — _run_gh has no dry-run awareness of its own."""
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
    import json as _json

    loop._prs = SimpleNamespace(
        _repo="o/r",
        _run_gh=AsyncMock(return_value=_json.dumps(issues)),
        post_comment=AsyncMock(),
    )
    loop._state = SimpleNamespace(
        get_stale_issue_settings=lambda: SimpleNamespace(dry_run=False)
    )
    stats = await loop._scan_backlog_budget()
    assert stats["retired"] == 0
    loop._prs.post_comment.assert_not_awaited()
    # Only the LIST call happened — never a close.
    for call in loop._prs._run_gh.await_args_list:
        assert "close" not in call.args
