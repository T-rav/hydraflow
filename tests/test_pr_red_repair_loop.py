"""PrRedRepairLoop unit tests (#10027: infra-flake retrier + real-red dispatch).

Covers the pure functions (settled-red predicate incl. the pinned
mid-rerun stale-conclusion trap, infra-flake classifier, latest-run
selection, dispatch-ownership predicate) and the loop's ``_do_work``
orchestration: Phase 1's bounded rerun / attempt-cap escalation / rollup
auto-close, and Phase 2's real-red auto-agent dispatch, its two
guardrails (double-writer via ``review_label``, human-PR ownership via
``is_bot`` + ``auto-fix-ok``), its own bounded attempt cap +
``hydraflow-hitl`` give-up, and the log-pointer comment dedup.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pr_red_repair_loop import (
    REASON_CANCELLED,
    REASON_SETUP_ACTION,
    REASON_VANISHED_LOGS,
    REASON_ZERO_FAILED_STEPS,
    PrRedRepairLoop,
    classify_infra_flake_job,
    classify_run_infra_flake,
    is_settled_red,
    select_latest_runs,
    should_dispatch_auto_agent,
)
from subprocess_util import CreditExhaustedError
from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# is_settled_red — the load-bearing predicate
# ---------------------------------------------------------------------------


class TestIsSettledRed:
    def test_empty_rollup_is_not_settled(self) -> None:
        assert is_settled_red([]) is False

    @pytest.mark.parametrize(
        ("rollup", "expected"),
        [
            pytest.param(
                [
                    {"status": "completed", "conclusion": "success"},
                    {"status": "completed", "conclusion": "success"},
                ],
                False,
                id="test_all_success_is_not_red",
            ),
            pytest.param(
                [
                    {"status": "completed", "conclusion": "failure"},
                    {"status": "completed", "conclusion": "success"},
                ],
                True,
                id="test_completed_with_failure_is_settled_red",
            ),
            # Failures present AND something still queued/in-progress -> not settled.
            pytest.param(
                [
                    {"status": "completed", "conclusion": "failure"},
                    {"status": "in_progress", "conclusion": ""},
                ],
                False,
                id="test_pending_entry_is_never_settled_even_with_a_failure",
            ),
            # PINNED (#10027): after ``gh run rerun --failed``, an entry can keep
            # reporting its OLD (pre-rerun) FAILURE conclusion while its status has
            # already flipped back to in_progress for the new attempt. The predicate
            # must NOT fire settled-red in this window — this is the exact trap hit
            # twice during the 2026-07-19/20 overnight session (stale rollup
            # mid-rerun).
            pytest.param(
                [
                    # Stale: still says FAILURE from the pre-rerun attempt, but the
                    # job is actually running again.
                    {"status": "in_progress", "conclusion": "failure"},
                    {"status": "completed", "conclusion": "success"},
                ],
                False,
                id="test_mid_rerun_stale_conclusion_trap_pinned",
            ),
            # Once the reran job actually finishes (status flips to completed), a
            # genuine still-red outcome DOES fire settled-red again.
            pytest.param(
                [
                    {"status": "completed", "conclusion": "failure"},
                    {"status": "completed", "conclusion": "success"},
                ],
                True,
                id="test_after_rerun_completes_red_again_is_settled_red",
            ),
        ],
    )
    def test_settled_red_verdict(
        self, rollup: list[dict[str, str]], expected: bool
    ) -> None:
        assert is_settled_red(rollup) is expected

    def test_queued_only_is_not_settled(self) -> None:
        rollup = [{"status": "queued", "conclusion": ""}]
        assert is_settled_red(rollup) is False

    def test_missing_status_is_treated_as_not_settled(self) -> None:
        """Fail-safe: an entry with no status at all never counts as settled."""
        rollup = [{"conclusion": "failure"}]
        assert is_settled_red(rollup) is False

    def test_cancelled_counts_as_failure(self) -> None:
        rollup = [{"status": "completed", "conclusion": "cancelled"}]
        assert is_settled_red(rollup) is True


# ---------------------------------------------------------------------------
# classify_infra_flake_job — the four proven signals
# ---------------------------------------------------------------------------


class TestClassifyInfraFlakeJob:
    def test_cancelled_job(self) -> None:
        job = {"conclusion": "cancelled", "steps": []}
        assert classify_infra_flake_job(job) == REASON_CANCELLED

    def test_zero_failed_steps(self) -> None:
        job = {
            "conclusion": "failure",
            "steps": [
                {"name": "Checkout", "conclusion": "success"},
                {"name": "Run tests", "conclusion": "success"},
            ],
        }
        assert classify_infra_flake_job(job) == REASON_ZERO_FAILED_STEPS

    def test_failure_with_no_steps_at_all(self) -> None:
        job = {"conclusion": "failure", "steps": []}
        assert classify_infra_flake_job(job) == REASON_ZERO_FAILED_STEPS

    def test_failed_setup_uv_step(self) -> None:
        job = {
            "conclusion": "failure",
            "steps": [
                {"name": "Run astral-sh/setup-uv@v3", "conclusion": "failure"},
            ],
        }
        assert classify_infra_flake_job(job) == REASON_SETUP_ACTION

    def test_failed_checkout_step(self) -> None:
        job = {
            "conclusion": "failure",
            "steps": [{"name": "Run actions/checkout@v4", "conclusion": "failure"}],
        }
        assert classify_infra_flake_job(job) == REASON_SETUP_ACTION

    def test_failed_set_up_job_step(self) -> None:
        job = {
            "conclusion": "failure",
            "steps": [{"name": "Set up job", "conclusion": "failure"}],
        }
        assert classify_infra_flake_job(job) == REASON_SETUP_ACTION

    def test_vanished_logs(self) -> None:
        job = {
            "conclusion": "failure",
            "steps": [{"name": "Run pytest", "conclusion": "failure"}],
        }
        assert (
            classify_infra_flake_job(job, log_text="Error: log not found")
            == REASON_VANISHED_LOGS
        )

    def test_real_red_failed_test_step_is_not_a_flake(self) -> None:
        job = {
            "conclusion": "failure",
            "steps": [{"name": "Run pytest", "conclusion": "failure"}],
        }
        assert classify_infra_flake_job(job) is None

    def test_passing_job_is_not_a_flake(self) -> None:
        job = {"conclusion": "success", "steps": []}
        assert classify_infra_flake_job(job) is None

    def test_setup_step_check_precedes_generic_failure_when_both_present(
        self,
    ) -> None:
        """A failed setup step among other failed steps still classifies."""
        job = {
            "conclusion": "failure",
            "steps": [
                {"name": "Run astral-sh/setup-uv@v3", "conclusion": "failure"},
                {"name": "Run pytest", "conclusion": "skipped"},
            ],
        }
        assert classify_infra_flake_job(job) == REASON_SETUP_ACTION


# ---------------------------------------------------------------------------
# classify_run_infra_flake — whole-run classification (all-or-nothing)
# ---------------------------------------------------------------------------


class TestClassifyRunInfraFlake:
    def test_empty_failing_jobs_is_none(self) -> None:
        assert classify_run_infra_flake([]) is None

    def test_all_flaky_jobs_classify(self) -> None:
        jobs = [
            {"conclusion": "cancelled", "steps": []},
            {"conclusion": "failure", "steps": []},
        ]
        assert classify_run_infra_flake(jobs) == REASON_CANCELLED

    def test_one_real_red_job_blocks_the_whole_run(self) -> None:
        """gh run rerun --failed reruns every failed job indiscriminately —
        if one failing job is a real regression, the whole run is left
        alone (Phase 2 territory), not just the flaky part."""
        jobs = [
            {"conclusion": "cancelled", "steps": []},
            {
                "conclusion": "failure",
                "steps": [{"name": "Run pytest", "conclusion": "failure"}],
            },
        ]
        assert classify_run_infra_flake(jobs) is None


# ---------------------------------------------------------------------------
# select_latest_runs
# ---------------------------------------------------------------------------


class TestSelectLatestRuns:
    def test_picks_newest_per_workflow(self) -> None:
        runs = [
            {
                "id": 1,
                "workflow": "CI",
                "pr_number": 42,
                "created_at": "2026-07-19T00:00:00Z",
            },
            {
                "id": 2,
                "workflow": "CI",
                "pr_number": 42,
                "created_at": "2026-07-20T00:00:00Z",
            },
            {
                "id": 3,
                "workflow": "Quality",
                "pr_number": 42,
                "created_at": "2026-07-19T00:00:00Z",
            },
        ]
        latest = select_latest_runs(runs, 42)
        assert latest["CI"]["id"] == 2
        assert latest["Quality"]["id"] == 3

    def test_filters_by_pr_number(self) -> None:
        runs = [
            {"id": 1, "workflow": "CI", "pr_number": 1, "created_at": "x"},
            {"id": 2, "workflow": "CI", "pr_number": 2, "created_at": "y"},
        ]
        latest = select_latest_runs(runs, 1)
        assert set(latest) == {"CI"}
        assert latest["CI"]["id"] == 1

    def test_no_runs_for_pr_returns_empty(self) -> None:
        assert select_latest_runs([], 42) == {}


# ---------------------------------------------------------------------------
# should_dispatch_auto_agent — Phase 2 ownership predicate
# ---------------------------------------------------------------------------


class TestShouldDispatchAutoAgent:
    def test_bot_authored_pr_always_dispatches(self) -> None:
        assert (
            should_dispatch_auto_agent(is_bot_author=True, has_auto_fix_ok_label=False)
            is True
        )

    def test_human_authored_pr_without_label_does_not_dispatch(self) -> None:
        assert (
            should_dispatch_auto_agent(is_bot_author=False, has_auto_fix_ok_label=False)
            is False
        )

    def test_human_authored_pr_with_auto_fix_ok_label_dispatches(self) -> None:
        assert (
            should_dispatch_auto_agent(is_bot_author=False, has_auto_fix_ok_label=True)
            is True
        )

    def test_bot_authored_pr_with_label_also_dispatches(self) -> None:
        """Redundant but harmless — both signals agree."""
        assert (
            should_dispatch_auto_agent(is_bot_author=True, has_auto_fix_ok_label=True)
            is True
        )


# ---------------------------------------------------------------------------
# PrRedRepairLoop — smoke + kill-switch
# ---------------------------------------------------------------------------


# Config fields absent from ConfigFactory.create's enumerated kwargs
# (mirrors test_gate_health_loop.py's ``object.__setattr__`` pattern for
# the frozen HydraFlowConfig model — the factory doesn't special-case
# every loop's own knobs).
_POST_CONSTRUCT_FIELDS = frozenset(
    {
        "pr_red_repair_loop_enabled",
        "pr_red_repair_interval",
        "pr_red_rerun_max_attempts",
        "pr_red_repair_dispatch_max_attempts",
        "pr_red_repair_dispatch_enabled",
    }
)


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    prs: object | None = None,
    state: object | None = None,
    runner: object | None = None,
    workspaces: object | None = None,
    human_pr_dedup: object | None = None,
    **config_overrides,
):
    config_overrides.setdefault("pr_red_repair_loop_enabled", True)
    post_construct = {
        k: config_overrides.pop(k)
        for k in list(config_overrides)
        if k in _POST_CONSTRUCT_FIELDS
    }
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, **config_overrides)
    for field, value in post_construct.items():
        object.__setattr__(deps.config, field, value)
    state = state if state is not None else MagicMock()
    loop = PrRedRepairLoop(
        config=deps.config,
        pr_manager=prs,
        state=state,
        deps=deps.loop_deps,
        runner=runner,
        workspaces=workspaces,
        human_pr_dedup=human_pr_dedup,
    )
    return loop, state


def _make_state_with_attempts(
    attempts: dict[str, int] | None = None,
    dispatch_attempts: dict[str, int] | None = None,
) -> MagicMock:
    state = MagicMock()
    counts = dict(attempts or {})
    dispatch_counts = dict(dispatch_attempts or {})

    def _get(pr_number: int) -> int:
        return int(counts.get(str(pr_number), 0))

    def _bump(pr_number: int) -> int:
        new = _get(pr_number) + 1
        counts[str(pr_number)] = new
        return new

    def _get_dispatch(pr_number: int) -> int:
        return int(dispatch_counts.get(str(pr_number), 0))

    def _bump_dispatch(pr_number: int) -> int:
        new = _get_dispatch(pr_number) + 1
        dispatch_counts[str(pr_number)] = new
        return new

    state.get_pr_red_rerun_attempts.side_effect = _get
    state.bump_pr_red_rerun_attempts.side_effect = _bump
    state.get_pr_red_dispatch_attempts.side_effect = _get_dispatch
    state.bump_pr_red_dispatch_attempts.side_effect = _bump_dispatch
    state.get_rollup_issue.return_value = None
    state.get_rollup_issue_keys.return_value = []
    state._counts = counts
    state._dispatch_counts = dispatch_counts
    return state


def _pr(number: int, branch: str = "feat/x", *, is_bot: bool = True) -> SimpleNamespace:
    return SimpleNamespace(pr=number, branch=branch, is_bot=is_bot)


def _cancelled_job(steps: list | None = None) -> dict:
    return {
        "name": "Tests",
        "status": "completed",
        "conclusion": "cancelled",
        "steps": steps or [],
    }


def _real_red_run(pr_number: int, run_id: int = 700) -> dict:
    return {
        "id": run_id,
        "workflow": "CI",
        "conclusion": "failure",
        "created_at": "2026-07-20T00:00:00Z",
        "pr_number": pr_number,
    }


def _real_red_jobs() -> list[dict]:
    return [
        {
            "name": "Tests",
            "status": "completed",
            "conclusion": "failure",
            "steps": [{"name": "Run pytest", "conclusion": "failure"}],
        }
    ]


def test_worker_name(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path)
    assert loop._worker_name == "pr_red_repair"


def test_default_interval(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, pr_red_repair_interval=123)
    assert loop._get_default_interval() == 123


@pytest.mark.asyncio
async def test_disabled_by_ui_kill_switch(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, enabled=False)
    assert await loop._do_work() == {"status": "disabled"}


@pytest.mark.asyncio
async def test_disabled_by_static_config(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, pr_red_repair_loop_enabled=False)
    assert await loop._do_work() == {"status": "config_disabled"}


@pytest.mark.asyncio
async def test_dry_run_is_a_noop(tmp_path: Path) -> None:
    loop, _ = _make_loop(tmp_path, dry_run=True)
    assert await loop._do_work() is None


@pytest.mark.asyncio
async def test_no_open_prs(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_all_open_prs.return_value = []
    loop, _ = _make_loop(tmp_path, prs=prs)
    result = await loop._do_work()
    assert result == {"status": "no_open_prs"}


@pytest.mark.asyncio
async def test_prs_unavailable_is_fail_soft(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_all_open_prs.side_effect = RuntimeError("gh boom")
    loop, _ = _make_loop(tmp_path, prs=prs)
    result = await loop._do_work()
    assert result == {"status": "prs_unavailable"}


@pytest.mark.asyncio
async def test_settled_red_infra_flake_triggers_bounded_rerun(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_all_open_prs.return_value = [_pr(42)]
    prs.list_workflow_runs.return_value = [
        {
            "id": 555,
            "workflow": "CI",
            "conclusion": "cancelled",
            "created_at": "2026-07-20T00:00:00Z",
            "pr_number": 42,
        }
    ]
    prs.get_workflow_run_jobs.return_value = [_cancelled_job()]
    prs.rerun_workflow_failed.return_value = True

    state = _make_state_with_attempts()
    loop, _ = _make_loop(tmp_path, prs=prs, state=state)

    result = await loop._do_work()

    prs.rerun_workflow_failed.assert_awaited_once_with(555)
    assert result["reran"] == 1
    assert result["escalated"] == 0
    assert state.get_pr_red_rerun_attempts(42) == 1


@pytest.mark.asyncio
async def test_real_red_is_left_untouched(tmp_path: Path) -> None:
    """A failed test step (not one of the four infra-flake signals) must
    never be rerun. With NO auto-agent runner wired, Phase 2 degrades to
    exactly Phase 1's original behavior: skipped, not rerun, not dispatched."""
    prs = AsyncMock()
    prs.list_all_open_prs.return_value = [_pr(42)]
    prs.list_workflow_runs.return_value = [
        {
            "id": 555,
            "workflow": "CI",
            "conclusion": "failure",
            "created_at": "2026-07-20T00:00:00Z",
            "pr_number": 42,
        }
    ]
    prs.get_workflow_run_jobs.return_value = [
        {
            "name": "Tests",
            "status": "completed",
            "conclusion": "failure",
            "steps": [{"name": "Run pytest", "conclusion": "failure"}],
        }
    ]
    prs.fetch_ci_failure_logs.return_value = ""

    state = _make_state_with_attempts()
    loop, _ = _make_loop(tmp_path, prs=prs, state=state)

    result = await loop._do_work()

    prs.rerun_workflow_failed.assert_not_called()
    assert result["skipped_real_red"] == 1
    assert result["reran"] == 0
    assert result["dispatched"] == 0
    assert result["commented_human_pr"] == 0


