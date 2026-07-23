"""#10260: escalation → resolving PR opened → reconciliation clears labels,
no further auto-agent dispatch.

Reproduces the parent-issue failure (#10215): a diagnostic escalation had
already been resolved by an open, CI-green PR, but the ``hitl-escalation``/
``diagnose-failed`` labels hadn't been reconciled yet, so a later tick
re-dispatched a redundant auto-agent attempt into the same issue.

Two independent layers close this gap, both exercised here against a single
shared ``FakeGitHub`` world:

1. ``AutoAgentPreflightLoop``'s dispatch guard — synchronous, so it is
   immune to any lag before reconciliation runs.
2. ``LabelDriftWatcherLoop`` — clears the stale escalation labels so the
   issue also drops out of future polls entirely (ADR-0088).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from label_drift_watcher_loop import LabelDriftWatcherLoop
from mockworld.fakes import FakeGitHub


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *_a, **_k: None,
        enabled_cb=lambda _name: True,
    )


def _preflight_loop(cfg: HydraFlowConfig, gh: FakeGitHub) -> AutoAgentPreflightLoop:
    state = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.get_auto_agent_attempts = MagicMock(return_value=1)
    audit = MagicMock()
    audit.daily_spend = MagicMock(return_value=0.0)
    return AutoAgentPreflightLoop(
        config=cfg,
        state=state,
        pr_manager=gh,
        wiki_store=None,
        audit_store=audit,
        deps=_deps(asyncio.Event()),
    )


@pytest.mark.asyncio
async def test_escalation_pr_reconciliation_suppresses_dispatch_and_clears_labels(
    tmp_path: Path,
) -> None:
    cfg = HydraFlowConfig(data_root=tmp_path, repo="owner/repo", repo_root=tmp_path)

    gh = FakeGitHub()
    gh.add_issue(
        42,
        "flaky rc_budget regression",
        "body",
        labels=["hitl-escalation", "diagnose-failed"],
    )
    gh.add_pr(number=100, issue_number=42, branch="agent/diag-42")
    gh._prs[100].checks = [
        ("Lint", "SUCCESS"),
        ("Tests", "SUCCESS"),
        ("Security Scan", "SUCCESS"),
    ]

    # Tick 1: the dispatch guard fires BEFORE any reconciliation has run —
    # this is exactly the race that stalled the parent issue's lineage.
    preflight = _preflight_loop(cfg, gh)
    result = await preflight._do_work()

    assert result == {"status": "ok", "issues_processed": 0, "suppressed": 1}
    assert gh._issues[42].labels.count("hitl-escalation") == 1, (
        "labels are untouched by the dispatch guard — reconciliation is a "
        "separate layer"
    )

    # Tick 2: LabelDriftWatcherLoop reconciles — clears the stale escalation
    # labels now that a green resolving PR exists.
    watcher = LabelDriftWatcherLoop(config=cfg, pr_manager=gh, deps=_deps(asyncio.Event()))
    drift_stats = await watcher._do_work()

    assert drift_stats == {"detected": 1, "reconciled": 1}
    assert "hitl-escalation" not in gh._issues[42].labels
    assert "diagnose-failed" not in gh._issues[42].labels

    # Tick 3: the issue no longer carries hitl-escalation at all, so the
    # preflight loop's own poll no longer surfaces it — no further dispatch.
    result_after = await preflight._do_work()

    assert result_after == {"status": "ok", "issues_processed": 0}


@pytest.mark.asyncio
async def test_still_dispatches_when_resolving_pr_ci_not_green(
    tmp_path: Path,
) -> None:
    """Sanity check: the guard must not suppress a genuinely still-broken
    escalation just because a PR happens to be open."""
    cfg = HydraFlowConfig(data_root=tmp_path, repo="owner/repo", repo_root=tmp_path)

    gh = FakeGitHub()
    gh.add_issue(7, "still broken", "body", labels=["hitl-escalation"])
    gh.add_pr(number=200, issue_number=7, branch="agent/diag-7")
    gh._prs[200].checks = [("Tests", "FAILURE")]

    preflight = _preflight_loop(cfg, gh)
    # Force straight to the deny-list/attempt-cap path rather than a real
    # agent spawn — this test only cares that the issue was NOT suppressed.
    preflight._state.get_auto_agent_attempts = MagicMock(return_value=3)

    result = await preflight._do_work()

    assert result["issues_processed"] == 1
    assert result["suppressed"] == 0
    assert result["result_status"] == "skipped_exhausted"
    # The escalation label is untouched by the dispatch guard itself.
    assert "hitl-escalation" in gh._issues[7].labels
