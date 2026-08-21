"""Zero-commit first attempt routes to diagnose, not to attempt 2 (#11568).

Measured: attempts per merged issue doubled (1.2 → 2.2) and 13 of 153
implement results ended "No commits found on branch" — each then burned a
second and third build on the same shape. A zero-commit result is not a
partial success to retry blindly: the ``zero-commit-abort`` flow node now
fires on the FIRST such result (``implement_no_progress_abort_attempts``
default 1) and routes the issue to the diagnostic agent with the transcript
tail, skipping the W5 spec review (nothing to review) and the next build.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from subprocess_util import CreditExhaustedError
from tests.conftest import PRInfoFactory, TaskFactory, WorkerResultFactory
from tests.helpers import ConfigFactory, make_implement_phase

ISSUE = 42
TRANSCRIPT = "x" * 5000 + "TAIL-MARKER"


def _config(tmp_path: Path, *, abort_attempts: int = 1, max_attempts: int = 3):
    config = ConfigFactory.create(
        max_issue_attempts=max_attempts,
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    return config.model_copy(
        update={"implement_no_progress_abort_attempts": abort_attempts}
    )


def _result(issue, wt_path, branch, *, commits: int, transcript: str = TRANSCRIPT):
    return WorkerResultFactory.create(
        issue_number=issue.id,
        branch=branch,
        success=False,
        error="No commits found on branch" if commits == 0 else "make quality failed",
        commits=commits,
        workspace_path=str(wt_path),
        transcript=transcript,
    )


def _agent(*, commits: int, calls: list[int] | None = None):
    async def agent(issue, wt_path, branch, **_kwargs):
        if calls is not None:
            calls.append(issue.id)
        return _result(issue, wt_path, branch, commits=commits)

    return agent


class TestFirstZeroCommitRoutesToDiagnose:
    @pytest.mark.asyncio
    async def test_label_swaps_to_diagnose(self, tmp_path: Path) -> None:
        phase, _, prs = make_implement_phase(
            _config(tmp_path),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
        )

        await phase.run_batch()

        prs.swap_pipeline_labels.assert_any_call(ISSUE, "hydraflow-diagnose")

    @pytest.mark.asyncio
    async def test_store_transitions_to_diagnose(self, tmp_path: Path) -> None:
        phase, _, _ = make_implement_phase(
            _config(tmp_path),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
        )

        await phase.run_batch()

        stages = [c.args[1] for c in phase._store.enqueue_transition.call_args_list]
        assert stages == ["diagnose"]

    @pytest.mark.asyncio
    async def test_hitl_cause_names_zero_commits(self, tmp_path: Path) -> None:
        phase, _, _ = make_implement_phase(
            _config(tmp_path),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
        )

        await phase.run_batch()

        assert "zero commits" in (phase._state.get_hitl_cause(ISSUE) or "").lower()

    @pytest.mark.asyncio
    async def test_escalation_context_carries_the_transcript_tail(
        self, tmp_path: Path
    ) -> None:
        config = _config(tmp_path)
        phase, _, _ = make_implement_phase(
            config, [TaskFactory.create(id=ISSUE)], agent_run=_agent(commits=0)
        )

        await phase.run_batch()

        context = phase._state.get_escalation_context(ISSUE)
        assert context is not None
        assert context.agent_transcript is not None
        assert context.agent_transcript.endswith("TAIL-MARKER")
        assert len(context.agent_transcript) <= config.error_output_max_chars

    @pytest.mark.asyncio
    async def test_escalation_context_origin_is_implement(self, tmp_path: Path) -> None:
        phase, _, _ = make_implement_phase(
            _config(tmp_path),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
        )

        await phase.run_batch()

        context = phase._state.get_escalation_context(ISSUE)
        assert context is not None and context.origin_phase == "implement"

    @pytest.mark.asyncio
    async def test_comment_explains_the_routing(self, tmp_path: Path) -> None:
        phase, _, prs = make_implement_phase(
            _config(tmp_path),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
        )

        await phase.run_batch()

        bodies = [c.args[1] for c in prs.post_comment.call_args_list]
        assert any("Zero Commits" in b and "diagnos" in b.lower() for b in bodies)

    @pytest.mark.asyncio
    async def test_issue_is_marked_failed(self, tmp_path: Path) -> None:
        phase, _, _ = make_implement_phase(
            _config(tmp_path),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
        )

        await phase.run_batch()

        assert phase._state.to_dict()["processed_issues"].get(str(ISSUE)) == "failed"

    @pytest.mark.asyncio
    async def test_result_keeps_the_zero_commit_error(self, tmp_path: Path) -> None:
        phase, _, _ = make_implement_phase(
            _config(tmp_path),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
        )

        results, _ = await phase.run_batch()

        assert results[0].success is False
        assert results[0].error == "No commits found on branch"

    @pytest.mark.asyncio
    async def test_spec_review_is_not_dispatched(self, tmp_path: Path) -> None:
        """Nothing to spec-review on zero commits — save the reviewer spawn."""
        reviewer = AsyncMock()
        phase, _, _ = make_implement_phase(
            _config(tmp_path),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
            spec_reviewer=reviewer,
        )

        await phase.run_batch()

        reviewer.review.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flow_walk_ends_at_the_abort_node(self, tmp_path: Path) -> None:
        phase, _, _ = make_implement_phase(
            _config(tmp_path),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
        )

        outcome = await phase._build_implement_flow().run(
            phase._initial_flow_state(0, TaskFactory.create(id=ISSUE), "agent/issue-42")
        )

        assert outcome.path[-3:] == ["screen", "zero-commit-abort", "done"]
        assert "spec-verify" not in outcome.path
        assert outcome.state["disposition"] == "escalate"

    @pytest.mark.asyncio
    async def test_resume_at_screen_takes_the_same_route(self, tmp_path: Path) -> None:
        """``_handle_implementation_result`` re-enters the same graph."""
        phase, _, prs = make_implement_phase(_config(tmp_path), [])
        issue = TaskFactory.create(id=ISSUE)
        result = _result(issue, tmp_path / "wt", "agent/issue-42", commits=0)

        await phase._handle_implementation_result(issue, result, is_retry=False)

        prs.swap_pipeline_labels.assert_any_call(ISSUE, "hydraflow-diagnose")


class TestNoSecondAttempt:
    @pytest.mark.asyncio
    async def test_issue_is_not_rebuilt_once_routed(self, tmp_path: Path) -> None:
        """A store that keeps offering the issue until it leaves ``ready``
        (the real IssueStore contract) sees exactly one build."""
        calls: list[int] = []
        issue = TaskFactory.create(id=ISSUE)
        phase, _, _ = make_implement_phase(
            _config(tmp_path), [issue], agent_run=_agent(commits=0, calls=calls)
        )
        routed: list[str] = []
        offers: list[int] = []
        phase._store.enqueue_transition = lambda _t, stage: routed.append(stage)

        def _offer(_n=None):
            # Re-offer while still at ready, bounded so a regression fails
            # instead of spinning the refilling pool forever.
            if routed or len(offers) >= 3:
                return []
            offers.append(issue.id)
            return [issue]

        phase._store.get_implementable = _offer

        await phase.run_batch()
        await phase.run_batch()

        assert calls == [ISSUE]
        assert phase._state.get_issue_attempts(ISSUE) == 1


class TestKillSwitchAndThreshold:
    @pytest.mark.asyncio
    async def test_threshold_zero_restores_the_retry_shape(
        self, tmp_path: Path
    ) -> None:
        reviewer = AsyncMock()
        phase, _, prs = make_implement_phase(
            _config(tmp_path, abort_attempts=0),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
            spec_reviewer=reviewer,
        )

        await phase.run_batch()

        assert phase._state.get_hitl_cause(ISSUE) is None
        swapped = [c.args for c in prs.swap_pipeline_labels.call_args_list]
        assert (ISSUE, "hydraflow-diagnose") not in swapped
        reviewer.review.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_threshold_two_lets_the_first_zero_commit_retry(
        self, tmp_path: Path
    ) -> None:
        phase, _, _ = make_implement_phase(
            _config(tmp_path, abort_attempts=2),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
        )

        await phase.run_batch()

        assert phase._state.get_hitl_cause(ISSUE) is None

    @pytest.mark.asyncio
    async def test_threshold_two_aborts_the_second_zero_commit(
        self, tmp_path: Path
    ) -> None:
        phase, _, prs = make_implement_phase(
            _config(tmp_path, abort_attempts=2),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=0),
        )
        phase._state.increment_issue_attempts(ISSUE)  # this run is attempt 2

        await phase.run_batch()

        prs.swap_pipeline_labels.assert_any_call(ISSUE, "hydraflow-diagnose")


class TestOnlyZeroCommitsAbort:
    @pytest.mark.asyncio
    async def test_committed_failure_still_takes_the_retry_path(
        self, tmp_path: Path
    ) -> None:
        reviewer = AsyncMock()
        phase, _, _ = make_implement_phase(
            _config(tmp_path),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=2),
            spec_reviewer=reviewer,
        )

        await phase.run_batch()

        assert phase._state.get_hitl_cause(ISSUE) is None
        reviewer.review.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_credit_exhaustion_is_not_a_zero_commit_failure(
        self, tmp_path: Path
    ) -> None:
        """ADR-0119: a credit cap raises through the phase so the orchestrator
        pauses — it never becomes a ``commits=0`` result routed to diagnose."""

        async def capped_agent(issue, wt_path, branch, **_kwargs):
            raise CreditExhaustedError("limit reached")

        phase, _, prs = make_implement_phase(
            _config(tmp_path), [TaskFactory.create(id=ISSUE)], agent_run=capped_agent
        )

        with pytest.raises(CreditExhaustedError):
            await phase.run_batch()

        assert phase._state.get_hitl_cause(ISSUE) is None
        swapped = [c.args for c in prs.swap_pipeline_labels.call_args_list]
        assert (ISSUE, "hydraflow-diagnose") not in swapped


class TestPreBuildAbortNeedsAPriorAttemptThisCycle:
    @pytest.mark.asyncio
    async def test_requeued_issue_with_stale_meta_still_builds(
        self, tmp_path: Path
    ) -> None:
        """A human re-queue resets the attempt counter but not the last
        worker meta; attempt 1 of the new cycle must build, not bounce."""
        calls: list[int] = []
        phase, _, _ = make_implement_phase(
            _config(tmp_path),
            [TaskFactory.create(id=ISSUE)],
            agent_run=_agent(commits=2, calls=calls),
            create_pr_return=PRInfoFactory.create(),
        )
        phase._state.set_worker_result_meta(
            ISSUE, {"commits": 0, "error": "No commits found on branch"}
        )
        phase._state.reset_issue_attempts(ISSUE)

        await phase.run_batch()

        assert calls == [ISSUE]
