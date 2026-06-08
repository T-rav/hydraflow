"""Regression: StagingPromotionLoop must treat a CI *timeout* as pending, not failure.

Issues #9219/#9271/#9311/#9323/#9328/#9330/#9334/#9342 — the staging->main
promotion pipeline stalled for ~3 days. ``PRManager.wait_for_ci`` returns
``(False, "Timeout after {timeout}s")`` when CI is still running past the poll
window (by design: the loop is a tight poller that retries each tick). But
``_handle_open_promotion``'s guard matched the literal substring ``"timed out"``,
which ``"Timeout after 60s"`` does NOT contain. So every slow-CI tick fell through
to the failure path: it force-closed a *green* RC PR and filed a noise issue.

The existing unit tests masked this because they fed the loop a hand-written
``"Timed out after 60s"`` / ``"timed out waiting for checks"`` summary that DID
match the guard — strings ``wait_for_ci`` never actually produces. These tests
assert against the EXACT production sentinel string.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from models import PRInfo
from staging_promotion_loop import StagingPromotionLoop


def _make_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ci_result: tuple[bool, str],
) -> tuple[StagingPromotionLoop, MagicMock]:
    monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
    monkeypatch.setenv("HYDRAFLOW_STAGING_PROMOTION_INTERVAL", "300")
    cfg = HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        data_root=tmp_path / "data",
    )

    async def _sleep(_s: float) -> None:
        return None

    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=lambda _n: True,
        sleep_fn=_sleep,
    )

    prs = MagicMock()
    prs.find_open_promotion_pr = AsyncMock(
        return_value=PRInfo(
            number=99,
            issue_number=0,
            branch="rc/2026-06-06-0114",
            url="https://github.com/o/r/pull/99",
            draft=False,
        )
    )
    prs.wait_for_ci = AsyncMock(return_value=ci_result)
    prs.merge_promotion_pr = AsyncMock(return_value=True)
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    prs.create_issue = AsyncMock(return_value=1234)
    prs.list_rc_branches = AsyncMock(return_value=[])
    loop = StagingPromotionLoop(config=cfg, prs=prs, deps=deps)
    return loop, prs


@pytest.mark.asyncio
async def test_real_wait_for_ci_timeout_string_is_pending_not_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The EXACT string PRManager.wait_for_ci emits on timeout -> ci_pending."""
    # This is verbatim what src/pr_manager.py returns: f"Timeout after {timeout}s".
    loop, prs = _make_loop(
        tmp_path, monkeypatch, ci_result=(False, "Timeout after 60s")
    )

    result = await loop._do_work()

    assert result == {"status": "ci_pending", "pr": 99}
    prs.close_issue.assert_not_called()
    prs.create_issue.assert_not_called()
    prs.merge_promotion_pr.assert_not_called()


@pytest.mark.asyncio
async def test_kill_switch_stopped_is_pending_not_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """wait_for_ci returns 'Stopped' when the kill-switch fires mid-poll.

    That is a shutdown signal, not a CI failure — it must not close the green PR.
    """
    loop, prs = _make_loop(tmp_path, monkeypatch, ci_result=(False, "Stopped"))

    result = await loop._do_work()

    assert result == {"status": "ci_pending", "pr": 99}
    prs.close_issue.assert_not_called()
    prs.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_genuine_ci_failure_still_closes_and_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real check failure must still close the PR and file an issue."""
    loop, prs = _make_loop(
        tmp_path, monkeypatch, ci_result=(False, "ci failed: Sandbox rc full suite")
    )

    result = await loop._do_work()

    assert result == {"status": "ci_failed", "pr": 99, "find_issue": 1234}
    prs.close_issue.assert_called_once_with(99)
    prs.create_issue.assert_called_once()
