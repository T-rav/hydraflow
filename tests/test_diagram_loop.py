"""Unit tests for src/diagram_loop.py:DiagramLoop.

ADR-0029 (caretaker pattern) and ADR-0049 (kill-switch convention).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from diagram_loop import DiagramLoop


@pytest.fixture
def loop_deps() -> LoopDeps:
    return LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=AsyncMock(),
        interval_cb=MagicMock(return_value=14400),
    )


def test_constructor_sets_worker_name(loop_deps):
    config = MagicMock()
    pr_manager = MagicMock()
    loop = DiagramLoop(config=config, pr_manager=pr_manager, deps=loop_deps)
    assert loop._worker_name == "diagram_loop"


def test_default_interval_is_four_hours(loop_deps):
    loop = DiagramLoop(config=MagicMock(), pr_manager=MagicMock(), deps=loop_deps)
    assert loop._get_default_interval() == 14400


@pytest.mark.asyncio
async def test_no_drift_returns_drift_false(loop_deps, tmp_path, monkeypatch):
    loop = DiagramLoop(config=MagicMock(), pr_manager=MagicMock(), deps=loop_deps)
    loop._set_repo_root(tmp_path)

    from auto_pr import AutoPrResult

    # _regen_pr returns a no-diff result → no drift, coverage check skipped.
    monkeypatch.setattr(
        loop,
        "_regen_pr",
        AsyncMock(
            return_value=AutoPrResult(
                status="no-diff", pr_url=None, branch="arch-regen-auto"
            )
        ),
    )
    result = await loop._do_work()
    assert result == {"drift": False}


@pytest.mark.asyncio
async def test_drift_opens_pr_and_runs_coverage(loop_deps, tmp_path, monkeypatch):
    loop = DiagramLoop(config=MagicMock(), pr_manager=MagicMock(), deps=loop_deps)
    loop._set_repo_root(tmp_path)

    from auto_pr import AutoPrResult

    monkeypatch.setattr(
        loop,
        "_regen_pr",
        AsyncMock(
            return_value=AutoPrResult(
                status="opened", pr_url="https://pr/1", branch="arch-regen-auto"
            )
        ),
    )
    coverage_mock = AsyncMock()
    monkeypatch.setattr(loop, "_ensure_coverage_issue", coverage_mock)

    result = await loop._do_work()
    assert result["drift"] is True
    assert result["pr_url"] == "https://pr/1"
    coverage_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_regen_pr_uses_config_base_branch_and_worktree_path_specs(
    loop_deps, tmp_path, monkeypatch
):
    config = MagicMock()
    config.diagram_loop_enabled = True
    config.base_branch.return_value = "staging"
    loop = DiagramLoop(config=config, pr_manager=MagicMock(), deps=loop_deps)
    loop._set_repo_root(tmp_path)

    captured = {}

    import auto_pr as _auto_pr_mod
    from auto_pr import AutoPrResult

    async def intercept(**kw):
        captured.update(kw)
        return AutoPrResult(
            status="opened", pr_url="https://pr/2", branch=kw["branch"], error=None
        )

    # _regen_pr must route through generate_and_open_pr_async (worktree), not
    # open_automated_pr_async (repo_root copy).
    monkeypatch.setattr(_auto_pr_mod, "generate_and_open_pr_async", intercept)
    result = await loop._regen_pr()

    assert result.pr_url == "https://pr/2"
    assert captured["base"] == "staging"
    assert captured["branch"] == "arch-regen-auto"
    assert captured["path_specs"] == ["docs/arch/generated", "docs/arch/.meta.json"]
    assert callable(captured["generate"])


@pytest.mark.asyncio
async def test_coverage_issue_auto_closes_when_all_assigned(loop_deps, monkeypatch):
    """#9359: when no loops/ports are unassigned, the open coverage issue closes."""
    pr_manager = MagicMock()
    pr_manager.find_existing_issue = AsyncMock(return_value=55)
    pr_manager.post_comment = AsyncMock()
    pr_manager.close_issue = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=0)
    loop = DiagramLoop(config=MagicMock(), pr_manager=pr_manager, deps=loop_deps)

    monkeypatch.setattr(
        loop, "_unassigned_items", AsyncMock(return_value={"loops": [], "ports": []})
    )
    await loop._ensure_coverage_issue()

    pr_manager.close_issue.assert_awaited_once_with(55)
    pr_manager.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_coverage_issue_noop_when_resolved_and_none_open(loop_deps, monkeypatch):
    """All assigned AND no open issue → nothing closed, nothing filed."""
    pr_manager = MagicMock()
    pr_manager.find_existing_issue = AsyncMock(return_value=0)
    pr_manager.close_issue = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=0)
    loop = DiagramLoop(config=MagicMock(), pr_manager=pr_manager, deps=loop_deps)

    monkeypatch.setattr(
        loop, "_unassigned_items", AsyncMock(return_value={"loops": [], "ports": []})
    )
    await loop._ensure_coverage_issue()

    pr_manager.close_issue.assert_not_awaited()
    pr_manager.create_issue.assert_not_awaited()
