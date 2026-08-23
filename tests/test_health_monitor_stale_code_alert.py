"""Tests for HealthMonitor stale-code dead-man-switch (#9596).

Consumes ``git_revision.get_commits_behind`` (#9663) for the commits-behind
count — these tests never recompute staleness themselves. They monkeypatch
the two seams ``_check_stale_code`` calls: ``run_subprocess`` (the bounded
pre-read ``git fetch`` this loop owns) and ``get_commits_behind`` (the #9663
snapshot). Mirrors the ``_check_wiki_freshness`` test structure in
``test_health_monitor_wiki_stall.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import health_monitor_loop
from config import Credentials, HydraFlowConfig
from events import EventBus, EventType
from health_monitor_loop import HealthMonitorLoop, _freshness


@pytest.fixture
def hm_env(tmp_path: Path):
    from dedup_store import DedupStore

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=repo_root,
        stale_code_alert_threshold=10,
    )
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=42)
    prs.list_issues_by_label = AsyncMock(return_value=[])
    hm = HealthMonitorLoop.__new__(HealthMonitorLoop)
    hm._config = cfg
    hm._prs = prs
    hm._credentials = Credentials()
    hm._bus = EventBus()
    hm._stale_code_dedup = DedupStore(
        "hm_stale_code_test",
        tmp_path / "dedup" / "hm_stale_code_test.json",
    )
    return hm, prs


def _stub_fetch_ok(monkeypatch) -> AsyncMock:
    mock_fetch = AsyncMock(return_value="")
    monkeypatch.setattr(_freshness, "run_subprocess", mock_fetch)
    return mock_fetch


def _stub_fetch_fails(monkeypatch) -> AsyncMock:
    mock_fetch = AsyncMock(side_effect=RuntimeError("fetch failed"))
    monkeypatch.setattr(_freshness, "run_subprocess", mock_fetch)
    return mock_fetch


def _stub_commits_behind(monkeypatch, value: int | None) -> None:
    monkeypatch.setattr(_freshness, "get_commits_behind", lambda base_ref: value)


async def test_no_prs_dependency_is_silent_noop(hm_env, monkeypatch) -> None:
    hm, _prs = hm_env
    hm._prs = None
    fetch = _stub_fetch_ok(monkeypatch)
    await hm._check_stale_code()
    fetch.assert_not_called()


async def test_fetch_failure_degrades_no_op(hm_env, monkeypatch) -> None:
    """A pre-read fetch failure must degrade the tick, not alert or recover."""
    hm, prs = hm_env
    _stub_fetch_fails(monkeypatch)
    # get_commits_behind should never even be consulted after a failed fetch.
    called = AsyncMock()
    monkeypatch.setattr(_freshness, "get_commits_behind", lambda base_ref: called())

    await hm._check_stale_code()

    prs.create_issue.assert_not_awaited()
    called.assert_not_called()
    assert hm._stale_code_dedup.get() == set()


async def test_commits_behind_unavailable_degrades_no_op(hm_env, monkeypatch) -> None:
    hm, prs = hm_env
    _stub_fetch_ok(monkeypatch)
    _stub_commits_behind(monkeypatch, None)

    await hm._check_stale_code()

    prs.create_issue.assert_not_awaited()
    assert hm._stale_code_dedup.get() == set()


async def test_below_threshold_no_issue(hm_env, monkeypatch) -> None:
    hm, prs = hm_env
    _stub_fetch_ok(monkeypatch)
    _stub_commits_behind(monkeypatch, 9)  # threshold is 10

    await hm._check_stale_code()

    prs.create_issue.assert_not_awaited()


async def test_at_threshold_files_issue(hm_env, monkeypatch) -> None:
    hm, prs = hm_env
    _stub_fetch_ok(monkeypatch)
    _stub_commits_behind(monkeypatch, 10)  # >= threshold fires

    await hm._check_stale_code()

    prs.create_issue.assert_awaited_once()
    title, _body, labels = prs.create_issue.await_args.args
    assert "factory-stale-code" in title
    assert "10" in title
    assert "hydraflow-find" in labels
    assert "factory-stale-code" in labels


async def test_above_threshold_publishes_system_alert(hm_env, monkeypatch) -> None:
    hm, _prs = hm_env
    _stub_fetch_ok(monkeypatch)
    _stub_commits_behind(monkeypatch, 25)

    await hm._check_stale_code()

    alerts = [e for e in hm._bus.get_history() if e.type == EventType.SYSTEM_ALERT]
    assert len(alerts) == 1
    assert alerts[0].data["kind"] == "factory_stale_code"
    assert alerts[0].data["commits_behind"] == 25
    assert alerts[0].data["threshold"] == 10


async def test_threshold_files_once(hm_env, monkeypatch) -> None:
    """Repeated stale ticks within the same stall event file exactly one issue."""
    hm, prs = hm_env
    _stub_fetch_ok(monkeypatch)
    _stub_commits_behind(monkeypatch, 15)

    await hm._check_stale_code()
    await hm._check_stale_code()
    await hm._check_stale_code()

    prs.create_issue.assert_awaited_once()


async def test_recovery_closes_open_issue_and_clears_dedup(hm_env, monkeypatch) -> None:
    hm, prs = hm_env
    _stub_fetch_ok(monkeypatch)
    _stub_commits_behind(monkeypatch, 15)
    await hm._check_stale_code()
    assert prs.create_issue.await_count == 1
    assert "health_monitor:stale_code:stale" in hm._stale_code_dedup.get()

    # Recovered: fresh process caught back up.
    _stub_commits_behind(monkeypatch, 0)
    prs.list_issues_by_label = AsyncMock(
        return_value=[{"number": 99, "title": "x", "body": "", "updated_at": ""}]
    )
    await hm._check_stale_code()

    prs.close_issue.assert_awaited_once_with(99)
    assert hm._stale_code_dedup.get() == set()


async def test_recovery_then_restale_files_fresh_issue(hm_env, monkeypatch) -> None:
    hm, prs = hm_env
    _stub_fetch_ok(monkeypatch)
    _stub_commits_behind(monkeypatch, 15)
    await hm._check_stale_code()
    assert prs.create_issue.await_count == 1

    _stub_commits_behind(monkeypatch, 0)
    await hm._check_stale_code()

    _stub_commits_behind(monkeypatch, 15)
    await hm._check_stale_code()

    assert prs.create_issue.await_count == 2


async def test_threshold_respects_config(hm_env, monkeypatch) -> None:
    hm, prs = hm_env
    hm._config = hm._config.model_copy(update={"stale_code_alert_threshold": 50})
    _stub_fetch_ok(monkeypatch)
    _stub_commits_behind(monkeypatch, 15)

    await hm._check_stale_code()

    prs.create_issue.assert_not_awaited()


async def test_fetch_targets_origin_base_branch_bounded(hm_env, monkeypatch) -> None:
    """The pre-read fetch is single-branch and time-bounded (#9596)."""
    hm, _prs = hm_env
    fetch = _stub_fetch_ok(monkeypatch)
    _stub_commits_behind(monkeypatch, 0)

    await hm._check_stale_code()

    fetch.assert_awaited_once()
    args, kwargs = fetch.await_args
    assert args == ("git", "fetch", "origin", hm._config.base_branch())
    assert kwargs["cwd"] == hm._config.repo_root
    assert kwargs["timeout"] == health_monitor_loop._STALE_CODE_FETCH_TIMEOUT_SECS
