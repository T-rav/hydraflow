"""Regression pins for P2 of epic #10682 — the implement phase on the flow primitive.

``ImplementPhase._worker_inner`` is a structural refactor onto the P0
``src/flows`` DAG runtime (ADR-0111): the same per-issue implement pipeline, now
expressed as an explicit ``Node``/``Edge`` graph
(``decompose -> no-progress-abort -> build -> screen -> (spec-verify | open-pr)
-> gate -> done``) instead of a straight-line method. This is the
highest-blast-radius conversion in the epic (implement is the core build phase)
and ships with NO feature flag, so parity is the only safety net.

These tests pin the load-bearing invariants of that cutover:

1. **Node order.** A failed attempt walks ``decompose -> build -> spec-verify ->
   gate`` (the documented gated direction), with the LLM/agent call confined to
   ``build``.
2. **Output parity.** The flow-backed public entry produces the same
   ``WorkerResult`` + side effects as the pre-refactor path for a seeded issue.
3. **No-progress early abort (#10659/#10616 — the point of P2).** A
   non-converging issue is escalated to HITL BEFORE ``build`` runs, so it never
   burns another full (up to ``agent_timeout``) build — proven with a build fake
   that would hang, wrapped in a short ``wait_for`` (as
   ``tests/regressions/test_issue_10597.py`` does).
4. **Happy path still opens a PR.** A successful build routes through ``open-pr``
   and creates the PR.

If any regress, a converted phase could resume mid-node, drop a step, thrash to
the attempt cap, or silently change the delivered ``WorkerResult``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from flows import Flow
from tests.conftest import PRInfoFactory, TaskFactory, WorkerResultFactory
from tests.helpers import ConfigFactory, make_implement_phase

# A stand-in for the stuck CLI / 3600s hard cap. If the flow (buggily) reaches
# ``build`` on a non-converging issue, this agent hangs; the test's ``wait_for``
# trips as a TimeoutError instead of hanging the suite.
HARD_TIMEOUT = 3600.0
TEST_GUARD_TIMEOUT = 5.0


def _tmp_config(
    tmp_path: Path,
    *,
    max_issue_attempts: int = 3,
    no_progress_attempts: int = 3,
):
    """A tmp-scoped config with the P2 no-progress abort threshold wired.

    ``ConfigFactory`` has an explicit signature and does not surface the new
    ``implement_no_progress_abort_attempts`` knob, so it is stamped on via
    ``model_copy`` (Pydantic v2) after construction.
    """
    config = ConfigFactory.create(
        max_issue_attempts=max_issue_attempts,
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    return config.model_copy(
        update={"implement_no_progress_abort_attempts": no_progress_attempts}
    )


def _is_subsequence(sub: list[str], seq: list[str]) -> bool:
    """True if *sub* appears in *seq* in order (not necessarily contiguously)."""
    it = iter(seq)
    return all(item in it for item in sub)


async def _zero_commit_agent(
    issue,
    wt_path: Path,
    branch: str,
    worker_id: int = 0,
    review_feedback: str = "",
    prior_failure: str = "",
    **_kwargs: object,
):
    return WorkerResultFactory.create(
        issue_number=issue.id,
        branch=branch,
        success=False,
        error="No commits found on branch",
        commits=0,
        workspace_path=str(wt_path),
    )


# ---------------------------------------------------------------------------
# 1. Flow shape + node order
# ---------------------------------------------------------------------------


async def test_worker_inner_builds_a_flow_entered_at_decompose(config) -> None:
    """The per-issue pipeline is an ``src.flows.Flow`` whose entry is ``decompose``."""
    phase, _, _ = make_implement_phase(config, [])

    flow = phase._build_implement_flow()

    assert isinstance(flow, Flow)
    assert flow.entry == "decompose"


async def test_failed_attempt_walks_decompose_build_spec_verify_gate(config) -> None:
    """A failed build walks decompose -> build -> spec-verify -> gate (in order)."""
    issue = TaskFactory.create()
    phase, _, _ = make_implement_phase(config, [issue], agent_run=_zero_commit_agent)

    recorded: list[str] = []
    flow = phase._build_implement_flow(
        checkpoint=lambda name, _state: recorded.append(name)
    )
    result = await flow.run(phase._initial_flow_state(0, issue, "agent/issue-42"))

    # The gated build direction the epic names, as a subsequence (the flow also
    # threads no-progress-abort + screen between these anchors).
    assert _is_subsequence(["decompose", "build", "spec-verify", "gate"], result.path)
    # Checkpoint fires once per node, in walk order (the resume substrate).
    assert recorded == result.path
    assert result.terminal == "done"


async def test_llm_call_is_confined_to_the_build_node(config) -> None:
    """The agent (LLM actuator) runs only inside ``build`` — never before it."""
    issue = TaskFactory.create()
    order: list[str] = []

    async def tracking_agent(issue, wt_path, branch, **_kwargs):
        order.append("agent")
        return WorkerResultFactory.create(
            issue_number=issue.id, success=True, workspace_path=str(wt_path)
        )

    phase, _, _ = make_implement_phase(
        config,
        [issue],
        agent_run=tracking_agent,
        create_pr_return=PRInfoFactory.create(),
    )
    seen: list[str] = []
    flow = phase._build_implement_flow(
        checkpoint=lambda name, _state: seen.append(name)
    )
    await flow.run(phase._initial_flow_state(0, issue, "agent/issue-42"))

    # The agent fires while build is the current node — i.e. after decompose /
    # no-progress-abort have both been walked and before screen.
    assert "build" in seen
    assert order == ["agent"]
    assert seen.index("build") == seen.index("screen") - 1


# ---------------------------------------------------------------------------
# 2. Output parity
# ---------------------------------------------------------------------------


async def test_happy_path_opens_a_pr_and_transitions_to_review(config) -> None:
    """A successful build routes through ``open-pr`` and creates the PR."""
    issue = TaskFactory.create()
    phase, _, mock_prs = make_implement_phase(
        config, [issue], create_pr_return=PRInfoFactory.create()
    )

    result = await flow_run_worker(phase, issue)

    assert result.success is True
    assert result.pr_info is not None and result.pr_info.number == 101
    mock_prs.create_pr.assert_awaited_once()
    mock_prs.transition.assert_awaited_once_with(42, "review", pr_number=101)
    assert phase._state.to_dict()["processed_issues"].get("42") == "success"


async def test_happy_path_flow_walks_through_open_pr(config) -> None:
    """The happy path's node walk includes ``open-pr`` (and never spec-verify)."""
    issue = TaskFactory.create()
    phase, _, _ = make_implement_phase(
        config, [issue], create_pr_return=PRInfoFactory.create()
    )

    result = await phase._build_implement_flow().run(
        phase._initial_flow_state(0, issue, "agent/issue-42")
    )

    assert "open-pr" in result.path
    assert "spec-verify" not in result.path
    assert result.terminal == "done"


