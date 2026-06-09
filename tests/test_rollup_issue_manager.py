"""Unit tests for RollupIssueManager (#9359 issue-hygiene)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from rollup_issue_manager import RollupIssueManager
from state import StateTracker


def _make(tmp_path: Path, *, create_return: int = 100):
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=create_return)
    pr.update_issue_body = AsyncMock()
    pr.close_issue = AsyncMock()
    pr.post_comment = AsyncMock()
    state = StateTracker(state_file=tmp_path / "s.json")
    mgr = RollupIssueManager(
        pr=pr, state=state, namespace="ns", labels=["hydraflow-find"]
    )
    return mgr, pr, state


@pytest.mark.asyncio
async def test_ensure_creates_once_and_tracks(tmp_path: Path) -> None:
    mgr, pr, state = _make(tmp_path)
    n = await mgr.ensure("subj", title="T", body="B")
    assert n == 100
    pr.create_issue.assert_awaited_once_with("T", "B", ["hydraflow-find"])
    assert state.get_rollup_issue("ns:subj")["issue_number"] == 100


@pytest.mark.asyncio
async def test_ensure_unchanged_body_is_noop(tmp_path: Path) -> None:
    mgr, pr, _state = _make(tmp_path)
    await mgr.ensure("subj", title="T", body="B")
    n = await mgr.ensure("subj", title="T", body="B")
    assert n == 100
    pr.create_issue.assert_awaited_once()  # not re-created
    pr.update_issue_body.assert_not_awaited()  # body unchanged


@pytest.mark.asyncio
async def test_ensure_changed_body_updates_in_place(tmp_path: Path) -> None:
    mgr, pr, _state = _make(tmp_path)
    await mgr.ensure("subj", title="T", body="B1")
    n = await mgr.ensure("subj", title="T", body="B2")
    assert n == 100
    pr.create_issue.assert_awaited_once()  # still only one create
    pr.update_issue_body.assert_awaited_once_with(100, "B2")


@pytest.mark.asyncio
async def test_ensure_zero_sentinel_not_tracked(tmp_path: Path) -> None:
    mgr, pr, state = _make(tmp_path, create_return=0)
    n = await mgr.ensure("subj", title="T", body="B")
    assert n == 0
    assert state.get_rollup_issue("ns:subj") is None  # not latched
    # next tick retries the create
    await mgr.ensure("subj", title="T", body="B")
    assert pr.create_issue.await_count == 2


@pytest.mark.asyncio
async def test_resolve_closes_and_clears(tmp_path: Path) -> None:
    mgr, pr, state = _make(tmp_path)
    await mgr.ensure("subj", title="T", body="B")
    closed = await mgr.resolve("subj", comment="done")
    assert closed is True
    pr.post_comment.assert_awaited_once_with(100, "done")
    pr.close_issue.assert_awaited_once_with(100)
    assert state.get_rollup_issue("ns:subj") is None


@pytest.mark.asyncio
async def test_resolve_untracked_is_idempotent_noop(tmp_path: Path) -> None:
    mgr, pr, _state = _make(tmp_path)
    closed = await mgr.resolve("never-filed")
    assert closed is False
    pr.close_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_all_except_closes_only_inactive(tmp_path: Path) -> None:
    pr = MagicMock()
    pr.update_issue_body = AsyncMock()
    pr.close_issue = AsyncMock()
    pr.post_comment = AsyncMock()
    # distinct issue numbers per subject
    pr.create_issue = AsyncMock(side_effect=[201, 202, 203])
    state = StateTracker(state_file=tmp_path / "s.json")
    mgr = RollupIssueManager(pr=pr, state=state, namespace="alerts", labels=["x"])

    for s in ("a", "b", "c"):
        await mgr.ensure(s, title=f"alert {s}", body="b")

    closed = await mgr.resolve_all_except({"b"}, comment="resolved")
    assert closed == 2
    assert {c.args[0] for c in pr.close_issue.await_args_list} == {201, 203}
    assert state.get_rollup_issue("alerts:b")["issue_number"] == 202
    assert state.get_rollup_issue("alerts:a") is None
    assert state.get_rollup_issue("alerts:c") is None
