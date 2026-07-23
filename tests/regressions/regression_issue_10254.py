"""Regression test for issue #10254.

Bug: ``RCBudgetLoop._compute_baselines`` built its rolling-30d median and
recent-5 spike baselines from EVERY completed ``rc-promotion-scenario.yml``
run — including gate-only runs where the workflow's ``gate`` job resolved
``should_run=false`` (a schedule tick with no open ``rc/*`` PR, or a non-RC
PR). On those runs ``Scenario Tests`` / ``Browser Scenarios`` / ``Trust Gate``
are all skipped, so the run finishes in a few seconds. Because the workflow
also runs on a ``*/30 * * * *`` cron, the history is dominated by these
near-zero gate-only runs, deflating the median/spike thresholds so a real full
run reads as an extreme spike (the #10216 "2729s vs 7s median" artifact).

Fix: exclude gate-only runs (``run["gate_only"] is True``) from the baseline
population for BOTH the median and the recent-5 spike window, while leaving the
``current`` run selection (newest by ``createdAt``) — and thus its own duration
reporting — unchanged.

Gate-only identification (verified against live runs):
  - Gate-only run jobs: ``Scenario Tests`` == "skipped", ``Browser Scenarios``
    == "skipped".
  - Full run jobs: ``Scenario Tests`` == "success" (even a schedule-triggered
    full run against an open rc/* PR — e.g. the 2729s #10216 run).

These tests assert the CORRECT (post-fix) behaviour and are GREEN once the fix
lands.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from rc_budget_loop import RCBudgetLoop


def _loop(tmp_path: Path) -> RCBudgetLoop:
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_rc_budget_duration_history.return_value = []
    pr_manager = AsyncMock()
    dedup = MagicMock()
    dedup.get.return_value = set()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )
    return RCBudgetLoop(
        config=cfg, state=state, pr_manager=pr_manager, dedup=dedup, deps=deps
    )


def test_gate_only_runs_excluded_from_baseline(tmp_path: Path) -> None:
    """Near-zero gate-only runs must not deflate median/recent-max baselines."""
    loop = _loop(tmp_path)
    # Gate-only runs are the most-recent history entries (frequent cron ticks),
    # so without the fix they dominate the recent-5 spike window and the median.
    gate_only = [
        {
            "databaseId": 90 - k,
            "duration_s": dur,
            "createdAt": f"2026-04-{29 - k:02d}T00:00:00Z",
            "conclusion": "success",
            "gate_only": True,
        }
        for k, dur in enumerate([7, 6, 8, 5, 9])
    ]
    full = [
        {
            "databaseId": 50 - k,
            "duration_s": dur,
            "createdAt": f"2026-04-{24 - k:02d}T00:00:00Z",
            "conclusion": "success",
            "gate_only": False,
        }
        for k, dur in enumerate([800, 810, 790, 820, 805])
    ]
    current = {
        "databaseId": 100,
        "duration_s": 1600,
        "createdAt": "2026-04-30T00:00:00Z",
        "conclusion": "success",
        "gate_only": False,
    }

    resolved, baselines = loop._compute_baselines([current, *gate_only, *full])

    # current unaffected (still newest), baseline from full runs only.
    assert resolved["databaseId"] == 100
    assert baselines["rolling_median"] == 805  # median([790,800,805,810,820])
    assert baselines["recent_max"] == 820  # not 9 (the gate-only max)

    # And a normal full run no longer reads as a spike against the clean
    # baseline (1600 < 2.0 * 820), whereas the polluted baseline (recent_max 9)
    # would have tripped it.
    signals = dict(loop._check_signals(current, baselines))
    assert "spike" not in signals


def test_skipped_suite_jobs_identify_gate_only_run(tmp_path: Path) -> None:
    """Job-conclusion signal: scenario/browser skipped => gate-only."""
    loop = _loop(tmp_path)
    assert (
        loop._jobs_indicate_gate_only(
            [
                {"name": "Resolve RC PR", "conclusion": "success"},
                {"name": "Scenario Tests", "conclusion": "skipped"},
                {"name": "Browser Scenarios", "conclusion": "skipped"},
            ]
        )
        is True
    )
    # Schedule-triggered FULL run (#10216 shape): scenario ran, browser cancelled.
    assert (
        loop._jobs_indicate_gate_only(
            [
                {"name": "Resolve RC PR", "conclusion": "success"},
                {"name": "Scenario Tests", "conclusion": "success"},
                {"name": "Browser Scenarios", "conclusion": "cancelled"},
            ]
        )
        is False
    )


@pytest.mark.asyncio
async def test_ambiguous_schedule_run_resolved_via_jobs(tmp_path: Path) -> None:
    """Schedule runs are undecidable from list fields; jobs settle + cache them."""
    loop = _loop(tmp_path)
    # A pull_request run on an rc/* head is a full run with no job fetch.
    assert (
        loop._classify_from_list_fields(
            {"event": "pull_request", "headBranch": "rc/2026-07-22-1824"}
        )
        is False
    )
    # A schedule run needs the job-level fetch.
    assert (
        loop._classify_from_list_fields({"event": "schedule", "headBranch": "staging"})
        is None
    )
    fetch = AsyncMock(
        return_value=[
            {"name": "Resolve RC PR", "conclusion": "success"},
            {"name": "Scenario Tests", "conclusion": "skipped"},
            {"name": "Browser Scenarios", "conclusion": "skipped"},
        ]
    )
    loop._fetch_run_jobs_raw = fetch
    run = {"databaseId": 777, "event": "schedule", "headBranch": "staging"}
    assert await loop._classify_gate_only(run) is True
    assert await loop._classify_gate_only(run) is True
    fetch.assert_awaited_once()  # cached, not re-fetched