async def test_zero_commit_parity_marks_failed_without_hitl(config) -> None:
    """Zero-commit failure marks failed + posts the comment, no HITL (parity)."""
    issue = TaskFactory.create()
    phase, _, mock_prs = make_implement_phase(
        config, [issue], agent_run=_zero_commit_agent
    )

    result = await flow_run_worker(phase, issue)

    assert result.success is False
    assert phase._state.to_dict()["processed_issues"].get("42") == "failed"
    assert phase._state.get_hitl_cause(42) is None
    comment_bodies = [c.args[1] for c in mock_prs.post_comment.call_args_list]
    assert any("Zero Commits" in body for body in comment_bodies)


async def flow_run_worker(phase, issue):
    """Drive one attempt through the flow-backed ``_worker_inner``."""
    return await phase._worker_inner(0, issue, "agent/issue-42")


# ---------------------------------------------------------------------------
# 3. No-progress early abort (the point of P2)
# ---------------------------------------------------------------------------


async def test_no_progress_aborts_to_hitl_before_running_the_build(
    tmp_path: Path,
) -> None:
    """A non-converging issue escalates to HITL BEFORE ``build`` — never burning
    another full (up to agent_timeout) build cycle.

    Threshold 2 + a prior zero-commit attempt means attempt 2 aborts up front.
    The ``build`` agent would hang if reached (stand-in for the 3600s cap); the
    short ``wait_for`` proves the abort fires in milliseconds and ``build`` is
    skipped entirely, rather than a regression that thrashes to the cap.
    """
    config = _tmp_config(tmp_path, max_issue_attempts=3, no_progress_attempts=2)
    issue = TaskFactory.create()

    agent_called = False

    async def hanging_agent(issue, wt_path, branch, **_kwargs):
        nonlocal agent_called
        agent_called = True
        await asyncio.sleep(
            HARD_TIMEOUT
        )  # the stuck build; never awaited to completion
        return WorkerResultFactory.create(issue_number=issue.id, success=False)

    phase, _, mock_prs = make_implement_phase(config, [issue], agent_run=hanging_agent)
    # Prior attempt produced no output; next increment lands at the threshold.
    phase._state.increment_issue_attempts(42)
    phase._state.set_worker_result_meta(
        42, {"commits": 0, "error": "No commits found on branch"}
    )

    result = await asyncio.wait_for(
        flow_run_worker(phase, issue), timeout=TEST_GUARD_TIMEOUT
    )

    # Aborted to HITL without running (or hanging in) the build.
    assert agent_called is False
    assert result.success is False
    assert "aborted" in (result.error or "").lower()
    assert phase._state.to_dict()["processed_issues"].get("42") == "failed"
    # Escalated through the shared HITL escalator (routes to diagnose).
    assert phase._state.get_hitl_cause(42) is not None
    mock_prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-diagnose")
    comment_bodies = [c.args[1] for c in mock_prs.post_comment.call_args_list]
    assert any("No Progress" in body for body in comment_bodies)


