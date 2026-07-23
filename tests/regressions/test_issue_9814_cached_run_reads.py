"""Regression #9814: flake_tracker / rc_budget read CI runs from the shared cache.

Before this fix both loops fired their own raw ``gh run list`` subprocess
per tick, so a gh timeout storm hit every loop at once (and a restart
thundering-herd fired them all together).  The fix routes the run-list
read through ``GitHubDataCache.get_rc_workflow_runs`` — one shared,
staleness-bounded snapshot fetched via ``PRPort.list_runs_for_workflow``
— so N loops share one gh call per freshness window and a gh outage
degrades to serving the stale snapshot instead of crashing.

Pinned contracts:

- ``GitHubDataCache.get_rc_workflow_runs`` serves a fresh snapshot with
  no port call, refreshes once past ``max_age_seconds`` (concurrent
  callers coalesce), serves stale-within-3x-bound on refresh failure,
  returns ``[]`` beyond that, and propagates billing signals.
- ``FlakeTrackerLoop._fetch_recent_runs`` / ``RCBudgetLoop._fetch_recent_runs``
  read the cache — never ``asyncio.create_subprocess_exec`` — and keep
  their legacy row shape (``databaseId``/``url``/``conclusion``/``createdAt``).
- ``RCBudgetLoop._fetch_job_breakdown`` reads via
  ``PRPort.get_workflow_run_jobs`` (fail-soft), not raw ``gh run view``.
- ``PRManager.list_runs_for_workflow`` hits the workflow-scoped REST runs
  endpoint and projects the documented row shape.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from flake_tracker_loop import FlakeTrackerLoop
from github_cache_loop import (
    RC_PROMOTION_WORKFLOW,
    CacheSnapshot,
    GitHubDataCache,
)
from rc_budget_loop import RCBudgetLoop
from subprocess_util import CreditExhaustedError
from tests.helpers import make_pr_manager


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_row(
    run_id: int,
    *,
    created: datetime,
    duration_s: int = 300,
    status: str = "completed",
    conclusion: str = "success",
) -> dict[str, object]:
    started = created + timedelta(seconds=10)
    return {
        "id": run_id,
        "url": f"https://github.com/hydra/hydraflow/actions/runs/{run_id}",
        "status": status,
        "conclusion": conclusion,
        "created_at": _iso(created),
        "run_started_at": _iso(started),
        "updated_at": _iso(started + timedelta(seconds=duration_s)),
    }


def _make_cache(
    tmp_path: Path,
    *,
    port_rows: list[dict[str, object]] | None = None,
    port_error: Exception | None = None,
    data_poll_interval: int = 300,
) -> tuple[GitHubDataCache, MagicMock]:
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        data_poll_interval=data_poll_interval,
    )
    prs = MagicMock()
    if port_error is not None:
        prs.list_runs_for_workflow = AsyncMock(side_effect=port_error)
    else:
        prs.list_runs_for_workflow = AsyncMock(return_value=port_rows or [])
    cache = GitHubDataCache(cfg, prs, MagicMock(), cache_dir=tmp_path / "cache")
    return cache, prs


def _seed_snapshot(
    cache: GitHubDataCache, rows: list[dict[str, object]], *, age_seconds: float
) -> None:
    cache._rc_workflow_runs = CacheSnapshot(
        data=rows, fetched_at=datetime.now(UTC) - timedelta(seconds=age_seconds)
    )


def _deps() -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


def _loop_kwargs(tmp_path: Path, gh_cache: MagicMock) -> dict[str, object]:
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_flake_attempts.return_value = 0
    state.inc_flake_attempts.return_value = 1
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    pr_manager.list_issues_by_label = AsyncMock(return_value=[])
    pr_manager.list_closed_issues_by_label = AsyncMock(return_value=[])
    dedup = MagicMock()
    dedup.get.return_value = set()
    return {
        "config": cfg,
        "state": state,
        "pr_manager": pr_manager,
        "dedup": dedup,
        "deps": _deps(),
        "github_cache": gh_cache,
    }


def _cache_mock(rows: list[dict[str, object]]) -> MagicMock:
    gh_cache = MagicMock()
    gh_cache.get_rc_workflow_runs = AsyncMock(return_value=rows)
    # FlakeTracker also reads the xdist-audit run list from the cache (#10141);
    # default to an empty audit so the xdist path is a cached-read no-op.
    gh_cache.get_xdist_audit_runs = AsyncMock(return_value=[])
    return gh_cache


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("raw subprocess spawned for a cached run read")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)


class TestGetRcWorkflowRunsCache:
    @pytest.mark.asyncio
    async def test_fresh_snapshot_served_without_port_call(
        self, tmp_path: Path
    ) -> None:
        cache, prs = _make_cache(tmp_path)
        rows = [_run_row(1, created=datetime.now(UTC))]
        _seed_snapshot(cache, rows, age_seconds=5)

        result = await cache.get_rc_workflow_runs(max_age_seconds=900)

        assert result == rows
        prs.list_runs_for_workflow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stale_snapshot_refreshes_via_port(self, tmp_path: Path) -> None:
        fresh = [_run_row(2, created=datetime.now(UTC))]
        cache, prs = _make_cache(tmp_path, port_rows=fresh)
        _seed_snapshot(
            cache, [_run_row(1, created=datetime.now(UTC))], age_seconds=2000
        )

        result = await cache.get_rc_workflow_runs(max_age_seconds=900)

        assert result == fresh
        prs.list_runs_for_workflow.assert_awaited_once_with(
            RC_PROMOTION_WORKFLOW, limit=100
        )
        assert cache.get_cache_age("rc_workflow_runs") < 60

    @pytest.mark.asyncio
    async def test_never_fetched_fetches_via_port(self, tmp_path: Path) -> None:
        rows = [_run_row(3, created=datetime.now(UTC))]
        cache, prs = _make_cache(tmp_path, port_rows=rows)

        result = await cache.get_rc_workflow_runs(max_age_seconds=900)

        assert result == rows
        prs.list_runs_for_workflow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_concurrent_stale_reads_coalesce_to_one_fetch(
        self, tmp_path: Path
    ) -> None:
        rows = [_run_row(4, created=datetime.now(UTC))]
        cache, prs = _make_cache(tmp_path, port_rows=rows)

        first, second = await asyncio.gather(
            cache.get_rc_workflow_runs(max_age_seconds=900),
            cache.get_rc_workflow_runs(max_age_seconds=900),
        )

        assert first == rows
        assert second == rows
        prs.list_runs_for_workflow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_failure_serves_stale_within_grace(
        self, tmp_path: Path
    ) -> None:
        stale = [_run_row(5, created=datetime.now(UTC))]
        cache, prs = _make_cache(tmp_path, port_error=RuntimeError("gh down"))
        _seed_snapshot(cache, stale, age_seconds=1000)

        result = await cache.get_rc_workflow_runs(max_age_seconds=900)

        assert result == stale
        prs.list_runs_for_workflow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh_failure_beyond_grace_returns_empty(
        self, tmp_path: Path
    ) -> None:
        cache, _ = _make_cache(tmp_path, port_error=RuntimeError("gh down"))
        _seed_snapshot(
            cache, [_run_row(6, created=datetime.now(UTC))], age_seconds=3000
        )

        result = await cache.get_rc_workflow_runs(max_age_seconds=900)

        assert result == []

    @pytest.mark.asyncio
    async def test_refresh_failure_never_fetched_returns_empty(
        self, tmp_path: Path
    ) -> None:
        cache, _ = _make_cache(tmp_path, port_error=RuntimeError("gh down"))

        result = await cache.get_rc_workflow_runs(max_age_seconds=900)

        assert result == []

    @pytest.mark.asyncio
    async def test_credit_exhaustion_propagates(self, tmp_path: Path) -> None:
        cache, _ = _make_cache(tmp_path, port_error=CreditExhaustedError("credits"))

        with pytest.raises(CreditExhaustedError):
            await cache.get_rc_workflow_runs(max_age_seconds=900)

    @pytest.mark.asyncio
    async def test_default_bound_derives_from_data_poll_interval(
        self, tmp_path: Path
    ) -> None:
        cache, prs = _make_cache(tmp_path, data_poll_interval=300)
        rows = [_run_row(7, created=datetime.now(UTC))]
        _seed_snapshot(cache, rows, age_seconds=850)

        result = await cache.get_rc_workflow_runs()

        assert result == rows
        prs.list_runs_for_workflow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_snapshot_survives_disk_roundtrip(self, tmp_path: Path) -> None:
        rows = [_run_row(8, created=datetime.now(UTC))]
        cache, _ = _make_cache(tmp_path, port_rows=rows)
        await cache.get_rc_workflow_runs(max_age_seconds=900)

        reloaded, prs2 = _make_cache(tmp_path)
        result = await reloaded.get_rc_workflow_runs(max_age_seconds=900)

        assert result == rows
        prs2.list_runs_for_workflow.assert_not_awaited()


class TestFlakeTrackerCachedReads:
    @pytest.mark.asyncio
    async def test_fetch_recent_runs_reads_cache_not_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
        rows = [_run_row(101 + i, created=created) for i in range(25)]
        gh_cache = _cache_mock(rows)
        loop = FlakeTrackerLoop(**_loop_kwargs(tmp_path, gh_cache))
        _forbid_subprocess(monkeypatch)

        runs = await loop._fetch_recent_runs()

        assert len(runs) == 20
        assert runs[0] == {
            "databaseId": 101,
            "url": "https://github.com/hydra/hydraflow/actions/runs/101",
            "conclusion": "success",
            "createdAt": "2026-07-19T10:00:00Z",
        }
        gh_cache.get_rc_workflow_runs.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_do_work_survives_empty_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gh_cache = _cache_mock([])
        loop = FlakeTrackerLoop(**_loop_kwargs(tmp_path, gh_cache))
        _forbid_subprocess(monkeypatch)

        result = await loop._do_work()

        assert result == {"status": "no_runs", "filed": 0, "xdist_filed": 0}


class TestRcBudgetCachedReads:
    @pytest.mark.asyncio
    async def test_fetch_recent_runs_filters_and_maps_cache_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = datetime.now(UTC)
        rows = [
            _run_row(201, created=now - timedelta(hours=1), duration_s=120),
            _run_row(
                202,
                created=now - timedelta(hours=2),
                status="in_progress",
                conclusion="",
            ),
            _run_row(203, created=now - timedelta(days=45), duration_s=100),
            _run_row(204, created=now - timedelta(hours=3), duration_s=90),
        ]
        gh_cache = _cache_mock(rows)
        loop = RCBudgetLoop(**_loop_kwargs(tmp_path, gh_cache))
        _forbid_subprocess(monkeypatch)

        runs = await loop._fetch_recent_runs()

        assert [r["databaseId"] for r in runs] == [201, 204]
        assert runs[0]["duration_s"] == 120
        assert runs[1]["duration_s"] == 90
        assert runs[0]["url"].endswith("/201")
        gh_cache.get_rc_workflow_runs.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_do_work_survives_empty_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gh_cache = _cache_mock([])
        loop = RCBudgetLoop(**_loop_kwargs(tmp_path, gh_cache))
        _forbid_subprocess(monkeypatch)

        result = await loop._do_work()

        assert result == {"status": "warmup", "runs_seen": 0}

    @pytest.mark.asyncio
    async def test_job_breakdown_reads_port_not_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kwargs = _loop_kwargs(tmp_path, _cache_mock([]))
        prs = kwargs["pr_manager"]
        prs.get_workflow_run_jobs = AsyncMock(
            return_value=[
                {
                    "name": "quick",
                    "conclusion": "success",
                    "started_at": "2026-07-19T10:00:00Z",
                    "completed_at": "2026-07-19T10:01:00Z",
                    "steps": [],
                },
                {
                    "name": "slow",
                    "conclusion": "success",
                    "started_at": "2026-07-19T10:00:00Z",
                    "completed_at": "2026-07-19T10:10:00Z",
                    "steps": [],
                },
            ]
        )
        loop = RCBudgetLoop(**kwargs)
        _forbid_subprocess(monkeypatch)

        jobs = await loop._fetch_job_breakdown({"databaseId": 777})

        assert jobs == [
            {"name": "slow", "duration_s": 600},
            {"name": "quick", "duration_s": 60},
        ]
        prs.get_workflow_run_jobs.assert_awaited_once_with(777)

    @pytest.mark.asyncio
    async def test_job_breakdown_port_failure_is_fail_soft(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kwargs = _loop_kwargs(tmp_path, _cache_mock([]))
        kwargs["pr_manager"].get_workflow_run_jobs = AsyncMock(
            side_effect=RuntimeError("gh down")
        )
        loop = RCBudgetLoop(**kwargs)
        _forbid_subprocess(monkeypatch)

        jobs = await loop._fetch_job_breakdown({"databaseId": 778})

        assert jobs == []


class TestListRunsForWorkflowAdapter:
    @pytest.mark.asyncio
    async def test_projects_workflow_scoped_rest_rows(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
        mgr = make_pr_manager(cfg, EventBus())
        mgr._run_gh = AsyncMock(
            return_value=(
                '[{"id": 11, "url": "https://x/runs/11", "status": "completed",'
                ' "conclusion": "success", "created_at": "2026-07-19T10:00:00Z",'
                ' "run_started_at": "2026-07-19T10:00:10Z",'
                ' "updated_at": "2026-07-19T10:05:10Z"}]'
            )
        )

        rows = await mgr.list_runs_for_workflow(RC_PROMOTION_WORKFLOW, limit=100)

        assert rows == [
            {
                "id": 11,
                "url": "https://x/runs/11",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-07-19T10:00:00Z",
                "run_started_at": "2026-07-19T10:00:10Z",
                "updated_at": "2026-07-19T10:05:10Z",
            }
        ]
        cmd = mgr._run_gh.await_args.args
        assert (
            f"repos/hydra/hydraflow/actions/workflows/{RC_PROMOTION_WORKFLOW}"
            "/runs?per_page=100" in cmd
        )

    @pytest.mark.asyncio
    async def test_unparseable_output_returns_empty(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
        mgr = make_pr_manager(cfg, EventBus())
        mgr._run_gh = AsyncMock(return_value="not json")

        assert await mgr.list_runs_for_workflow(RC_PROMOTION_WORKFLOW) == []

    @pytest.mark.asyncio
    async def test_limit_clamped_to_rest_page_cap(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
        mgr = make_pr_manager(cfg, EventBus())
        mgr._run_gh = AsyncMock(return_value="[]")

        await mgr.list_runs_for_workflow(RC_PROMOTION_WORKFLOW, limit=500)

        cmd = mgr._run_gh.await_args.args
        assert any("per_page=100" in part for part in cmd)


class TestFakeGitHubRunsForWorkflow:
    @pytest.mark.asyncio
    async def test_filters_by_workflow_and_projects_shape(self) -> None:
        from mockworld.fakes.fake_github import FakeGitHub

        fake = FakeGitHub()
        fake.add_workflow_run(
            1,
            workflow=RC_PROMOTION_WORKFLOW,
            conclusion="success",
            created_at="2026-07-19T10:00:00Z",
            url="https://x/runs/1",
            status="completed",
            run_started_at="2026-07-19T10:00:10Z",
            updated_at="2026-07-19T10:05:10Z",
        )
        fake.add_workflow_run(2, workflow="other.yml", conclusion="failure")

        rows = await fake.list_runs_for_workflow(RC_PROMOTION_WORKFLOW)

        assert rows == [
            {
                "id": 1,
                "url": "https://x/runs/1",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-07-19T10:00:00Z",
                "run_started_at": "2026-07-19T10:00:10Z",
                "updated_at": "2026-07-19T10:05:10Z",
            }
        ]

    @pytest.mark.asyncio
    async def test_legacy_list_workflow_runs_shape_unchanged(self) -> None:
        from mockworld.fakes.fake_github import FakeGitHub

        fake = FakeGitHub()
        fake.add_workflow_run(
            3,
            workflow="Tests",
            conclusion="failure",
            created_at="2026-07-19T09:00:00Z",
            pr_number=12,
            url="https://x/runs/3",
        )

        rows = await fake.list_workflow_runs()

        assert rows == [
            {
                "id": 3,
                "workflow": "Tests",
                "conclusion": "failure",
                "created_at": "2026-07-19T09:00:00Z",
                "pr_number": 12,
            }
        ]
