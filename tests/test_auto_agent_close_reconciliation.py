"""Issue-close → clear_auto_agent_attempts integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from tests.helpers import make_bg_loop_deps


@pytest.mark.asyncio
async def test_closed_issue_attempts_cleared(tmp_path: Path) -> None:
    deps = make_bg_loop_deps(tmp_path)
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=2)
    state.clear_auto_agent_attempts = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    pr = AsyncMock()
    pr.list_closed_issues_by_label = AsyncMock(
        return_value=[
            {"number": 7},
            {"number": 12},
        ]
    )
    pr.list_issues_by_label = AsyncMock(return_value=[])
    audit = MagicMock()

    loop = AutoAgentPreflightLoop(
        config=deps.config,
        state=state,
        pr_manager=pr,
        wiki_store=None,
        audit_store=audit,
        deps=deps.loop_deps,
    )
    await loop._do_work()

    assert state.clear_auto_agent_attempts.call_count == 2
    state.clear_auto_agent_attempts.assert_any_call(7)
    state.clear_auto_agent_attempts.assert_any_call(12)


@pytest.mark.asyncio
async def test_closed_issue_no_attempts_skip_clear(tmp_path: Path) -> None:
    """Issues with 0 attempts shouldn't trigger a clear (no-op optimization)."""
    deps = make_bg_loop_deps(tmp_path)
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=0)
    state.clear_auto_agent_attempts = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    pr = AsyncMock()
    pr.list_closed_issues_by_label = AsyncMock(return_value=[{"number": 99}])
    pr.list_issues_by_label = AsyncMock(return_value=[])
    audit = MagicMock()

    loop = AutoAgentPreflightLoop(
        config=deps.config,
        state=state,
        pr_manager=pr,
        wiki_store=None,
        audit_store=audit,
        deps=deps.loop_deps,
    )
    await loop._do_work()
    state.clear_auto_agent_attempts.assert_not_called()


@pytest.mark.asyncio
async def test_closed_issue_poll_failure_does_not_block(tmp_path: Path) -> None:
    """If list_closed_issues_by_label raises, the loop continues to poll-eligible."""
    deps = make_bg_loop_deps(tmp_path)
    state = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    pr = AsyncMock()
    pr.list_closed_issues_by_label = AsyncMock(side_effect=RuntimeError("gh down"))
    pr.list_issues_by_label = AsyncMock(return_value=[])
    audit = MagicMock()

    loop = AutoAgentPreflightLoop(
        config=deps.config,
        state=state,
        pr_manager=pr,
        wiki_store=None,
        audit_store=audit,
        deps=deps.loop_deps,
    )
    result = await loop._do_work()
    # Reconcile failed but loop continued and produced normal status
    assert result == {"status": "ok", "issues_processed": 0}