@pytest.mark.asyncio
async def test_budget_exhausted_escalates_via_rollup_issue(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_all_open_prs.return_value = [_pr(42)]
    prs.list_workflow_runs.return_value = [
        {
            "id": 555,
            "workflow": "CI",
            "conclusion": "cancelled",
            "created_at": "2026-07-20T00:00:00Z",
            "pr_number": 42,
        }
    ]
    prs.get_workflow_run_jobs.return_value = [_cancelled_job()]
    prs.create_issue.return_value = 9999

    # Attempts already at the (default) cap of 2.
    state = _make_state_with_attempts({"42": 2})
    loop, _ = _make_loop(tmp_path, prs=prs, state=state)

    result = await loop._do_work()

    prs.rerun_workflow_failed.assert_not_called()
    assert result["escalated"] == 1
    prs.create_issue.assert_awaited_once()
    title = prs.create_issue.await_args.args[0]
    assert "42" in title


@pytest.mark.asyncio
async def test_attempt_cap_is_configurable(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_all_open_prs.return_value = [_pr(42)]
    prs.list_workflow_runs.return_value = [
        {
            "id": 555,
            "workflow": "CI",
            "conclusion": "cancelled",
            "created_at": "2026-07-20T00:00:00Z",
            "pr_number": 42,
        }
    ]
    prs.get_workflow_run_jobs.return_value = [_cancelled_job()]
    prs.rerun_workflow_failed.return_value = True

    state = _make_state_with_attempts()
    loop, _ = _make_loop(tmp_path, prs=prs, state=state, pr_red_rerun_max_attempts=5)

    await loop._do_work()

    prs.rerun_workflow_failed.assert_awaited_once()
    assert state.get_pr_red_rerun_attempts(42) == 1


@pytest.mark.asyncio
async def test_mid_rerun_pending_pr_is_not_reran_again(tmp_path: Path) -> None:
    """The settled-red predicate protects the loop from double-firing
    while a rerun is still in flight: a job whose status is in_progress
    must never trigger another rerun this cycle."""
    prs = AsyncMock()
    prs.list_all_open_prs.return_value = [_pr(42)]
    prs.list_workflow_runs.return_value = [
        {
            "id": 555,
            "workflow": "CI",
            "conclusion": "failure",  # stale, from before the rerun
            "created_at": "2026-07-20T00:00:00Z",
            "pr_number": 42,
        }
    ]
    prs.get_workflow_run_jobs.return_value = [
        {
            "name": "Tests",
            "status": "in_progress",  # rerun attempt N+1 is running
            "conclusion": "cancelled",  # stale conclusion from attempt N
            "steps": [],
        }
    ]

    state = _make_state_with_attempts({"42": 1})
    loop, _ = _make_loop(tmp_path, prs=prs, state=state)

    result = await loop._do_work()

    prs.rerun_workflow_failed.assert_not_called()
    assert result["reran"] == 0
    assert result["escalated"] == 0


@pytest.mark.asyncio
async def test_resolved_pr_closes_its_tracked_rollup(tmp_path: Path) -> None:
    """Once a previously-escalated PR's CI is examined and no longer
    settled-red, its rollup issue auto-closes (#10022 discipline)."""
    prs = AsyncMock()
    prs.list_all_open_prs.return_value = [_pr(42)]
    prs.list_workflow_runs.return_value = [
        {
            "id": 555,
            "workflow": "CI",
            "conclusion": "success",
            "created_at": "2026-07-20T00:00:00Z",
            "pr_number": 42,
        }
    ]
    prs.get_workflow_run_jobs.return_value = [
        {"name": "Tests", "status": "completed", "conclusion": "success", "steps": []}
    ]
    prs.close_issue.return_value = True

    state = _make_state_with_attempts({"42": 2})
    state.get_rollup_issue_keys.return_value = ["pr_red_repair:42"]
    state.get_rollup_issue.return_value = {
        "issue_number": 9999,
        "content_hash": "abc",
    }

    loop, _ = _make_loop(tmp_path, prs=prs, state=state)

    result = await loop._do_work()

    prs.close_issue.assert_awaited_once_with(9999)
    assert result["closed_rollups"] == 1


@pytest.mark.asyncio
async def test_unexamined_tracked_pr_is_never_auto_closed(tmp_path: Path) -> None:
    """A tracked (escalated) PR with NO runs in this cycle's fetch window
    must stay open — resolution is never inferred from silence (the
    SecurityPatchLoop mass-close hazard)."""
    prs = AsyncMock()
    prs.list_all_open_prs.return_value = [_pr(42), _pr(7)]
    # Only PR #7 has runs in this window; #42 has none.
    prs.list_workflow_runs.return_value = [
        {
            "id": 1,
            "workflow": "CI",
            "conclusion": "success",
            "created_at": "2026-07-20T00:00:00Z",
            "pr_number": 7,
        }
    ]
    prs.get_workflow_run_jobs.return_value = [
        {"name": "Tests", "status": "completed", "conclusion": "success", "steps": []}
    ]

    state = _make_state_with_attempts({"42": 2})
    state.get_rollup_issue_keys.return_value = ["pr_red_repair:42"]

    loop, _ = _make_loop(tmp_path, prs=prs, state=state)

    result = await loop._do_work()

    prs.close_issue.assert_not_called()
    assert result["closed_rollups"] == 0


@pytest.mark.asyncio
async def test_closed_pr_rollup_is_reconciled(tmp_path: Path) -> None:
    """A tracked PR no longer present in the open-PR list (merged/closed)
    has its rollup closed even without fresh CI data."""
    prs = AsyncMock()
    prs.list_all_open_prs.return_value = [_pr(7)]
    prs.list_workflow_runs.return_value = [
        {
            "id": 1,
            "workflow": "CI",
            "conclusion": "success",
            "created_at": "2026-07-20T00:00:00Z",
            "pr_number": 7,
        }
    ]
    prs.get_workflow_run_jobs.return_value = [
        {"name": "Tests", "status": "completed", "conclusion": "success", "steps": []}
    ]
    prs.close_issue.return_value = True

    state = _make_state_with_attempts()
    state.get_rollup_issue_keys.return_value = ["pr_red_repair:42"]
    state.get_rollup_issue.return_value = {
        "issue_number": 8888,
        "content_hash": "abc",
    }

    loop, _ = _make_loop(tmp_path, prs=prs, state=state)

    result = await loop._do_work()

    prs.close_issue.assert_awaited_once_with(8888)
    assert result["closed_rollups"] == 1


@pytest.mark.asyncio
async def test_vanished_logs_signal_triggers_rerun(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_all_open_prs.return_value = [_pr(42)]
    prs.list_workflow_runs.return_value = [
        {
            "id": 555,
            "workflow": "Quality",
            "conclusion": "failure",
            "created_at": "2026-07-20T00:00:00Z",
            "pr_number": 42,
        }
    ]
    prs.get_workflow_run_jobs.return_value = [
        {
            "name": "quality",
            "status": "completed",
            "conclusion": "failure",
            "steps": [{"name": "Run make quality", "conclusion": "failure"}],
        }
    ]
    prs.fetch_ci_failure_logs.return_value = "Error: log not found"
    prs.rerun_workflow_failed.return_value = True

    state = _make_state_with_attempts()
    loop, _ = _make_loop(tmp_path, prs=prs, state=state)

    result = await loop._do_work()

    prs.rerun_workflow_failed.assert_awaited_once_with(555)
    assert result["reran"] == 1


# ---------------------------------------------------------------------------
# PrRedRepairLoop — Phase 2 (#10027): real-red auto-agent dispatch
# ---------------------------------------------------------------------------


def _dispatch_prs_mock(
    *, review_labels: set[int] | None = None, auto_fix_ok: set[int] | None = None
) -> AsyncMock:
    """Build the ``list_prs_by_label`` side effect for the two Phase 2 fetches."""
    review = review_labels or set()
    ok = auto_fix_ok or set()

    async def _by_label(label: str) -> list[SimpleNamespace]:
        if label == "hydraflow-review":
            return [SimpleNamespace(number=n) for n in review]
        if label == "auto-fix-ok":
            return [SimpleNamespace(number=n) for n in ok]
        return []

    prs = AsyncMock()
    prs.list_prs_by_label.side_effect = _by_label
    # AsyncMock auto-creates unconfigured attributes as AsyncMock too, so an
    # un-set ``get_pr_recent_commit_diffs`` returns another (unawaited)
    # AsyncMock rather than a string — default it to empty here so every
    # dispatch test doesn't have to remember to set it individually.
    prs.get_pr_recent_commit_diffs.return_value = ""
    return prs


@pytest.mark.asyncio
async def test_real_red_bot_pr_dispatches_auto_agent(tmp_path: Path) -> None:
    """A bot-authored PR's real red gets dispatched to the auto-agent."""
    prs = _dispatch_prs_mock()
    prs.list_all_open_prs.return_value = [_pr(42, is_bot=True)]
    prs.list_workflow_runs.return_value = [_real_red_run(42)]
    prs.get_workflow_run_jobs.return_value = _real_red_jobs()
    prs.fetch_ci_failure_logs.return_value = "FAILED tests/test_thing.py::test_x"
    prs.get_pr_recent_commit_diffs.return_value = "diff --git a/x.py b/x.py\n+bug"

    state = _make_state_with_attempts()
    runner = MagicMock()
    runner.run = AsyncMock(return_value=SimpleNamespace(crashed=False))
    workspaces = MagicMock()
    resolved = tmp_path / "worktrees" / "issue-42"
    resolved.mkdir(parents=True)
    workspaces.create = AsyncMock(return_value=resolved)

    loop, _ = _make_loop(
        tmp_path, prs=prs, state=state, runner=runner, workspaces=workspaces
    )

    result = await loop._do_work()

    assert result["dispatched"] == 1
    assert result["skipped_real_red"] == 0
    assert result["commented_human_pr"] == 0
    runner.run.assert_awaited_once()
    assert state.get_pr_red_dispatch_attempts(42) == 1

    kwargs = runner.run.await_args.kwargs
    assert kwargs["worktree_path"] == str(resolved)
    assert kwargs["issue_number"] == 42
    assert "FAILED tests/test_thing.py::test_x" in kwargs["prompt"]
    assert "diff --git a/x.py b/x.py" in kwargs["prompt"]
    assert "{CI_FAILURE_LOG}" not in kwargs["prompt"]
    assert "{RECENT_COMMIT_DIFFS}" not in kwargs["prompt"]


@pytest.mark.asyncio
async def test_infra_flake_still_reruns_when_runner_is_wired(tmp_path: Path) -> None:
    """Wiring Phase 2 must not change Phase 1's infra-flake path at all."""
    prs = _dispatch_prs_mock()
    prs.list_all_open_prs.return_value = [_pr(42)]
    prs.list_workflow_runs.return_value = [
        {
            "id": 555,
            "workflow": "CI",
            "conclusion": "cancelled",
            "created_at": "2026-07-20T00:00:00Z",
            "pr_number": 42,
        }
    ]
    prs.get_workflow_run_jobs.return_value = [_cancelled_job()]
    prs.rerun_workflow_failed.return_value = True

    state = _make_state_with_attempts()
    runner = MagicMock()
    runner.run = AsyncMock()

    loop, _ = _make_loop(tmp_path, prs=prs, state=state, runner=runner)

    result = await loop._do_work()

    prs.rerun_workflow_failed.assert_awaited_once_with(555)
    assert result["reran"] == 1
    runner.run.assert_not_awaited()
    assert result["dispatched"] == 0


@pytest.mark.asyncio
async def test_review_labeled_pr_skips_dispatch_double_writer_guard(
    tmp_path: Path,
) -> None:
    """A PR under active review (double-writer risk) is never dispatched to."""
    prs = _dispatch_prs_mock(review_labels={42})
    prs.list_all_open_prs.return_value = [_pr(42, is_bot=True)]
    prs.list_workflow_runs.return_value = [_real_red_run(42)]
    prs.get_workflow_run_jobs.return_value = _real_red_jobs()
    prs.fetch_ci_failure_logs.return_value = ""

    state = _make_state_with_attempts()
    runner = MagicMock()
    runner.run = AsyncMock()

    loop, _ = _make_loop(tmp_path, prs=prs, state=state, runner=runner)

    result = await loop._do_work()

    runner.run.assert_not_awaited()
    assert result["dispatched"] == 0
    assert result["skipped_external_activity"] == 1
    assert result["skipped_real_red"] == 1
    # No attempt consumed while blocked by the guardrail.
    assert state.get_pr_red_dispatch_attempts(42) == 0


@pytest.mark.asyncio
async def test_human_authored_pr_gets_one_comment_not_dispatch(tmp_path: Path) -> None:
    """A human-authored PR without the opt-in label gets a comment, not a push."""
    prs = _dispatch_prs_mock()
    prs.list_all_open_prs.return_value = [_pr(42, is_bot=False)]
    prs.list_workflow_runs.return_value = [_real_red_run(42)]
    prs.get_workflow_run_jobs.return_value = _real_red_jobs()
    prs.fetch_ci_failure_logs.return_value = "AssertionError: boom"
    prs.post_pr_comment.return_value = None

    state = _make_state_with_attempts()
    runner = MagicMock()
    runner.run = AsyncMock()

    loop, _ = _make_loop(tmp_path, prs=prs, state=state, runner=runner)

    result = await loop._do_work()

    runner.run.assert_not_awaited()
    assert result["dispatched"] == 0
    assert result["commented_human_pr"] == 1
    assert state.get_pr_red_dispatch_attempts(42) == 0
    prs.post_pr_comment.assert_awaited_once()
    pr_number, body = prs.post_pr_comment.await_args.args
    assert pr_number == 42
    assert "auto-fix-ok" in body
    assert "AssertionError: boom" in body


@pytest.mark.asyncio
async def test_human_authored_pr_with_auto_fix_ok_label_dispatches(
    tmp_path: Path,
) -> None:
    """The auto-fix-ok opt-in label routes a human PR back to dispatch."""
    prs = _dispatch_prs_mock(auto_fix_ok={42})
    prs.list_all_open_prs.return_value = [_pr(42, is_bot=False)]
    prs.list_workflow_runs.return_value = [_real_red_run(42)]
    prs.get_workflow_run_jobs.return_value = _real_red_jobs()
    prs.fetch_ci_failure_logs.return_value = ""
    prs.get_pr_recent_commit_diffs.return_value = ""

    state = _make_state_with_attempts()
    runner = MagicMock()
    runner.run = AsyncMock(return_value=SimpleNamespace(crashed=False))

    loop, _ = _make_loop(tmp_path, prs=prs, state=state, runner=runner)

    result = await loop._do_work()

    runner.run.assert_awaited_once()
    assert result["dispatched"] == 1
    assert result["commented_human_pr"] == 0
    prs.post_pr_comment.assert_not_called()


@pytest.mark.asyncio
async def test_human_pr_comment_is_deduped_across_cycles(tmp_path: Path) -> None:
    """The log-pointer comment posts at most once while the PR stays real-red."""
    prs = _dispatch_prs_mock()
    prs.list_all_open_prs.return_value = [_pr(42, is_bot=False)]
    prs.list_workflow_runs.return_value = [_real_red_run(42)]
    prs.get_workflow_run_jobs.return_value = _real_red_jobs()
    prs.fetch_ci_failure_logs.return_value = "same failure both cycles"

    state = _make_state_with_attempts()
    runner = MagicMock()
    runner.run = AsyncMock()

    loop, _ = _make_loop(tmp_path, prs=prs, state=state, runner=runner)

    result_1 = await loop._do_work()
    result_2 = await loop._do_work()

    assert result_1["commented_human_pr"] == 1
    assert result_2["commented_human_pr"] == 0
    prs.post_pr_comment.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_attempt_cap_exhausted_gives_up_to_hitl_label(
    tmp_path: Path,
) -> None:
    """Once the dispatch cap is spent, the PR is labeled hydraflow-hitl instead."""
    prs = _dispatch_prs_mock()
    prs.list_all_open_prs.return_value = [_pr(42, is_bot=True)]
    prs.list_workflow_runs.return_value = [_real_red_run(42)]
    prs.get_workflow_run_jobs.return_value = _real_red_jobs()
    prs.fetch_ci_failure_logs.return_value = ""
    prs.add_pr_labels.return_value = None

    # Dispatch attempts already at the (default) cap of 2.
    state = _make_state_with_attempts(dispatch_attempts={"42": 2})
    runner = MagicMock()
    runner.run = AsyncMock()

    loop, _ = _make_loop(tmp_path, prs=prs, state=state, runner=runner)

    result = await loop._do_work()

    runner.run.assert_not_awaited()
    assert result["dispatch_escalated"] == 1
    assert result["dispatched"] == 0
    prs.add_pr_labels.assert_awaited_once_with(42, ["hydraflow-hitl"])


@pytest.mark.asyncio
async def test_dispatch_disabled_config_falls_back_to_phase1_only(
    tmp_path: Path,
) -> None:
    """The dark-launch gate suppresses BOTH dispatch and the human-PR comment."""
    prs = _dispatch_prs_mock()
    prs.list_all_open_prs.return_value = [_pr(42, is_bot=True)]
    prs.list_workflow_runs.return_value = [_real_red_run(42)]
    prs.get_workflow_run_jobs.return_value = _real_red_jobs()
    prs.fetch_ci_failure_logs.return_value = ""

    state = _make_state_with_attempts()
    runner = MagicMock()
    runner.run = AsyncMock()

    loop, _ = _make_loop(
        tmp_path,
        prs=prs,
        state=state,
        runner=runner,
        pr_red_repair_dispatch_enabled=False,
    )

    result = await loop._do_work()

    runner.run.assert_not_awaited()
    prs.post_pr_comment.assert_not_called()
    assert result["dispatched"] == 0
    assert result["commented_human_pr"] == 0
    assert result["skipped_real_red"] == 1


@pytest.mark.asyncio
async def test_dispatch_crashed_outcome_counts_separately(tmp_path: Path) -> None:
    prs = _dispatch_prs_mock()
    prs.list_all_open_prs.return_value = [_pr(42, is_bot=True)]
    prs.list_workflow_runs.return_value = [_real_red_run(42)]
    prs.get_workflow_run_jobs.return_value = _real_red_jobs()
    prs.fetch_ci_failure_logs.return_value = ""

    state = _make_state_with_attempts()
    runner = MagicMock()
    runner.run = AsyncMock(return_value=SimpleNamespace(crashed=True))

    loop, _ = _make_loop(tmp_path, prs=prs, state=state, runner=runner)

    result = await loop._do_work()

    assert result["dispatch_crashed"] == 1
    assert result["dispatched"] == 0
    # The attempt still counts toward the cap even though it crashed.
    assert state.get_pr_red_dispatch_attempts(42) == 1


@pytest.mark.asyncio
async def test_credit_exhausted_propagates_from_dispatch(tmp_path: Path) -> None:
    """CreditExhaustedError from the auto-agent must reach BaseBackgroundLoop,
    never be swallowed by the loop's own broad except (dark-factory §2.2)."""
    prs = _dispatch_prs_mock()
    prs.list_all_open_prs.return_value = [_pr(42, is_bot=True)]
    prs.list_workflow_runs.return_value = [_real_red_run(42)]
    prs.get_workflow_run_jobs.return_value = _real_red_jobs()
    prs.fetch_ci_failure_logs.return_value = ""

    state = _make_state_with_attempts()
    runner = MagicMock()
    runner.run = AsyncMock(side_effect=CreditExhaustedError("out of credits"))

    loop, _ = _make_loop(tmp_path, prs=prs, state=state, runner=runner)

    with pytest.raises(CreditExhaustedError):
        await loop._do_work()


@pytest.mark.asyncio
async def test_dispatch_falls_back_to_repo_root_without_workspace_port(
    tmp_path: Path,
) -> None:
    """With no WorkspacePort wired the cwd degrades to repo_root — still a
    real dispatch, matching SandboxFailureFixerLoop's own fallback."""
    prs = _dispatch_prs_mock()
    prs.list_all_open_prs.return_value = [_pr(42, is_bot=True)]
    prs.list_workflow_runs.return_value = [_real_red_run(42)]
    prs.get_workflow_run_jobs.return_value = _real_red_jobs()
    prs.fetch_ci_failure_logs.return_value = ""

    state = _make_state_with_attempts()
    runner = MagicMock()
    runner.run = AsyncMock(return_value=SimpleNamespace(crashed=False))

    loop, _ = _make_loop(tmp_path, prs=prs, state=state, runner=runner)

    result = await loop._do_work()

    assert result["dispatched"] == 1
    kwargs = runner.run.await_args.kwargs
    assert kwargs["worktree_path"] == str(loop._config.repo_root)
