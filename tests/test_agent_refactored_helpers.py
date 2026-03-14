"""Tests for agent.py extracted helper methods."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from agent import AgentRunner
from models import Task, WorkerResult
from tests.helpers import ConfigFactory


@pytest.fixture
def agent_task() -> Task:
    return Task(
        id=42,
        title="Fix the frobnicator",
        body="The frobnicator is broken.",
        tags=["ready"],
        comments=[],
        source_url="https://github.com/test/repo/issues/42",
    )


@pytest.fixture
def runner(config, event_bus):
    return AgentRunner(config=config, event_bus=event_bus)


# ---------------------------------------------------------------------------
# _build_plan_section
# ---------------------------------------------------------------------------


class TestBuildPlanSection:
    """Tests for AgentRunner._build_plan_section."""

    def test_returns_empty_when_no_plan(self, runner, agent_task) -> None:
        section, other, before, after = runner._build_plan_section(agent_task)
        assert section == ""
        assert other == []
        assert after == 0

    def test_extracts_plan_from_comments(self, runner, agent_task) -> None:
        agent_task.comments = [
            "## Implementation Plan\n\nDo the thing\n\n---\n**Branch:** main"
        ]
        section, other, before, after = runner._build_plan_section(agent_task)
        assert "## Implementation Plan" in section
        assert other == []
        assert after > 0

    def test_separates_non_plan_comments(self, runner, agent_task) -> None:
        agent_task.comments = [
            "Some discussion",
            "## Implementation Plan\n\nDo the thing",
            "Another comment",
        ]
        section, other, before, after = runner._build_plan_section(agent_task)
        assert len(other) == 2
        assert "Some discussion" in other
        assert "Another comment" in other

    def test_falls_back_to_plan_file(self, config, event_bus, agent_task) -> None:
        plan_path = config.plans_dir / "issue-42.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text("# Plan for Issue #42\n\nSaved plan\n")
        r = AgentRunner(config=config, event_bus=event_bus)
        section, _other, _before, after = r._build_plan_section(agent_task)
        assert "Saved plan" in section
        assert after > 0


# ---------------------------------------------------------------------------
# _build_context_sections
# ---------------------------------------------------------------------------


class TestBuildContextSections:
    """Tests for AgentRunner._build_context_sections."""

    def test_empty_when_no_feedback(self, runner) -> None:
        review, failure, before, after = runner._build_context_sections("", "")
        assert review == ""
        assert failure == ""
        assert before == 0
        assert after == 0

    def test_review_feedback_section(self, runner) -> None:
        review, failure, before, after = runner._build_context_sections(
            "Fix the tests", ""
        )
        assert "## Review Feedback" in review
        assert "Fix the tests" in review
        assert failure == ""
        assert before == len("Fix the tests")

    def test_prior_failure_section(self, runner) -> None:
        review, failure, before, after = runner._build_context_sections(
            "", "TypeError: bad arg"
        )
        assert review == ""
        assert "## Prior Attempt Failure" in failure
        assert "TypeError: bad arg" in failure

    def test_both_sections(self, runner) -> None:
        review, failure, before, after = runner._build_context_sections(
            "feedback", "error"
        )
        assert review != ""
        assert failure != ""
        assert before == len("feedback") + len("error")


# ---------------------------------------------------------------------------
# _build_insight_sections
# ---------------------------------------------------------------------------


class TestBuildInsightSections:
    """Tests for AgentRunner._build_insight_sections."""

    def test_empty_when_no_data(self, runner) -> None:
        feedback, escalation, escalations, before, after = (
            runner._build_insight_sections()
        )
        assert feedback == ""
        assert escalation == ""
        assert escalations == []
        assert before == 0
        assert after == 0


# ---------------------------------------------------------------------------
# _truncate_body
# ---------------------------------------------------------------------------


class TestTruncateBody:
    """Tests for AgentRunner._truncate_body."""

    def test_short_body_unchanged(self, runner) -> None:
        body, before, after = runner._truncate_body("short body")
        assert body == "short body"
        assert before == after

    def test_long_body_truncated(self, event_bus) -> None:
        cfg = ConfigFactory.create(max_issue_body_chars=1000)
        r = AgentRunner(config=cfg, event_bus=event_bus)
        body, before, after = r._truncate_body("a" * 2000)
        assert before == 2000
        assert after < 2000
        assert "Body truncated" in body


# ---------------------------------------------------------------------------
# _build_log_section
# ---------------------------------------------------------------------------


class TestBuildLogSection:
    """Tests for AgentRunner._build_log_section."""

    def test_empty_when_disabled(self, runner) -> None:
        assert runner._build_log_section() == ""

    def test_returns_log_section_when_enabled(self, event_bus) -> None:
        cfg = ConfigFactory.create(inject_runtime_logs=True)
        r = AgentRunner(config=cfg, event_bus=event_bus)
        with patch("log_context.load_runtime_logs", return_value="some log output"):
            section = r._build_log_section()
        assert "## Recent Application Logs" in section
        assert "some log output" in section


# ---------------------------------------------------------------------------
# _run_post_impl_checks
# ---------------------------------------------------------------------------


class TestRunPostImplChecks:
    """Tests for AgentRunner._run_post_impl_checks."""

    @pytest.mark.asyncio
    async def test_returns_early_on_sanity_failure(
        self, config, event_bus, agent_task
    ) -> None:
        r = AgentRunner(config=config, event_bus=event_bus)
        result = WorkerResult(
            issue_number=42, branch="test-branch", worktree_path="/tmp/test"
        )
        with (
            patch.object(
                r,
                "_run_diff_sanity_loop",
                new_callable=AsyncMock,
                return_value=MagicMock(passed=False, summary="bad diff"),
            ),
            patch.object(
                r,
                "_count_commits",
                new_callable=AsyncMock,
                return_value=1,
            ),
            patch.object(r, "_emit_status", new_callable=AsyncMock),
        ):
            early = await r._run_post_impl_checks(
                agent_task, Path("/tmp/test"), "test-branch", 0, result, 0.0
            )
        assert early is not None
        assert early.success is False
        assert "Diff sanity" in early.error

    @pytest.mark.asyncio
    async def test_returns_none_on_full_success(
        self, config, event_bus, agent_task
    ) -> None:
        r = AgentRunner(config=config, event_bus=event_bus)
        result = WorkerResult(
            issue_number=42, branch="test-branch", worktree_path="/tmp/test"
        )
        with (
            patch.object(
                r,
                "_run_diff_sanity_loop",
                new_callable=AsyncMock,
                return_value=MagicMock(passed=True),
            ),
            patch.object(
                r,
                "_run_test_adequacy_loop",
                new_callable=AsyncMock,
                return_value=MagicMock(passed=True),
            ),
            patch.object(
                r,
                "_run_pre_quality_review_loop",
                new_callable=AsyncMock,
                return_value=MagicMock(passed=True, attempts=1),
            ),
            patch.object(
                r,
                "_verify_result",
                new_callable=AsyncMock,
                return_value=MagicMock(passed=True, summary="OK"),
            ),
            patch.object(
                r,
                "_count_commits",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch.object(r, "_emit_status", new_callable=AsyncMock),
        ):
            early = await r._run_post_impl_checks(
                agent_task, Path("/tmp/test"), "test-branch", 0, result, 0.0
            )
        assert early is None
        assert result.success is True


# ---------------------------------------------------------------------------
# _gather_prompt_sections
# ---------------------------------------------------------------------------


class TestGatherPromptSections:
    """Tests for AgentRunner._gather_prompt_sections."""

    def test_returns_expected_section_keys(self, runner, agent_task) -> None:
        sections, escalations, h_b, h_a, b_b, b_a = runner._gather_prompt_sections(
            agent_task
        )
        expected_keys = {
            "body",
            "plan",
            "review",
            "failure",
            "comments",
            "manifest",
            "memory",
            "log",
            "feedback",
            "escalation",
        }
        assert set(sections.keys()) == expected_keys

    def test_no_review_feedback_gives_empty_sections(self, runner, agent_task) -> None:
        sections, _, _, _, _, _ = runner._gather_prompt_sections(agent_task)
        assert sections["review"] == ""
        assert sections["failure"] == ""

    def test_review_feedback_included(self, runner, agent_task) -> None:
        sections, _, _, _, _, _ = runner._gather_prompt_sections(
            agent_task, review_feedback="Fix tests"
        )
        assert "Fix tests" in sections["review"]

    def test_prior_failure_included(self, runner, agent_task) -> None:
        sections, _, _, _, _, _ = runner._gather_prompt_sections(
            agent_task, prior_failure="TypeError"
        )
        assert "TypeError" in sections["failure"]


# ---------------------------------------------------------------------------
# _assemble_impl_prompt
# ---------------------------------------------------------------------------


class TestAssembleImplPrompt:
    """Tests for AgentRunner._assemble_impl_prompt."""

    def test_contains_issue_info(self, runner, agent_task) -> None:
        sections = dict.fromkeys(
            [
                "body",
                "plan",
                "review",
                "failure",
                "comments",
                "manifest",
                "memory",
                "log",
                "feedback",
                "escalation",
            ],
            "",
        )
        sections["body"] = "The frobnicator is broken."
        prompt = runner._assemble_impl_prompt(agent_task, sections, [])
        assert "issue #42" in prompt.lower()
        assert "Fix the frobnicator" in prompt
        assert "The frobnicator is broken." in prompt

    def test_includes_instructions(self, runner, agent_task) -> None:
        sections = dict.fromkeys(
            [
                "body",
                "plan",
                "review",
                "failure",
                "comments",
                "manifest",
                "memory",
                "log",
                "feedback",
                "escalation",
            ],
            "",
        )
        prompt = runner._assemble_impl_prompt(agent_task, sections, [])
        assert "## Instructions" in prompt
        assert "## Rules" in prompt


# ---------------------------------------------------------------------------
# _compute_prompt_stats
# ---------------------------------------------------------------------------


class TestAgentComputePromptStats:
    """Tests for AgentRunner._compute_prompt_stats."""

    def test_no_pruning(self) -> None:
        stats = AgentRunner._compute_prompt_stats(
            history_before=100,
            history_after=100,
            body_before=200,
            body_after=200,
        )
        assert stats["pruned_chars_total"] == 0

    def test_with_pruning(self) -> None:
        stats = AgentRunner._compute_prompt_stats(
            history_before=500,
            history_after=300,
            body_before=1000,
            body_after=800,
        )
        assert stats["pruned_chars_total"] == 400
        assert stats["section_chars"]["issue_body_before"] == 1000
        assert stats["section_chars"]["issue_body_after"] == 800

    def test_returns_expected_keys(self) -> None:
        stats = AgentRunner._compute_prompt_stats(
            history_before=0,
            history_after=0,
            body_before=0,
            body_after=0,
        )
        assert "history_chars_before" in stats
        assert "context_chars_before" in stats
        assert "pruned_chars_total" in stats
        assert "section_chars" in stats


# ---------------------------------------------------------------------------
# _finalize_run
# ---------------------------------------------------------------------------


class TestFinalizeRun:
    """Tests for AgentRunner._finalize_run."""

    def test_sets_duration(self, runner) -> None:
        result = WorkerResult(issue_number=42, branch="b", worktree_path="/tmp")
        start = time.monotonic() - 1.0
        with patch.object(runner, "_save_transcript"):
            runner._finalize_run(result, start)
        assert result.duration_seconds >= 1.0

    def test_saves_transcript(self, runner) -> None:
        result = WorkerResult(issue_number=42, branch="b", worktree_path="/tmp")
        result.transcript = "some transcript"
        with patch.object(runner, "_save_transcript") as mock_save:
            runner._finalize_run(result, time.monotonic())
        mock_save.assert_called_once_with("issue", 42, "some transcript")

    def test_handles_oserror_gracefully(self, runner) -> None:
        result = WorkerResult(issue_number=42, branch="b", worktree_path="/tmp")
        with patch.object(runner, "_save_transcript", side_effect=OSError("disk")):
            runner._finalize_run(result, time.monotonic())
        assert result.duration_seconds >= 0
