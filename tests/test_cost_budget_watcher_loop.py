"""Unit tests for CostBudgetWatcherLoop (advisor-a03 coverage gap).

Closes the unit-test gap identified in the coverage-matrix audit.
The canonical name ``test_cost_budget_watcher_loop.py`` satisfies the
``_unit_check`` naming pattern used by the coverage-matrix generator.

Substantive behavioural tests live in ``test_cost_budget_watcher_scenario.py``
(filed before the naming convention was settled). This module adds a
lightweight smoke test that confirms the loop constructs successfully and
honours the ``daily_cost_budget_usd = None`` (unlimited) short-circuit —
the concrete signal that closes the matrix gap.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cost_budget_watcher_loop import CostBudgetWatcherLoop


def _make_loop(cap: float | None = None) -> CostBudgetWatcherLoop:
    config = MagicMock()
    config.daily_cost_budget_usd = cap
    config.cost_budget_watcher_loop_enabled = True
    # Throttle off by default; throttle tests opt in via _make_throttle_loop.
    config.cost_throttle_ratio = 0.0
    state = MagicMock()
    state.get_cost_budget_killed_workers.return_value = set()
    state.get_cost_throttled_workers.return_value = {}
    pr_manager = AsyncMock()
    deps = MagicMock()
    loop = CostBudgetWatcherLoop(
        config=config,
        pr_manager=pr_manager,
        state=state,
        deps=deps,
    )
    bg = MagicMock()
    bg.is_enabled.return_value = True
    loop.set_bg_workers(bg)
    return loop


@pytest.mark.asyncio
async def test_unlimited_mode_returns_action_unlimited() -> None:
    """``daily_cost_budget_usd = None`` → action=unlimited, no I/O."""
    loop = _make_loop(cap=None)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_build:
        result = await loop._do_work()  # noqa: SLF001
    mock_build.assert_not_called()
    assert result == {"action": "unlimited"}


@pytest.mark.asyncio
async def test_under_cap_returns_ok() -> None:
    """Spend below cap → action=ok, nothing disabled."""
    loop = _make_loop(cap=50.0)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_build:
        mock_build.return_value = {"total": {"cost_usd": 20.0}}
        result = await loop._do_work()  # noqa: SLF001
    assert result["action"] == "ok"
    assert result["cap"] == 50.0
    assert result["total"] == 20.0


def _make_throttle_loop(
    cap: float = 50.0,
    ratio: float = 0.8,
    total: float = 45.0,
    priors: dict | None = None,
    intervals: dict | None = None,
):
    loop = _make_loop(cap=cap)
    loop._config.cost_throttle_ratio = ratio
    loop._state.get_cost_throttled_workers.return_value = dict(priors or {})
    bg = loop._bg_workers
    bg.worker_intervals = dict(intervals or {})
    bg.get_interval.return_value = 600
    return loop, total


@pytest.mark.asyncio
async def test_throttle_band_stretches_intervals_and_saves_priors() -> None:
    """cap*ratio <= spend <= cap → stretch every target's interval, saving
    the pre-throttle override (None = operator had none) for exact restore."""
    loop, total = _make_throttle_loop(intervals={"repo_wiki": 900})
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_build:
        mock_build.return_value = {"total": {"cost_usd": total}}
        result = await loop._do_work()  # noqa: SLF001
    assert result["action"] == "throttled"
    loop._bg_workers.set_interval.assert_any_call("repo_wiki", 2400)
    loop._bg_workers.set_interval.assert_any_call("flake_tracker", 2400)
    priors = loop._state.set_cost_throttled_workers.call_args.args[0]
    assert priors["repo_wiki"] == 900  # operator override preserved
    assert priors["flake_tracker"] is None  # no override before throttle


@pytest.mark.asyncio
async def test_throttle_is_idempotent_across_ticks() -> None:
    """Already-throttled workers must not be re-stretched (compounding 4x)."""
    from cost_budget_watcher_loop import _TARGET_WORKERS

    all_priors = dict.fromkeys(_TARGET_WORKERS)
    loop, total = _make_throttle_loop(priors=all_priors)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_build:
        mock_build.return_value = {"total": {"cost_usd": total}}
        result = await loop._do_work()  # noqa: SLF001
    assert result["action"] == "throttled"
    loop._bg_workers.set_interval.assert_not_called()


@pytest.mark.asyncio
async def test_recovery_below_band_restores_intervals() -> None:
    """Below cap*ratio: operator overrides restored, throttle-only overrides
    cleared entirely, state emptied."""
    loop, _ = _make_throttle_loop(priors={"repo_wiki": 900, "flake_tracker": None})
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_build:
        mock_build.return_value = {"total": {"cost_usd": 10.0}}
        result = await loop._do_work()  # noqa: SLF001
    assert result["action"] == "unthrottled"
    loop._bg_workers.set_interval.assert_called_once_with("repo_wiki", 900)
    loop._bg_workers.clear_interval.assert_called_once_with("flake_tracker")
    loop._state.set_cost_throttled_workers.assert_called_once_with({})


@pytest.mark.asyncio
async def test_over_cap_still_kills_without_touching_throttle() -> None:
    """The hard cap keeps its kill contract; throttle state survives so
    revived loops come back throttled, not full-cadence."""
    loop, _ = _make_throttle_loop(priors={"repo_wiki": None})
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_build:
        mock_build.return_value = {"total": {"cost_usd": 60.0}}
        result = await loop._do_work()  # noqa: SLF001
    assert result["action"] == "killed"
    loop._bg_workers.set_interval.assert_not_called()
    loop._bg_workers.clear_interval.assert_not_called()


@pytest.mark.asyncio
async def test_ratio_zero_disables_throttling() -> None:
    loop, total = _make_throttle_loop(ratio=0.0)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_build:
        mock_build.return_value = {"total": {"cost_usd": total}}
        result = await loop._do_work()  # noqa: SLF001
    assert result["action"] == "ok"
    loop._bg_workers.set_interval.assert_not_called()
