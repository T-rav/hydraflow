"""Tests for RCBudgetLoop (spec §4.8)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from rc_budget_loop import RCBudgetLoop


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


def test_compute_baselines_excludes_gate_only_runs(loop_env) -> None:
    """Gate-only (should_run=false) runs must not pollute median/spike baseline.

    Regression for #10254: schedule-triggered ticks with no open ``rc/*`` PR
    skip every suite job, so the run finishes in a few seconds. Those near-zero
    ``gate_only`` runs used to drag the rolling median + recent-5 spike window
    down (the #10216 "2729s vs 7s median" artifact). They must be excluded from
    the baseline population while the current run + full runs are preserved.
    """
    loop = _loop(loop_env)
    # Five near-zero gate-only runs, MORE RECENT than the real full runs so
    # that — without the fix — they would dominate the recent-5 spike window.
    gate_only = [
        {
            "databaseId": 90 - k,
            "duration_s": dur,
            "createdAt": f"2026-04-{29 - k:02d}T00:00:00Z",
            "conclusion": "success",
            "gate_only": True,
        }
        for k, dur in enumerate([7, 6, 8, 5, 9])
    ]
    full = [
        {
            "databaseId": 50 - k,
            "duration_s": dur,
            "createdAt": f"2026-04-{24 - k:02d}T00:00:00Z",
            "conclusion": "success",
            "gate_only": False,
        }
        for k, dur in enumerate([800, 810, 790, 820, 805])
    ]
    current = {
        "databaseId": 100,
        "duration_s": 1600,
        "createdAt": "2026-04-30T00:00:00Z",
        "conclusion": "success",
        "gate_only": False,
    }
    runs = [current, *gate_only, *full]

    resolved, baselines = loop._compute_baselines(runs)

    assert resolved["databaseId"] == 100  # current unchanged (newest)
    # Baseline built from the 5 full runs ONLY: [790, 800, 805, 810, 820].
    assert baselines["rolling_median"] == 805
    assert baselines["recent_max"] == 820  # not 9 (the gate-only max)


def test_jobs_indicate_gate_only_from_skipped_suite_jobs(loop_env) -> None:
    """Scenario/Browser jobs skipped == gate-only; any that ran == full run."""
    loop = _loop(loop_env)
    gate_only_jobs = [
        {"name": "Resolve RC PR", "conclusion": "success"},
        {"name": "Scenario Tests", "conclusion": "skipped"},
        {"name": "Browser Scenarios", "conclusion": "skipped"},
        {
            "name": "Trust Gate (adversarial corpus, fixture mode)",
            "conclusion": "skipped",
        },
    ]
    # Real #10216 shape: schedule-triggered FULL run — scenario ran, browser cancelled.
    full_jobs = [
        {"name": "Resolve RC PR", "conclusion": "success"},
        {"name": "Scenario Tests", "conclusion": "success"},
        {"name": "Browser Scenarios", "conclusion": "cancelled"},
    ]
    assert loop._jobs_indicate_gate_only(gate_only_jobs) is True
    assert loop._jobs_indicate_gate_only(full_jobs) is False
    # Unknown/empty shape → treat as full (never drop real data).
    assert loop._jobs_indicate_gate_only([]) is False


def test_classify_from_list_fields_pull_request(loop_env) -> None:
    """rc/* PR runs are always full; non-rc PR runs are always gate-only."""
    loop = _loop(loop_env)
    assert (
        loop._classify_from_list_fields(
            {"event": "pull_request", "headBranch": "rc/2026-07-22-1824"}
        )
        is False
    )
    assert (
        loop._classify_from_list_fields(
            {"event": "pull_request", "headBranch": "feature/x"}
        )
        is True
    )
    # schedule / workflow_dispatch → ambiguous, needs job inspection.
    assert (
        loop._classify_from_list_fields({"event": "schedule", "headBranch": "staging"})
        is None
    )


async def test_classify_gate_only_uses_jobs_and_caches(loop_env) -> None:
    """Ambiguous schedule runs are classified via jobs and cached per run id."""
    loop = _loop(loop_env)
    fetch = AsyncMock(
        return_value=[
            {"name": "Resolve RC PR", "conclusion": "success"},
            {"name": "Scenario Tests", "conclusion": "skipped"},
            {"name": "Browser Scenarios", "conclusion": "skipped"},
        ]
    )
    loop._fetch_run_jobs_raw = fetch
    run = {"databaseId": 555, "event": "schedule", "headBranch": "staging"}

    assert await loop._classify_gate_only(run) is True
    assert await loop._classify_gate_only(run) is True  # served from cache
    fetch.assert_awaited_once()  # only one job fetch despite two classifications


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
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"rc_budget:median", "rc_budget:spike"}
    loop = _loop(loop_env)

    class _P:
        returncode = 0

        async def communicate(self):
            return (
                b'[{"title": "HITL: RC gate duration regression (median) '
                b'unresolved after 3 attempts"}]',
                b"",
            )

    async def fake_subproc(*args, **kwargs):
        return _P()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)
    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert "rc_budget:median" not in remaining
    assert "rc_budget:spike" in remaining
    state.clear_rc_budget_attempts.assert_called_once_with("median")


async def test_fetch_job_breakdown_sorts_and_caps_slowest_jobs(
    loop_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _loop(loop_env)
    jobs = [
        {
            "name": f"job-{idx}",
            "startedAt": "2026-04-20T00:00:00Z",
            "completedAt": f"2026-04-20T00:{idx:02d}:00Z",
        }
        for idx in range(1, 13)
    ]

    class _Proc:
        returncode = 0

        async def communicate(self):
            return (json.dumps({"jobs": jobs}).encode(), b"")

    async def fake_subproc(*args, **kwargs):
        assert args[:4] == ("gh", "run", "view", "123")
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)

    result = await loop._fetch_job_breakdown({"databaseId": 123})

    assert [job["name"] for job in result[:3]] == ["job-12", "job-11", "job-10"]
    assert len(result) == 10
    assert result[0]["duration_s"] == 720


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
    loop = RCBudgetLoop(config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=deps)
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
    loop = RCBudgetLoop(config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=deps)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_recent_runs = AsyncMock(
        side_effect=AssertionError("must not run when disabled")
    )
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}
    loop._reconcile_closed_escalations.assert_not_awaited()
    pr.create_issue.assert_not_awaited()
