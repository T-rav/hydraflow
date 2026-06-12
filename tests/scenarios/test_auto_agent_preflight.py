"""Full-loop scenario tests for AutoAgentPreflightLoop (spec §8.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from preflight.agent import PreflightSpawn
from tests.helpers import make_bg_loop_deps


def _make_loop(tmp_path, **overrides):
    deps = make_bg_loop_deps(tmp_path, **overrides)
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=0)
    state.bump_auto_agent_attempts = MagicMock(return_value=1)
    state.clear_auto_agent_attempts = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.add_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.get_escalation_context = MagicMock(return_value=None)
    pr = AsyncMock()
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    audit = MagicMock()
    audit.append = MagicMock()
    audit.entries_for_issue = MagicMock(return_value=[])
    loop = AutoAgentPreflightLoop(
        config=deps.config,
        state=state,
        pr_manager=pr,
        wiki_store=None,
        audit_store=audit,
        deps=deps.loop_deps,
    )
    return loop, state, pr, audit


def _stub_spawn(loop, output: str, *, cost: float = 1.0, crashed: bool = False):
    async def _spawn(prompt: str, worktree_path: str) -> PreflightSpawn:
        return PreflightSpawn(
            process=None,
            output_text=output,
            cost_usd=cost,
            tokens=100,
            crashed=crashed,
        )

    loop._build_spawn_fn = lambda issue: _spawn


@pytest.mark.asyncio
async def test_flaky_test_resolved(tmp_path: Path) -> None:
    loop, _state, pr, _audit = _make_loop(tmp_path)
    pr.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 1,
                "body": "x",
                "labels": [
                    {"name": "hitl-escalation"},
                    {"name": "flaky-test-stuck"},
                ],
            },
        ]
    )
    _stub_spawn(
        loop,
        "<status>resolved</status><pr_url>https://x/pr/1</pr_url><diagnosis>fixed</diagnosis>",
    )
    result = await loop._do_work()
    assert result["result_status"] == "resolved"
    # `resolved` removes hitl-escalation + human-required + sub-label
    # (singular remove_label called once per label).
    pr.remove_label.assert_any_await(1, "hitl-escalation")
    pr.remove_label.assert_any_await(1, "human-required")
    pr.remove_label.assert_any_await(1, "flaky-test-stuck")


@pytest.mark.asyncio
async def test_low_confidence_bail_retries_without_paging_human(tmp_path: Path) -> None:
    # A `needs_human` bail with a transient / low-confidence signal must NOT
    # page a human — the loop converges via `retry`, leaving the issue eligible
    # for the next cycle (ADR-0084 pillar B; the #9275 failure mode).
    loop, _state, pr, _audit = _make_loop(tmp_path)
    pr.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 1,
                "body": "x",
                "labels": [
                    {"name": "hitl-escalation"},
                    {"name": "flaky-test-stuck"},
                ],
            },
        ]
    )
    _stub_spawn(
        loop,
        "<status>needs_human</status><confidence>low</confidence>"
        "<blocked_reason>insufficient_context</blocked_reason>"
        "<diagnosis>need more context</diagnosis>",
    )
    result = await loop._do_work()
    assert result["result_status"] == "retry"
    # No human escalation: nothing the loop added may include human-required.
    for call in pr.add_labels.await_args_list:
        assert "human-required" not in call.args[1]


@pytest.mark.asyncio
async def test_subprocess_fatal(tmp_path: Path) -> None:
    loop, _state, pr, _audit = _make_loop(tmp_path)
    pr.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 1,
                "body": "x",
                "labels": [
                    {"name": "hitl-escalation"},
                    {"name": "flaky-test-stuck"},
                ],
            },
        ]
    )
    _stub_spawn(loop, "partial output", cost=0.5, crashed=True)
    result = await loop._do_work()
    assert result["result_status"] == "fatal"
    pr.add_labels.assert_awaited_with(1, ["human-required", "auto-agent-fatal"])


@pytest.mark.asyncio
async def test_resolved_without_pr_url_demotes_to_pr_failed(tmp_path: Path) -> None:
    loop, _state, pr, _audit = _make_loop(tmp_path)
    pr.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 1,
                "body": "x",
                "labels": [
                    {"name": "hitl-escalation"},
                    {"name": "flaky-test-stuck"},
                ],
            },
        ]
    )
    _stub_spawn(loop, "<status>resolved</status><diagnosis>fixed</diagnosis>")
    result = await loop._do_work()
    # Spec §2.2: agent claimed `resolved` but produced no PR — the loop demotes
    # this to `pr_failed` so a human picks up the cleanup. The diagnosis is
    # still preserved in the audit + comment.
    assert result["result_status"] == "pr_failed"
    pr.add_labels.assert_awaited_with(1, ["human-required", "auto-agent-pr-failed"])


@pytest.mark.asyncio
async def test_third_attempt_marks_exhausted(tmp_path: Path) -> None:
    loop, state, pr, _audit = _make_loop(tmp_path)
    # get_auto_agent_attempts is called twice in the pipeline:
    # once before bump (returns 2), once in apply_decision after bump (returns 3)
    state.get_auto_agent_attempts = MagicMock(side_effect=[2, 3])
    state.bump_auto_agent_attempts = MagicMock(return_value=3)
    pr.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 1,
                "body": "x",
                "labels": [
                    {"name": "hitl-escalation"},
                    {"name": "flaky-test-stuck"},
                ],
            },
        ]
    )
    _stub_spawn(loop, "<status>needs_human</status><diagnosis>cannot fix</diagnosis>")
    await loop._do_work()
    pr.add_labels.assert_awaited_with(1, ["human-required", "auto-agent-exhausted"])


@pytest.mark.asyncio
async def test_principles_stuck_bypassed(tmp_path: Path) -> None:
    loop, _state, pr, _audit = _make_loop(tmp_path)
    pr.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 1,
                "body": "x",
                "labels": [
                    {"name": "hitl-escalation"},
                    {"name": "principles-stuck"},
                ],
            },
        ]
    )
    spawn_called = False

    async def _never_spawn(*a, **kw):
        nonlocal spawn_called
        spawn_called = True
        raise AssertionError("agent must not be spawned for deny-list sub-labels")

    loop._build_spawn_fn = lambda issue: _never_spawn
    result = await loop._do_work()
    assert result["result_status"] == "skipped_deny_list"
    pr.add_labels.assert_awaited_with(1, ["human-required"])
    assert spawn_called is False


@pytest.mark.asyncio
async def test_credit_exhaustion_refunds_attempt_and_reraises(tmp_path: Path) -> None:
    # A session/credit limit mid-spawn is a transient (ADR-0084): refund the
    # attempt and re-raise to stop the cycle — never strand the issue or burn
    # its budget toward a wrongful human-required.
    from subprocess_util import CreditExhaustedError  # noqa: PLC0415

    loop, state, pr, _audit = _make_loop(tmp_path)
    state.refund_auto_agent_attempt = MagicMock(return_value=0)
    pr.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 1,
                "body": "x",
                "labels": [
                    {"name": "hitl-escalation"},
                    {"name": "flaky-test-stuck"},
                ],
            },
        ]
    )

    async def _spawn(prompt: str, worktree_path: str):
        raise CreditExhaustedError("You've hit your session limit")

    loop._build_spawn_fn = lambda issue: _spawn

    with pytest.raises(CreditExhaustedError):
        await loop._do_work()

    state.refund_auto_agent_attempt.assert_called_once_with(1)
    # No human escalation — the issue stays eligible for retry when budget returns.
    for call in pr.add_labels.await_args_list:
        assert "human-required" not in call.args[1]


@pytest.mark.asyncio
async def test_resolved_diagnose_failed_routes_back_to_review(tmp_path: Path) -> None:
    # A diagnose-failed issue (routed from the diagnostic loop) that the
    # Auto-Agent resolves must re-enter review, not linger in the HITL queue.
    loop, _state, pr, _audit = _make_loop(tmp_path)
    pr.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 1,
                "body": "x",
                "labels": [
                    {"name": "hitl-escalation"},
                    {"name": "diagnose-failed"},
                ],
            },
        ]
    )
    _stub_spawn(
        loop,
        "<status>resolved</status><pr_url>https://x/pr/1</pr_url>"
        "<confidence>high</confidence><diagnosis>applied review fixes</diagnosis>",
    )

    result = await loop._do_work()

    assert result["result_status"] == "resolved"
    pr.swap_pipeline_labels.assert_awaited_once_with(1, loop._config.review_label[0])
