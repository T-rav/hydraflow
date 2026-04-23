"""Blocked managed repos are skipped in the pipeline dispatch loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestrator import HydraFlowOrchestrator


def test_is_slug_blocked_reads_state_tracker() -> None:
    state = MagicMock()
    state.blocked_slugs.return_value = {"acme/widget"}
    orch = HydraFlowOrchestrator.__new__(HydraFlowOrchestrator)
    orch._state = state
    assert orch._is_slug_blocked("acme/widget") is True
    assert orch._is_slug_blocked("acme/other") is False
    assert orch._is_slug_blocked("hydraflow-self") is False


def test_is_slug_blocked_empty_state() -> None:
    state = MagicMock()
    state.blocked_slugs.return_value = set()
    orch = HydraFlowOrchestrator.__new__(HydraFlowOrchestrator)
    orch._state = state
    assert orch._is_slug_blocked("anything") is False


@pytest.mark.asyncio
async def test_pipeline_work_wrapper_skips_blocked_slug() -> None:
    """When the slug is blocked, the inner work callable is not invoked."""
    state = MagicMock()
    state.blocked_slugs.return_value = {"acme/blocked"}
    orch = HydraFlowOrchestrator.__new__(HydraFlowOrchestrator)
    orch._state = state

    inner = AsyncMock(return_value=True)
    result = await orch._pipeline_work_wrapper("acme/blocked", inner)

    assert result is False
    inner.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_work_wrapper_runs_inner_when_not_blocked() -> None:
    """When the slug is not blocked, the inner work callable runs and its result passes through."""
    state = MagicMock()
    state.blocked_slugs.return_value = set()
    orch = HydraFlowOrchestrator.__new__(HydraFlowOrchestrator)
    orch._state = state

    inner = AsyncMock(return_value=[1, 2, 3])  # list return type (plan_issues shape)
    result = await orch._pipeline_work_wrapper("acme/allowed", inner)

    assert result == [1, 2, 3]
    inner.assert_awaited_once_with()