async def test_no_progress_abort_flow_skips_build_node(tmp_path: Path) -> None:
    """The abort walk is decompose -> no-progress-abort -> done (build skipped)."""
    config = _tmp_config(tmp_path, max_issue_attempts=3, no_progress_attempts=2)
    issue = TaskFactory.create()

    async def hanging_agent(issue, wt_path, branch, **_kwargs):
        await asyncio.sleep(HARD_TIMEOUT)
        return WorkerResultFactory.create(issue_number=issue.id, success=False)

    phase, _, _ = make_implement_phase(config, [issue], agent_run=hanging_agent)
    phase._state.increment_issue_attempts(42)
    phase._state.set_worker_result_meta(
        42, {"commits": 0, "error": "No commits found on branch"}
    )

    result = await asyncio.wait_for(
        phase._build_implement_flow().run(
            phase._initial_flow_state(0, issue, "agent/issue-42")
        ),
        timeout=TEST_GUARD_TIMEOUT,
    )

    assert result.path == ["decompose", "no-progress-abort", "done"]
    assert "build" not in result.path


async def test_first_no_output_attempt_still_retries_not_abort(tmp_path: Path) -> None:
    """A single prior no-output attempt below threshold still runs the build.

    Guards the ADR-0063 W5 corrective retry: with the default threshold == the
    default ``max_issue_attempts``, the second attempt after one zero-commit
    failure must still build (so W5 gap-feed recovery can succeed).
    """
    config = _tmp_config(tmp_path, max_issue_attempts=3, no_progress_attempts=3)
    issue = TaskFactory.create()

    agent_called = False

    async def succeeding_agent(issue, wt_path, branch, **_kwargs):
        nonlocal agent_called
        agent_called = True
        return WorkerResultFactory.create(
            issue_number=issue.id, success=True, workspace_path=str(wt_path)
        )

    phase, _, _ = make_implement_phase(
        config,
        [issue],
        agent_run=succeeding_agent,
        create_pr_return=PRInfoFactory.create(),
    )
    # One prior zero-commit attempt; next attempt (2) is below the threshold (3).
    phase._state.increment_issue_attempts(42)
    phase._state.set_worker_result_meta(
        42, {"commits": 0, "error": "No commits found on branch"}
    )

    result = await flow_run_worker(phase, issue)

    assert agent_called is True
    assert result.success is True


async def test_abort_disabled_when_threshold_zero(tmp_path: Path) -> None:
    """``implement_no_progress_abort_attempts = 0`` disables the abort entirely."""
    config = _tmp_config(tmp_path, max_issue_attempts=5, no_progress_attempts=0)
    issue = TaskFactory.create()

    agent_called = False

    async def succeeding_agent(issue, wt_path, branch, **_kwargs):
        nonlocal agent_called
        agent_called = True
        return WorkerResultFactory.create(
            issue_number=issue.id, success=True, workspace_path=str(wt_path)
        )

    phase, _, _ = make_implement_phase(
        config,
        [issue],
        agent_run=succeeding_agent,
        create_pr_return=PRInfoFactory.create(),
    )
    # Well past any threshold + a no-output prior attempt: disabled ⇒ still build.
    for _ in range(4):
        phase._state.increment_issue_attempts(42)
    phase._state.set_worker_result_meta(
        42, {"commits": 0, "error": "No commits found on branch"}
    )

    result = await flow_run_worker(phase, issue)

    assert agent_called is True
    assert result.success is True


# ---------------------------------------------------------------------------
# 5. Issue-state gate placement (#11457)
# ---------------------------------------------------------------------------


async def test_issue_state_gate_is_the_last_gate_before_build(config) -> None:
    """The #11457 re-check sits between ``no-progress-abort`` and ``build``.

    Deliberate placement: ``decompose``'s existing-PR shortcut and attempt
    cap, then the no-progress abort, must all run BEFORE the GitHub state
    re-read — and the re-read must be the final gate before the actuator, so
    the selection→branch-cut window (#11443/#11451) is closed as late as
    possible without re-ordering admission control.
    """
    issue = TaskFactory.create()
    phase, _, _ = make_implement_phase(
        config, [issue], create_pr_return=PRInfoFactory.create()
    )

    recorded: list[str] = []
    flow = phase._build_implement_flow(
        checkpoint=lambda name, _state: recorded.append(name)
    )
    await flow.run(phase._initial_flow_state(0, issue, "agent/issue-42"))

    assert _is_subsequence(
        ["decompose", "no-progress-abort", "issue-state", "build"], recorded
    )
    # Adjacency in the happy-path walk: nothing may be interleaved between
    # the re-check and the build it guards.
    assert recorded.index("issue-state") == recorded.index("build") - 1
