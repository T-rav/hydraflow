"""Tests for src/cost_budget_alerts.py (spec §4.11 point 6)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cost_budget_alerts import check_daily_budget, check_issue_cost


@pytest.fixture
def cost_cfg(tmp_path: Path) -> MagicMock:
    """Standalone config mock — avoids the shared `config` fixture."""
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = tmp_path.joinpath
    cfg.daily_cost_budget_usd = None
    cfg.issue_cost_alert_usd = None
    cfg.find_label = ["hydraflow-find"]
    return cfg


async def test_daily_budget_none_is_noop(cost_cfg: MagicMock) -> None:
    cost_cfg.daily_cost_budget_usd = None
    pr = MagicMock()
    pr.create_issue = AsyncMock()
    dedup = MagicMock()
    bus = MagicMock()
    bus.publish = AsyncMock()
    await check_daily_budget(
        cost_cfg,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        total_cost_24h=99999.0,
        now=datetime(2026, 4, 22, tzinfo=UTC),
    )
    pr.create_issue.assert_not_awaited()
    bus.publish.assert_not_awaited()


async def test_daily_budget_under_threshold_no_alert(cost_cfg: MagicMock) -> None:
    cost_cfg.daily_cost_budget_usd = 10.0
    pr = MagicMock()
    pr.create_issue = AsyncMock()
    dedup = MagicMock()
    dedup.get.return_value = set()
    bus = MagicMock()
    bus.publish = AsyncMock()
    await check_daily_budget(
        cost_cfg,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        total_cost_24h=5.0,
        now=datetime(2026, 4, 22, tzinfo=UTC),
    )
    pr.create_issue.assert_not_awaited()


async def test_daily_budget_over_threshold_files_and_dedups(
    cost_cfg: MagicMock,
) -> None:
    cost_cfg.daily_cost_budget_usd = 10.0
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=1234)
    dedup = MagicMock()
    dedup.get.return_value = set()
    bus = MagicMock()
    bus.publish = AsyncMock()
    await check_daily_budget(
        cost_cfg,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        total_cost_24h=12.5,
        now=datetime(2026, 4, 22, 10, tzinfo=UTC),
    )
    pr.create_issue.assert_awaited_once()
    args, kwargs = pr.create_issue.call_args
    labels_arg = args[2] if len(args) > 2 else kwargs.get("labels", [])
    assert "cost-budget-exceeded" in labels_arg
    dedup.add.assert_called_once_with("cost_budget:2026-04-22")
    bus.publish.assert_awaited_once()


async def test_daily_budget_already_filed_noop(cost_cfg: MagicMock) -> None:
    cost_cfg.daily_cost_budget_usd = 10.0
    pr = MagicMock()
    pr.create_issue = AsyncMock()
    dedup = MagicMock()
    dedup.get.return_value = {"cost_budget:2026-04-22"}
    bus = MagicMock()
    bus.publish = AsyncMock()
    await check_daily_budget(
        cost_cfg,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        total_cost_24h=99.0,
        now=datetime(2026, 4, 22, tzinfo=UTC),
    )
    pr.create_issue.assert_not_awaited()


async def test_daily_budget_create_issue_failure_does_not_dedup(
    cost_cfg: MagicMock,
) -> None:
    """If create_issue raises, dedup.add is not called so the next tick retries."""
    cost_cfg.daily_cost_budget_usd = 10.0
    pr = MagicMock()
    pr.create_issue = AsyncMock(side_effect=RuntimeError("gh boom"))
    dedup = MagicMock()
    dedup.get.return_value = set()
    bus = MagicMock()
    bus.publish = AsyncMock()
    await check_daily_budget(
        cost_cfg,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        total_cost_24h=50.0,
        now=datetime(2026, 4, 22, tzinfo=UTC),
    )
    dedup.add.assert_not_called()
    bus.publish.assert_not_awaited()


async def test_daily_budget_create_issue_returns_zero_skips_dedup(
    cost_cfg: MagicMock,
) -> None:
    cost_cfg.daily_cost_budget_usd = 10.0
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=0)
    dedup = MagicMock()
    dedup.get.return_value = set()
    bus = MagicMock()
    bus.publish = AsyncMock()
    await check_daily_budget(
        cost_cfg,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        total_cost_24h=50.0,
        now=datetime(2026, 4, 22, tzinfo=UTC),
    )
    dedup.add.assert_not_called()


async def test_issue_cost_under_threshold_noop(cost_cfg: MagicMock) -> None:
    cost_cfg.issue_cost_alert_usd = 2.0
    pr = MagicMock()
    pr.create_issue = AsyncMock()
    dedup = MagicMock()
    dedup.get.return_value = set()
    bus = MagicMock()
    bus.publish = AsyncMock()
    await check_issue_cost(
        cost_cfg,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        issue_number=42,
        cost_usd=1.0,
    )
    pr.create_issue.assert_not_awaited()


async def test_issue_cost_over_threshold_files_and_dedups(
    cost_cfg: MagicMock,
) -> None:
    cost_cfg.issue_cost_alert_usd = 2.0
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=7777)
    dedup = MagicMock()
    dedup.get.return_value = set()
    bus = MagicMock()
    bus.publish = AsyncMock()
    await check_issue_cost(
        cost_cfg,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        issue_number=42,
        cost_usd=5.0,
    )
    pr.create_issue.assert_awaited_once()
    dedup.add.assert_called_once_with("issue_cost:42")
    bus.publish.assert_awaited_once()


async def test_issue_cost_disabled_noop(cost_cfg: MagicMock) -> None:
    cost_cfg.issue_cost_alert_usd = None
    pr = MagicMock()
    pr.create_issue = AsyncMock()
    dedup = MagicMock()
    bus = MagicMock()
    bus.publish = AsyncMock()
    await check_issue_cost(
        cost_cfg,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        issue_number=42,
        cost_usd=999.0,
    )
    pr.create_issue.assert_not_awaited()


async def test_issue_cost_already_filed_noop(cost_cfg: MagicMock) -> None:
    cost_cfg.issue_cost_alert_usd = 2.0
    pr = MagicMock()
    pr.create_issue = AsyncMock()
    dedup = MagicMock()
    dedup.get.return_value = {"issue_cost:42"}
    bus = MagicMock()
    bus.publish = AsyncMock()
    await check_issue_cost(
        cost_cfg,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        issue_number=42,
        cost_usd=99.0,
    )
    pr.create_issue.assert_not_awaited()
