"""Tests for RCBudgetLoop (spec §4.8)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from rc_budget_loop import RCBudgetLoop


def _gh_cache() -> MagicMock:
    cache = MagicMock()
    cache.get_rc_workflow_runs = AsyncMock(return_value=[])
    return cache


def _deps(stop: asyncio.Event, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_rc_budget_duration_history.return_value = []
    state.get_rc_budget_attempts.return_value = 0
    state.inc_rc_budget_attempts.return_value = 1
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr_manager, dedup


def _loop(env) -> RCBudgetLoop:
    cfg, state, pr, dedup = env
    return RCBudgetLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        deps=_deps(asyncio.Event()),
        github_cache=_gh_cache(),
    )


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    loop = _loop(loop_env)
    assert loop._worker_name == "rc_budget"
    assert loop._get_default_interval() == 14400


async def test_do_work_warmup_when_history_short(loop_env) -> None:
    loop = _loop(loop_env)
    loop._fetch_recent_runs = AsyncMock(
        return_value=[
            {
                "databaseId": i,
                "duration_s": 300,
                "createdAt": f"2026-04-{i:02d}T00:00:00Z",
                "conclusion": "success",
            }
            for i in range(1, 4)
        ]
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "warmup"
    _, _, pr, _ = loop_env
    pr.create_issue.assert_not_awaited()


def test_compute_baselines_median_and_recent_max(loop_env) -> None:
    loop = _loop(loop_env)
    runs = [
        {
            "databaseId": 10,
            "duration_s": 900,
            "createdAt": "2026-04-20T00:00:00Z",
            "conclusion": "success",
        },
        {
            "databaseId": 9,
            "duration_s": 310,
            "createdAt": "2026-04-19T00:00:00Z",
            "conclusion": "success",
        },
        {
            "databaseId": 8,
            "duration_s": 300,
            "createdAt": "2026-04-18T00:00:00Z",
            "conclusion": "success",
        },
        {
            "databaseId": 7,
            "duration_s": 320,
            "createdAt": "2026-04-17T00:00:00Z",
            "conclusion": "success",
        },
        {
            "databaseId": 6,
            "duration_s": 290,
            "createdAt": "2026-04-16T00:00:00Z",
            "conclusion": "success",
        },
        {
            "databaseId": 5,
            "duration_s": 315,
            "createdAt": "2026-04-15T00:00:00Z",
            "conclusion": "success",
        },
    ]
    current, baselines = loop._compute_baselines(runs)
    assert current["databaseId"] == 10
    assert baselines["recent_max"] == 320
    # Sorted others: 290, 300, 310, 315, 320 → median = 310.
    assert baselines["rolling_median"] == 310


def _history() -> list[dict]:
    """6 prior runs at 300s."""
    return [
        {
            "databaseId": i,
            "duration_s": 300,
            "createdAt": f"2026-04-{10 + i:02d}T00:00:00Z",
            "conclusion": "success",
            "url": f"u{i}",
        }
        for i in range(1, 7)
    ]


async def test_do_work_files_issue_on_median_signal(loop_env) -> None:
    loop = _loop(loop_env)
    runs = [
        {
            "databaseId": 99,
            "duration_s": 600,
            "createdAt": "2026-04-20T00:00:00Z",
            "conclusion": "success",
            "url": "u99",
        },
        *_history(),
    ]
    loop._fetch_recent_runs = AsyncMock(return_value=runs)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_job_breakdown = AsyncMock(return_value=[])
    loop._fetch_junit_tests = AsyncMock(return_value=[])
    stats = await loop._do_work()
    assert stats["filed"] >= 1
    _, _, pr, _ = loop_env
    title = pr.create_issue.await_args.args[0]
    assert "RC gate duration regression" in title
    labels = pr.create_issue.await_args.args[2]
    assert "hydraflow-find" in labels and "rc-duration-regression" in labels


async def test_do_work_skips_when_dedup_key_present(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"rc_budget:median", "rc_budget:spike"}
    loop = _loop(loop_env)
    runs = [
        {
            "databaseId": 99,
            "duration_s": 9000,
            "createdAt": "2026-04-20T00:00:00Z",
            "conclusion": "success",
            "url": "u",
        },
        *_history(),
    ]
    loop._fetch_recent_runs = AsyncMock(return_value=runs)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_job_breakdown = AsyncMock(return_value=[])
    loop._fetch_junit_tests = AsyncMock(return_value=[])
    stats = await loop._do_work()
    assert stats["filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_escalation_fires_after_three_attempts(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    state.inc_rc_budget_attempts.return_value = 3
    loop = _loop(loop_env)
    runs = [
        {
            "databaseId": 99,
            "duration_s": 9000,
            "createdAt": "2026-04-20T00:00:00Z",
            "conclusion": "success",
            "url": "u",
        },
        *_history(),
    ]
    loop._fetch_recent_runs = AsyncMock(return_value=runs)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_job_breakdown = AsyncMock(return_value=[])
    loop._fetch_junit_tests = AsyncMock(return_value=[])
    stats = await loop._do_work()
    assert stats["escalated"] >= 1
    assert any(
        "hitl-escalation" in call.args[2] and "rc-duration-stuck" in call.args[2]
        for call in pr.create_issue.await_args_list
    )


async def test_reconcile_closed_escalations_clears_dedup(loop_env, monkeypatch) -> None:
    """Closed `rc-duration-stuck` escalations clear their dedup key + counter.

    The read routes through ``PRPort.list_closed_issues_by_label`` (shared
    ``EscalationReconciler``) — never a raw ``gh`` subprocess (#9932). The
    ``create_subprocess_exec`` guard fails the test if the reconcile path
    escapes the MockWorld air-gap.
    """
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"rc_budget:median", "rc_budget:spike"}
    loop = _loop(loop_env)

    pr.list_closed_issues_by_label.return_value = [
        {
            "number": 9700,
            "title": (
                "HITL: RC gate duration regression (median) unresolved after 3 attempts"
            ),
            "body": "",
            "updated_at": "",
        }
    ]

    def _no_subprocess(*_args, **_kwargs):
        raise AssertionError("reconcile must route through the PRPort, not raw gh")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _no_subprocess)

    await loop._reconcile_closed_escalations()

    pr.list_closed_issues_by_label.assert_awaited_once_with(
        "rc-duration-stuck", limit=100
    )
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert "rc_budget:median" not in remaining
    assert "rc_budget:spike" in remaining
    state.clear_rc_budget_attempts.assert_called_once_with("median")


async def test_fetch_job_breakdown_sorts_and_caps_slowest_jobs(
    loop_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, state, pr, dedup = loop_env
    loop = _loop(loop_env)
    pr.get_workflow_run_jobs = AsyncMock(
        return_value=[
            {
                "name": f"job-{idx}",
                "conclusion": "success",
                "started_at": "2026-04-20T00:00:00Z",
                "completed_at": f"2026-04-20T00:{idx:02d}:00Z",
                "steps": [],
            }
            for idx in range(1, 13)
        ]
    )

    async def fake_subproc(*args, **kwargs):
        raise AssertionError("job breakdown must read the PRPort, not gh run view")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)

    result = await loop._fetch_job_breakdown({"databaseId": 123})

    assert [job["name"] for job in result[:3]] == ["job-12", "job-11", "job-10"]
    assert len(result) == 10
    assert result[0]["duration_s"] == 720
    pr.get_workflow_run_jobs.assert_awaited_once_with(123)


async def test_fetch_junit_tests_parses_and_caps_slowest_tests(
    loop_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _loop(loop_env)

    class _Proc:
        returncode = 0

        async def communicate(self):
            return (b"", b"")

    async def fake_subproc(*args, **kwargs):
        assert args[:4] == ("gh", "run", "download", "123")
        out_dir = Path(args[args.index("--dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        cases = "\n".join(
            f'<testcase classname="pkg.TestSuite" name="test_{idx}" time="{idx / 10}" />'
            for idx in range(1, 13)
        )
        (out_dir / "junit.xml").write_text(f"<testsuite>{cases}</testsuite>")
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)

    result = await loop._fetch_junit_tests({"databaseId": 123})

    assert result[:3] == [
        ("pkg.TestSuite.test_12", 1.2),
        ("pkg.TestSuite.test_11", 1.1),
        ("pkg.TestSuite.test_10", 1.0),
    ]
    assert len(result) == 10


async def test_regression_issue_body_includes_enrichment(loop_env) -> None:
    loop = _loop(loop_env)
    current = {
        "databaseId": 99,
        "duration_s": 900,
        "createdAt": "2026-04-20T00:00:00Z",
        "conclusion": "success",
        "url": "https://example/run/99",
    }
    previous_5 = [
        {
            "databaseId": 90,
            "duration_s": 300,
            "createdAt": "2026-04-19T00:00:00Z",
        }
    ]

    await loop._file_regression_issue(
        kind="spike",
        current=current,
        baseline_s=300,
        baselines={"rolling_median": 300, "recent_max": 300},
        previous_5=previous_5,
        jobs=[{"name": "scenario-loop", "duration_s": 420}],
        junit_tests=[("tests.scenarios.test_rc_budget.test_spike", 12.345)],
    )

    _, _, pr, _ = loop_env
    title, body, labels = pr.create_issue.await_args.args
    assert title == "RC gate duration regression: 900s vs 300s (spike)"
    assert labels == ["hydraflow-find", "rc-duration-regression"]
    assert "Run [99](https://example/run/99) took **900s**" in body
    assert "- `scenario-loop` — 420s" in body
    assert "- `tests.scenarios.test_rc_budget.test_spike` — 12.35s" in body
    assert "- run 90 (2026-04-19T00:00:00Z) — 300s" in body


async def test_kill_switch_short_circuits_run(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: name != "rc_budget",
    )
    loop = RCBudgetLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        deps=deps,
        github_cache=_gh_cache(),
    )
    # Belt + braces: a guarded _do_work must not be entered by the dispatcher.
    loop._fetch_recent_runs = AsyncMock(side_effect=AssertionError("must not run"))

    # Drive one cycle via the public run loop; tick the stop event after.
    async def driver():
        await asyncio.sleep(0.01)
        stop.set()
        loop.trigger()

    await asyncio.gather(loop.run(), driver())
    pr.create_issue.assert_not_awaited()


async def test_both_signals_fire_concurrently(loop_env) -> None:
    loop = _loop(loop_env)
    # median=300, recent_max=320, current=1000 -> both trip.
    runs = [
        {
            "databaseId": 99,
            "duration_s": 1000,
            "createdAt": "2026-04-20T00:00:00Z",
            "conclusion": "success",
            "url": "u",
        },
        *[
            {
                "databaseId": i,
                "duration_s": (300 if i != 5 else 320),
                "createdAt": f"2026-04-{10 + i:02d}T00:00:00Z",
                "conclusion": "success",
                "url": f"u{i}",
            }
            for i in range(1, 7)
        ],
    ]
    loop._fetch_recent_runs = AsyncMock(return_value=runs)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_job_breakdown = AsyncMock(return_value=[])
    loop._fetch_junit_tests = AsyncMock(return_value=[])
    stats = await loop._do_work()
    assert stats["filed"] == 2
    _, _, _, dedup = loop_env
    assert dedup.set_all.call_count == 2


@pytest.mark.asyncio
async def test_kill_switch_short_circuits_do_work(loop_env) -> None:
    """Disabled kill-switch → _do_work returns `disabled` (ADR-0049, in-body check)."""
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: name != "rc_budget",
    )
    loop = RCBudgetLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        deps=deps,
        github_cache=_gh_cache(),
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_recent_runs = AsyncMock(
        side_effect=AssertionError("must not run when disabled")
    )
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}
    loop._reconcile_closed_escalations.assert_not_awaited()
    pr.create_issue.assert_not_awaited()
