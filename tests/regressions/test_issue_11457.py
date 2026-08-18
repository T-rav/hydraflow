"""Regression pins for the branch-cut issue-state re-check (#11457).

Two PRs (#11443, #11451) were built against issues that had already been
fixed and closed by other work. The issue was genuinely open when the
work-picker selected it; between selection and branch-cut it was closed on
GitHub, and nothing re-validated issue state in that window — so the build
proceeded (agent spawn, quality run, wiki writes, a PR) against a resolved
issue and produced a duplicate PR. GitHub is the source of truth for issue
state (ADR-0041); the local cache is exactly what makes the picked Task
stale.

These tests pin the fix:

1. **Surface A — branch-cut gate.** A new ``issue-state`` flow node between
   ``no-progress-abort`` and ``build`` re-reads the issue's state from GitHub
   immediately before the actuator. ``COMPLETED`` / ``NOT_PLANNED`` ⇒ abandon
   before spending the build: no agent run, no worktree, no PR.
2. **Fail-open error path (load-bearing).** The Port read failing (GitHub
   hiccup, unreadable issue, an unconfigured mock returning a ``MagicMock``)
   must NEVER block a build — the gate only acts on a positive resolved
   read. Credit/auth exhaustion still propagates.
3. **Surface B — pre-PR gate.** The issue can also close DURING the build;
   ``open-pr`` re-checks before pushing/opening the duplicate PR.
4. **Abandon semantics.** No re-enqueue to ready, no label stripping — the
   issue is closed on GitHub, so ``IssueFetcher._is_open`` keeps it out of
   the next refresh and ``LabelDriftWatcherLoop`` reconciles stray labels
   (ADR-0088). The worker returns a terminal non-success ``WorkerResult``
   and the state records ``completed`` (a terminal, workspace-clearing
   status — NOT ``failed``, which retry sweepers target).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import PRInfoFactory, TaskFactory, WorkerResultFactory
from tests.helpers import make_implement_phase

# Stand-ins matching tests/regressions/test_issue_10682_p2_implement_flow.py:
# if the gate (buggily) lets a resolved issue through to ``build``, the agent
# hangs and the short ``wait_for`` trips instead of the suite.
HARD_TIMEOUT = 3600.0
TEST_GUARD_TIMEOUT = 5.0

BRANCH_CUT_AT = "branch-cut"


async def _success_result(issue, wt_path):
    """A successful build outcome routed for push (the open-pr precondition)."""
    return WorkerResultFactory.create(
        issue_number=issue.id, success=True, workspace_path=str(wt_path)
    )


# ---------------------------------------------------------------------------
# 1. Surface A — the branch-cut gate
# ---------------------------------------------------------------------------


async def test_resolved_issue_is_abandoned_before_branch_cut(config) -> None:
    """An issue closed between pick and branch-cut never reaches the build.

    The pick was legitimate (issue open at selection); by branch-cut time
    another PR has closed it as COMPLETED. The gate must abandon with no
    agent run, no worktree creation, and no PR — the duplicate-PR failure
    mode of #11457.
    """
    issue = TaskFactory.create()
    agent_called = False

    async def hanging_agent(issue, wt_path, branch, **_kwargs):
        nonlocal agent_called
        agent_called = True
        await asyncio.sleep(HARD_TIMEOUT)

    phase, mock_wt, mock_prs = make_implement_phase(
        config, [issue], agent_run=hanging_agent
    )
    mock_prs.get_issue_state = AsyncMock(return_value="COMPLETED")

    result = await asyncio.wait_for(
        phase._worker_inner(0, issue, "agent/issue-42"), timeout=TEST_GUARD_TIMEOUT
    )

    assert agent_called is False, "a resolved issue must never reach the build"
    mock_wt.create.assert_not_called()
    mock_prs.create_pr.assert_not_awaited()
    # Terminal, non-success WorkerResult — the slot returns without a PR.
    assert result.success is False
    assert result.pr_info is None
    assert "resolved" in (result.error or "").lower()
    assert BRANCH_CUT_AT in (result.error or "")
    # Terminal 'completed' status (workspace-clearing; NOT 'failed' — no
    # retry sweeper may pick a resolved issue back up).
    assert phase._state.to_dict()["processed_issues"].get("42") == "completed"


async def test_not_planned_close_also_abandons(config) -> None:
    """A duplicate/wontfix close (NOT_PLANNED) is just as resolved (#10025)."""
    issue = TaskFactory.create()
    agent_called = False

    async def hanging_agent(issue, wt_path, branch, **_kwargs):
        nonlocal agent_called
        agent_called = True
        await asyncio.sleep(HARD_TIMEOUT)

    phase, _, mock_prs = make_implement_phase(config, [issue], agent_run=hanging_agent)
    mock_prs.get_issue_state = AsyncMock(return_value="NOT_PLANNED")

    result = await asyncio.wait_for(
        phase._worker_inner(0, issue, "agent/issue-42"), timeout=TEST_GUARD_TIMEOUT
    )

    assert agent_called is False
    assert result.success is False
    assert "resolved" in (result.error or "").lower()


async def test_open_issue_still_builds(config) -> None:
    """Parity guard: an issue that is still OPEN on GitHub builds normally."""
    issue = TaskFactory.create()
    agent_called = False

    async def succeeding_agent(issue, wt_path, branch, **_kwargs):
        nonlocal agent_called
        agent_called = True
        return await _success_result(issue, wt_path)

    phase, _, mock_prs = make_implement_phase(
        config,
        [issue],
        agent_run=succeeding_agent,
        create_pr_return=PRInfoFactory.create(),
    )
    mock_prs.get_issue_state = AsyncMock(return_value="OPEN")

    result = await phase._worker_inner(0, issue, "agent/issue-42")

    assert agent_called is True
    assert result.success is True


async def test_resolved_issue_walk_ends_at_the_issue_state_gate(config) -> None:
    """The abandon walk is decompose -> no-progress-abort -> issue-state -> done."""
    issue = TaskFactory.create()

    async def hanging_agent(issue, wt_path, branch, **_kwargs):
        await asyncio.sleep(HARD_TIMEOUT)

    phase, _, mock_prs = make_implement_phase(config, [issue], agent_run=hanging_agent)
    mock_prs.get_issue_state = AsyncMock(return_value="COMPLETED")

    outcome = await asyncio.wait_for(
        phase._build_implement_flow().run(
            phase._initial_flow_state(0, issue, "agent/issue-42")
        ),
        timeout=TEST_GUARD_TIMEOUT,
    )

    assert outcome.path == ["decompose", "no-progress-abort", "issue-state", "done"]
    assert "build" not in outcome.path


# ---------------------------------------------------------------------------
# 2. Fail-open error path (load-bearing)
# ---------------------------------------------------------------------------


async def test_state_read_error_fails_open_and_builds(config) -> None:
    """A GitHub read failure must never block the build — fail open.

    The exact failure mode of a dark-factory Port: a transient ``gh`` error.
    Only a POSITIVE resolved read may abandon; an unreadable issue builds.
    """
    issue = TaskFactory.create()
    agent_called = False

    async def succeeding_agent(issue, wt_path, branch, **_kwargs):
        nonlocal agent_called
        agent_called = True
        return await _success_result(issue, wt_path)

    phase, _, mock_prs = make_implement_phase(
        config,
        [issue],
        agent_run=succeeding_agent,
        create_pr_return=PRInfoFactory.create(),
    )
    mock_prs.get_issue_state = AsyncMock(side_effect=RuntimeError("gh down"))

    result = await phase._worker_inner(0, issue, "agent/issue-42")

    assert agent_called is True, "a read error must fail open, not skip the build"
    assert mock_prs.get_issue_state.await_count >= 1
    assert result.success is True


async def test_unconfigured_state_return_fails_open(config) -> None:
    """A bare AsyncMock PRPort yields a MagicMock state — never resolved.

    This is why the predicate coerces through ``str()``: every pre-existing
    test (and any future caller) that never configures ``get_issue_state``
    keeps the pre-gate behaviour instead of abandoning every issue.
    """
    issue = TaskFactory.create()
    agent_called = False

    async def succeeding_agent(issue, wt_path, branch, **_kwargs):
        nonlocal agent_called
        agent_called = True
        return await _success_result(issue, wt_path)

    phase, _, mock_prs = make_implement_phase(
        config,
        [issue],
        agent_run=succeeding_agent,
        create_pr_return=PRInfoFactory.create(),
    )
    mock_prs.get_issue_state = AsyncMock(return_value=MagicMock())

    result = await phase._worker_inner(0, issue, "agent/issue-42")

    assert agent_called is True
    assert result.success is True


async def test_credit_exhausted_during_state_read_propagates(config) -> None:
    """Credit/auth exhaustion must reraise — never silently fail open.

    ``reraise_on_credit_or_bug`` is the dark-factory contract for every
    broad except around a Port read (CLAUDE.md); swallowing it here would
    burn attempt budget against an exhausted billing signal.
    """
    from subprocess_util import CreditExhaustedError

    issue = TaskFactory.create()
    phase, _, mock_prs = make_implement_phase(config, [issue])
    mock_prs.get_issue_state = AsyncMock(side_effect=CreditExhaustedError("no credits"))

    with pytest.raises(CreditExhaustedError):
        await phase._worker_inner(0, issue, "agent/issue-42")


# ---------------------------------------------------------------------------
# 3. Surface B — the pre-PR gate
# ---------------------------------------------------------------------------


async def test_issue_closed_during_build_abandons_before_opening_pr(config) -> None:
    """The window spans the build too: re-check before pushing/PR.

    State flips OPEN -> COMPLETED between the branch-cut check (surface A)
    and the open-pr check (surface B): the first read passes, the build
    spends, and the second read must still stop the DUPLICATE PR — the
    actual #11443/#11451 failure shape.
    """
    issue = TaskFactory.create()
    agent_called = False

    async def succeeding_agent(issue, wt_path, branch, **_kwargs):
        nonlocal agent_called
        agent_called = True
        return await _success_result(issue, wt_path)

    phase, _, mock_prs = make_implement_phase(
        config,
        [issue],
        agent_run=succeeding_agent,
        create_pr_return=PRInfoFactory.create(),
    )
    mock_prs.get_issue_state = AsyncMock(side_effect=["OPEN", "COMPLETED"])

    result = await phase._worker_inner(0, issue, "agent/issue-42")

    assert agent_called is True, "the build legitimately ran while the issue was open"
    # The branch-cut push (exactly once, from _setup_worktree_and_branch) is
    # legitimate build work; the DUPLICATE PR is what surface B must stop.
    assert mock_prs.push_branch.await_count == 1
    mock_prs.create_pr.assert_not_awaited()
    assert result.success is False
    assert "open-pr" in (result.error or "")
    assert phase._state.to_dict()["processed_issues"].get("42") == "completed"


# ---------------------------------------------------------------------------
# 4. Abandon semantics
# ---------------------------------------------------------------------------


async def test_abandon_neither_reenqueues_nor_strips_labels(config) -> None:
    """Abandon touches nothing but local state — GitHub reconciles itself.

    No ``enqueue_transition("ready")`` (the issue is closed; the next
    ``IssueFetcher`` refresh drops it via ``_is_open``), no pipeline-label
    swaps (``LabelDriftWatcherLoop`` owns stray labels on closed issues,
    ADR-0088), no diagnose/HITL routing (nothing is wrong).
    """
    issue = TaskFactory.create()

    async def hanging_agent(issue, wt_path, branch, **_kwargs):
        await asyncio.sleep(HARD_TIMEOUT)

    phase, _, mock_prs = make_implement_phase(config, [issue], agent_run=hanging_agent)
    mock_prs.get_issue_state = AsyncMock(return_value="COMPLETED")

    await asyncio.wait_for(
        phase._worker_inner(0, issue, "agent/issue-42"), timeout=TEST_GUARD_TIMEOUT
    )

    phase._store.enqueue_transition.assert_not_called()
    mock_prs.swap_pipeline_labels.assert_not_called()
    mock_prs.remove_label.assert_not_called()
    mock_prs.post_comment.assert_not_called()
    # Not routed to HITL/diagnose — the issue is done, not broken.
    assert phase._state.get_hitl_cause(42) is None
