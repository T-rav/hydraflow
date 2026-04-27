"""CostBudgetWatcherLoop _do_work tests with mocked cost rollups."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cost_budget_watcher_loop import CostBudgetWatcherLoop


def _build_loop(*, cap: float | None = None):
    config = MagicMock()
    config.daily_cost_budget_usd = cap
    bg_workers = MagicMock()
    bg_workers.set_enabled = MagicMock()
    bg_workers.is_enabled = MagicMock(return_value=True)
    pr_manager = AsyncMock(
        find_existing_issue=AsyncMock(return_value=0),
        create_issue=AsyncMock(return_value=0),
    )
    state = MagicMock()
    state.get_cost_budget_killed_workers = MagicMock(return_value=set())
    state.set_cost_budget_killed_workers = MagicMock()
    state.get_disabled_workers = MagicMock(return_value=set())
    deps = MagicMock()
    # Construct without bg_workers (chicken-and-egg per HealthMonitorLoop /
    # TrustFleetSanityLoop precedent — BGWorkerManager takes the loop
    # registry as a constructor input, so loops that need bg_workers get
    # it injected post-construction via set_bg_workers()).
    loop = CostBudgetWatcherLoop(
        config=config,
        pr_manager=pr_manager,
        state=state,
        deps=deps,
    )
    loop.set_bg_workers(bg_workers)
    return loop, bg_workers, pr_manager, state


async def test_unlimited_when_cap_is_none() -> None:
    """Default cap=None → no-op every tick, no kills, no issues."""
    loop, bg, pr, state = _build_loop(cap=None)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        result = await loop._do_work()
    mock_rolling.assert_not_called()
    bg.set_enabled.assert_not_called()
    pr.create_issue.assert_not_awaited()
    assert result == {"action": "unlimited"}


async def test_under_cap_returns_ok() -> None:
    """Total spend < cap → ok action, no kills."""
    loop, bg, pr, state = _build_loop(cap=10.0)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 5.0}}
        result = await loop._do_work()
    assert result == {"action": "ok", "cap": 10.0, "total": 5.0}
    bg.set_enabled.assert_not_called()
    pr.create_issue.assert_not_awaited()


async def test_over_cap_disables_target_loops_and_files_issue() -> None:
    """Total > cap → disable curated workers, file deduped issue, mark in state."""
    loop, bg, pr, state = _build_loop(cap=10.0)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 15.0}}
        result = await loop._do_work()
    assert result["action"] == "killed"
    assert result["cap"] == 10.0
    assert result["total"] == 15.0
    # set_enabled called for every name in _TARGET_WORKERS, with enabled=False
    assert bg.set_enabled.call_count > 0
    for call in bg.set_enabled.call_args_list:
        assert call.args[1] is False
    # state recorded which loops were killed
    state.set_cost_budget_killed_workers.assert_called_once()
    killed = state.set_cost_budget_killed_workers.call_args.args[0]
    assert isinstance(killed, set)
    assert len(killed) > 0
    # issue filed
    pr.create_issue.assert_awaited_once()
    issue_kwargs = pr.create_issue.await_args.kwargs
    assert issue_kwargs["title"] == "[cost-budget] daily cap exceeded"
    assert "hydraflow-find" in issue_kwargs["labels"]


async def test_over_cap_dedups_when_issue_already_open() -> None:
    """find_existing_issue returns >0 → no duplicate issue."""
    loop, bg, pr, state = _build_loop(cap=10.0)
    pr.find_existing_issue = AsyncMock(return_value=42)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 15.0}}
        await loop._do_work()
    pr.create_issue.assert_not_awaited()


async def test_recovery_reenables_only_watcher_kills() -> None:
    """When total drops back below cap, only re-enable loops the watcher killed."""
    loop, bg, pr, state = _build_loop(cap=10.0)
    state.get_cost_budget_killed_workers = MagicMock(
        return_value={"dependabot_merge", "ci_monitor"}
    )
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 5.0}}
        result = await loop._do_work()
    assert result["action"] == "recovered"
    # set_enabled(name, True) for exactly the recorded set, not anything else
    enabled_calls = [c for c in bg.set_enabled.call_args_list if c.args[1] is True]
    enabled_names = {c.args[0] for c in enabled_calls}
    assert enabled_names == {"dependabot_merge", "ci_monitor"}
    state.set_cost_budget_killed_workers.assert_called_once_with(set())


async def test_recovery_no_op_when_no_prior_kills() -> None:
    """Total under cap and no prior kills → ok, not recovered."""
    loop, bg, pr, state = _build_loop(cap=10.0)
    state.get_cost_budget_killed_workers = MagicMock(return_value=set())
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 5.0}}
        result = await loop._do_work()
    assert result["action"] == "ok"
    bg.set_enabled.assert_not_called()


async def test_kill_skips_already_operator_disabled_loops() -> None:
    """If operator already disabled a loop, watcher must not claim authorship
    or re-enable it on recovery.

    Mechanic: ``_kill_caretakers`` only adds a worker to
    ``cost_budget_killed_workers`` if ``bg_workers.is_enabled(name)`` was
    True at kill time. So operator-pre-disabled workers never enter our
    set; recovery doesn't touch them.
    """
    loop, bg, pr, state = _build_loop(cap=10.0)
    # Operator had `dependabot_merge` disabled before cap was breached.
    # bg_workers.is_enabled returns False for it, True for everything else.

    def is_enabled(name: str) -> bool:
        return name != "dependabot_merge"

    bg.is_enabled = MagicMock(side_effect=is_enabled)

    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 15.0}}
        await loop._do_work()

    # Watcher killed everything EXCEPT dependabot_merge (operator already had it off)
    state.set_cost_budget_killed_workers.assert_called_once()
    killed_set = state.set_cost_budget_killed_workers.call_args.args[0]
    assert "dependabot_merge" not in killed_set
    # And the actual set_enabled(False) call list also excludes it
    disable_calls = [c for c in bg.set_enabled.call_args_list if c.args[1] is False]
    disable_names = {c.args[0] for c in disable_calls}
    assert "dependabot_merge" not in disable_names


async def test_kill_switch_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    """HYDRAFLOW_DISABLE_COST_BUDGET_WATCHER=1 → return immediately."""
    monkeypatch.setenv("HYDRAFLOW_DISABLE_COST_BUDGET_WATCHER", "1")
    loop, bg, pr, state = _build_loop(cap=10.0)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        result = await loop._do_work()
    assert result == {"skipped": "kill_switch"}
    mock_rolling.assert_not_called()
    bg.set_enabled.assert_not_called()
