"""Regression: RC/merge CI gate must not block on advisory checks (#9910).

``wait_for_ci`` treated ANY non-passing check as a failure, so an *advisory*
check — one NOT in the base branch's required-status-check set — blocked
``StagingPromotionLoop`` from auto-merging RC promotion PRs even though GitHub
itself reported them ``MERGEABLE``. The concrete trigger was the ``CodeQL``
github-advanced-security check on ``main`` (a ruleset that does not require
it): a false-positive alert failed that advisory check on every staging->main
RC, stalling promotion for ~12 days.

The fix consults GitHub's own ``mergeStateStatus``: when all *required* checks
are satisfied and only advisory checks fail, GitHub reports
``mergeable=MERGEABLE`` + ``mergeStateStatus=UNSTABLE``, so ``wait_for_ci``
treats the run as passed (advisory failures reported, not blocking). GitHub is
the authority on which contexts are required (rulesets included), so no
ruleset parsing is needed. Fail-closed: a required-check failure yields
``mergeStateStatus=BLOCKED`` and still fails the gate, and an
undeterminable merge-state never merges on uncertainty.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from tests.helpers import make_pr_manager


def _merge_state_json(mergeable: str, mss: str) -> str:
    return json.dumps({"mergeable": mergeable, "mergeStateStatus": mss})


@pytest.mark.asyncio
async def test_advisory_failure_with_unstable_mergestate_passes(config, event_bus):
    """Required green + advisory red + mergeStateStatus=UNSTABLE → passed=True."""
    mgr = make_pr_manager(config, event_bus)
    mgr.get_pr_checks = AsyncMock(
        return_value=[
            {"name": "Tests", "state": "SUCCESS"},
            {"name": "CodeQL", "state": "FAILURE"},
        ]
    )
    mgr._run_gh = AsyncMock(return_value=_merge_state_json("MERGEABLE", "UNSTABLE"))

    passed, msg = await mgr.wait_for_ci(
        123, timeout=30, poll_interval=1, stop_event=asyncio.Event()
    )

    assert passed is True
    assert "CodeQL" in msg  # advisory failure still surfaced in the summary


@pytest.mark.asyncio
async def test_required_failure_with_blocked_mergestate_fails(config, event_bus):
    """A required check red + mergeStateStatus=BLOCKED → passed=False."""
    mgr = make_pr_manager(config, event_bus)
    mgr.get_pr_checks = AsyncMock(return_value=[{"name": "Tests", "state": "FAILURE"}])
    mgr._run_gh = AsyncMock(return_value=_merge_state_json("MERGEABLE", "BLOCKED"))

    passed, msg = await mgr.wait_for_ci(
        123, timeout=30, poll_interval=1, stop_event=asyncio.Event()
    )

    assert passed is False
    assert "Tests" in msg


@pytest.mark.asyncio
async def test_advisory_failure_but_unknown_mergestate_fails_closed(config, event_bus):
    """Undeterminable merge-state → fail closed (never merge on uncertainty)."""
    mgr = make_pr_manager(config, event_bus)
    mgr.get_pr_checks = AsyncMock(
        return_value=[
            {"name": "Tests", "state": "SUCCESS"},
            {"name": "CodeQL", "state": "FAILURE"},
        ]
    )
    mgr._run_gh = AsyncMock(return_value=_merge_state_json("UNKNOWN", "UNKNOWN"))

    passed, _ = await mgr.wait_for_ci(
        123, timeout=30, poll_interval=1, stop_event=asyncio.Event()
    )

    assert passed is False


@pytest.mark.asyncio
async def test_all_required_pass_no_merge_state_probe(config, event_bus):
    """All checks green → passed=True WITHOUT probing merge-state (no advisory
    override path needed; the probe only fires on a failure)."""
    mgr = make_pr_manager(config, event_bus)
    mgr.get_pr_checks = AsyncMock(return_value=[{"name": "Tests", "state": "SUCCESS"}])
    mgr._run_gh = AsyncMock(
        side_effect=AssertionError("merge-state must not be probed on all-green")
    )

    passed, _ = await mgr.wait_for_ci(
        123, timeout=30, poll_interval=1, stop_event=asyncio.Event()
    )

    assert passed is True
