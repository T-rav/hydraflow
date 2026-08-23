"""Tests for hitl_runner.py — HITLRunner class."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_runner import BaseRunner
from config import HydraFlowConfig
from events import EventBus, EventType
from hitl_runner import HITLRunner, _classify_cause
from models import LoopResult
from tests.conftest import HITLResultFactory, IssueFactory


@pytest.fixture
def hitl_runner(config, event_bus):
    return HITLRunner(config, event_bus)


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


class TestHITLRunnerInheritance:
    """HITLRunner must extend BaseRunner."""

    def test_inherits_from_base_runner(self, hitl_runner) -> None:
        assert isinstance(hitl_runner, BaseRunner)

    def test_has_terminate_method(self, hitl_runner) -> None:
        assert callable(hitl_runner.terminate)


# ---------------------------------------------------------------------------
# Cause classification
# ---------------------------------------------------------------------------


class TestClassifyCause:
    @pytest.mark.parametrize(
        ("summary", "expected"),
        [
            pytest.param(
                "CI failed after 2 fix attempt(s)", "ci", id="ci_failure_maps_to_ci"
            ),
            pytest.param(
                "Failed checks: lint, test", "ci", id="check_keyword_maps_to_ci"
            ),
            pytest.param(
                "test fail in module", "ci", id="test_fail_keyword_maps_to_ci"
            ),
            pytest.param(
                "Merge conflict with main branch",
                "merge_conflict",
                id="merge_conflict_maps_correctly",
            ),
            pytest.param(
                "Insufficient issue detail for triage",
                "needs_info",
                id="insufficient_detail_maps_to_needs_info",
            ),
            pytest.param(
                "Needs more information",
                "needs_info",
                id="needs_more_info_maps_to_needs_info",
            ),
            pytest.param(
                "Unknown escalation", "default", id="unknown_cause_maps_to_default"
            ),
            pytest.param(
                "PR merge failed on GitHub",
                "default",
                id="pr_merge_failed_maps_to_default",
            ),
            pytest.param("", "default", id="empty_cause_maps_to_default"),
            pytest.param(
                "Visual validation failed on 3 screens",
                "visual",
                id="visual_keyword_maps_to_visual",
            ),
            pytest.param(
                "Screenshot diff exceeded threshold",
                "visual",
                id="screenshot_keyword_maps_to_visual",
            ),
            pytest.param(
                "diff image mismatch on login page",
                "visual",
                id="diff_image_keyword_maps_to_visual",
            ),
            # Visual keywords must match BEFORE CI keywords when both are present.
            pytest.param(
                "Visual check failed in CI", "visual", id="visual_before_ci_priority"
            ),
            # Visual keywords must match BEFORE needs_info when the text says "needs".
            pytest.param(
                "Visual validation failed: login screen needs baseline update",
                "visual",
                id="visual_before_needs_info_priority",
            ),
            # "deficit" contains "ci" as a substring — the word boundary must hold.
            pytest.param(
                "deficit in implementation coverage",
                "default",
                id="ci_word_boundary_not_substring",
            ),
        ],
    )
    def test_classify_cause_maps_summary_to_category(
        self, summary: str, expected: str
    ) -> None:
        assert _classify_cause(summary) == expected


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    @pytest.mark.asyncio
    async def test_prompt_includes_issue_title(self, hitl_runner) -> None:
        issue = IssueFactory.create(number=42, title="Fix the widget")
        prompt, _ = await hitl_runner._build_prompt_with_stats(
            issue, "Try mocking the DB", "CI failed"
        )
        assert "Fix the widget" in prompt

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("issue_number", "correction", "cause", "expected_fragment"),
        [
            pytest.param(
                42,
                "Mock the database layer",
                "CI failed",
                "Mock the database layer",
                id="test_prompt_includes_correction_text",
            ),
            pytest.param(
                42,
                "Fix it",
                "CI failed after 2 attempts",
                "CI failed after 2 attempts",
                id="test_prompt_includes_cause",
            ),
            pytest.param(
                42,
                "Add logging",
                "Insufficient issue detail for triage",
                "comprehensive tests",
                id="test_prompt_uses_needs_info_instructions",
            ),
            pytest.param(
                99,
                "Fix it",
                "Unknown",
                "#99",
                id="test_prompt_includes_issue_number_in_commit_message",
            ),
            pytest.param(
                42,
                "Fix",
                "CI failed",
                "Do NOT push to remote",
                id="test_prompt_includes_no_push_rule",
            ),
        ],
    )
    async def test_prompt_contains_expected_fragment(
        self,
        hitl_runner,
        issue_number: int,
        correction: str,
        cause: str,
        expected_fragment: str,
    ) -> None:
        issue = IssueFactory.create(number=issue_number)
        prompt, _ = await hitl_runner._build_prompt_with_stats(issue, correction, cause)
        assert expected_fragment in prompt

    @pytest.mark.asyncio
    async def test_prompt_uses_ci_instructions_for_ci_cause(self, hitl_runner) -> None:
        issue = IssueFactory.create(number=42)
        prompt, _ = await hitl_runner._build_prompt_with_stats(
            issue, "Fix", "CI failed after 2 fix attempt(s)"
        )
        assert "make quality" in prompt
        assert "do NOT skip or disable tests" in prompt

    @pytest.mark.asyncio
    async def test_prompt_uses_merge_instructions_for_conflict_cause(
        self, hitl_runner
    ) -> None:
        issue = IssueFactory.create(number=42)
        prompt, _ = await hitl_runner._build_prompt_with_stats(
            issue, "Fix", "Merge conflict with main branch"
        )
        assert "git status" in prompt
        assert "conflict" in prompt.lower()

    @pytest.mark.asyncio
    async def test_prompt_uses_visual_instructions_for_visual_cause(
        self, hitl_runner
    ) -> None:
        issue = IssueFactory.create(number=42)
        prompt, _ = await hitl_runner._build_prompt_with_stats(
            issue, "Fix the button", "Visual validation failed on login screen"
        )
        assert "visual" in prompt.lower()
        assert "screenshot" in prompt.lower()
        assert "visual regression" in prompt.lower()

    @pytest.mark.asyncio
    async def test_prompt_includes_memory_suggestion_block(self, hitl_runner) -> None:
        issue = IssueFactory.create(number=42)
        prompt, _ = await hitl_runner._build_prompt_with_stats(
            issue, "Fix", "CI failed"
        )
        assert "MEMORY_SUGGESTION_START" in prompt
        assert "MEMORY_SUGGESTION_END" in prompt

    @pytest.mark.asyncio
    async def test_prompt_no_project_context_without_hindsight(
        self, hitl_runner
    ) -> None:
        """Without Hindsight, ## Project Context is absent (manifest is Hindsight-only)."""
        issue = IssueFactory.create(number=42)
        prompt, _ = await hitl_runner._build_prompt_with_stats(
            issue, "Fix", "CI failed"
        )
        assert "## Project Context" not in prompt

    @pytest.mark.asyncio
    async def test_prompt_no_accumulated_learnings_without_hindsight(
        self, hitl_runner
    ) -> None:
        """Without Hindsight, ## Accumulated Learnings is absent (digest removed)."""
        issue = IssueFactory.create(number=42)
        prompt, _ = await hitl_runner._build_prompt_with_stats(
            issue, "Fix", "CI failed"
        )
        assert "## Accumulated Learnings" not in prompt

    @pytest.mark.asyncio
    async def test_prompt_forbids_unrelated_refactoring(self, hitl_runner) -> None:
        """Prompt must warn agent not to bundle unrelated refactoring."""
        issue = IssueFactory.create(number=42)
        prompt, _ = await hitl_runner._build_prompt_with_stats(
            issue, "Fix the test", "CI failed"
        )
        assert "Do NOT bundle unrelated refactoring" in prompt
        assert "Each concern is a separate PR" in prompt


class TestBuildPromptHumanSteering:
    """ADR-0099 #4 — live operator guidance folded into the HITL cause-template.

    Unlike the plain-prompt builders (planner, reviewer, etc.), HITL's prompt
    is assembled from cause-keyed instruction templates
    (``_CAUSE_INSTRUCTIONS``). Guidance must still reach the model ONLY via
    ``fenced_steering_guidance`` — never as raw comment text (ADR-0092 fence
    invariant) — appended to the rendered cause-template output.
    """

    @pytest.mark.asyncio
    async def test_folds_fenced_human_steering_guidance(self, hitl_runner) -> None:
        from human_steering import fenced_steering_guidance

        issue = IssueFactory.create(number=42, title="Fix the widget")
        guidance = "Prioritize the enterprise SSO angle over consumer features."

        prompt, _ = await hitl_runner._build_prompt_with_stats(
            issue, "Fix it", "CI failed", guidance
        )

        assert "## Human Steering Guidance" in prompt
        assert fenced_steering_guidance(guidance) in prompt

    @pytest.mark.asyncio
    async def test_empty_guidance_produces_no_steering_section(
        self, hitl_runner
    ) -> None:
        issue = IssueFactory.create(number=42, title="Fix the widget")

        prompt, _ = await hitl_runner._build_prompt_with_stats(
            issue, "Fix it", "CI failed", ""
        )

        assert "## Human Steering Guidance" not in prompt

    @pytest.mark.asyncio
    async def test_default_guidance_param_produces_no_steering_section(
        self, hitl_runner
    ) -> None:
        """Callers that don't pass ``guidance`` at all get unchanged behavior."""
        issue = IssueFactory.create(number=42, title="Fix the widget")

        prompt, _ = await hitl_runner._build_prompt_with_stats(
            issue, "Fix it", "CI failed"
        )

        assert "## Human Steering Guidance" not in prompt

    @pytest.mark.asyncio
    async def test_run_threads_guidance_kwarg_into_prompt(
        self, config, event_bus
    ) -> None:
        """``HITLRunner.run(..., guidance=...)`` reaches the executed prompt."""
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42, title="Fix the widget")
        guidance = "Watch out for the flaky auth fixture."

        captured: dict[str, object] = {}

        async def fake_execute(cmd, prompt, worktree_path, meta, **kwargs):  # noqa: ANN001, ARG001
            captured["prompt"] = prompt
            return "transcript"

        runner._execute = fake_execute  # type: ignore[method-assign]
        runner._verify_quality = AsyncMock(  # type: ignore[method-assign]
            return_value=LoopResult(passed=True, summary="OK")
        )

        await runner.run(
            issue, "fix the test", "CI failed", Path("/tmp/wt"), guidance=guidance
        )

        assert "## Human Steering Guidance" in captured["prompt"]


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_command_includes_claude(self, hitl_runner) -> None:
        cmd = hitl_runner._build_command(Path("/tmp/wt"))
        assert cmd[0] == "claude"
        assert "-p" in cmd

    def test_command_includes_model(self, hitl_runner, config) -> None:
        cmd = hitl_runner._build_command(Path("/tmp/wt"))
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == config.model

    def test_command_excludes_budget_flag(self, hitl_runner) -> None:
        cmd = hitl_runner._build_command(Path("/tmp/wt"))
        assert "--max-budget-usd" not in cmd

    def test_command_supports_codex_backend(self, event_bus) -> None:
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            implementation_tool="codex",
            model="gpt-5-codex",
        )
        runner = HITLRunner(cfg, event_bus)
        cmd = runner._build_command(Path("/tmp/wt"))
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


# ---------------------------------------------------------------------------
# Run — dry run mode
# ---------------------------------------------------------------------------


class TestRunDryMode:
    @pytest.mark.asyncio
    async def test_dry_run_returns_success(self, dry_config, event_bus) -> None:
        runner = HITLRunner(dry_config, event_bus)
        issue = IssueFactory.create(number=42)
        result = await runner.run(issue, "correction", "cause", Path("/tmp/wt"))
        assert result.success is True
        assert result.issue_number == 42

    @pytest.mark.asyncio
    async def test_dry_run_publishes_event(self, dry_config, event_bus) -> None:
        runner = HITLRunner(dry_config, event_bus)
        issue = IssueFactory.create(number=42)
        await runner.run(issue, "correction", "cause", Path("/tmp/wt"))

        events = [e for e in event_bus.get_history() if e.type == EventType.HITL_UPDATE]
        assert len(events) >= 1
        assert events[0].data["status"] == "running"


# ---------------------------------------------------------------------------
# Run — execution
# ---------------------------------------------------------------------------


class TestRunExecution:
    @pytest.mark.asyncio
    async def test_run_success_returns_result(self, config, event_bus) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)

        runner._execute = AsyncMock(return_value="transcript text")  # type: ignore[method-assign]
        runner._verify_quality = AsyncMock(
            return_value=LoopResult(passed=True, summary="OK")
        )  # type: ignore[method-assign]
        runner._save_transcript = lambda *a: None  # type: ignore[method-assign]

        result = await runner.run(issue, "fix the test", "CI failed", Path("/tmp/wt"))

        assert result.success is True
        assert result.issue_number == 42
        assert result.transcript == "transcript text"
        assert result.duration_seconds > 0
        telemetry = runner._execute.await_args.kwargs["telemetry_stats"]
        assert int(telemetry["pruned_chars_total"]) >= 0

    @pytest.mark.asyncio
    async def test_run_failure_sets_error(self, config, event_bus) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)

        runner._execute = AsyncMock(return_value="transcript text")  # type: ignore[method-assign]
        runner._verify_quality = AsyncMock(  # type: ignore[method-assign]
            return_value=LoopResult(
                passed=False, summary="`make quality` failed:\ntest_foo FAILED"
            )
        )
        runner._save_transcript = lambda *a: None  # type: ignore[method-assign]

        result = await runner.run(issue, "fix the test", "CI failed", Path("/tmp/wt"))

        assert result.success is False
        assert result.error is not None
        assert "make quality" in result.error

    @pytest.mark.asyncio
    async def test_build_prompt_with_stats_prunes_large_guidance(
        self, config, event_bus
    ) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42, body="b" * 200)
        _prompt, stats = await runner._build_prompt_with_stats(
            issue,
            correction="x" * 10_000,
            cause="y" * 6000,
        )
        assert stats["pruned_chars_total"] > 0

    @pytest.mark.asyncio
    async def test_run_exception_sets_error(self, config, event_bus) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)

        runner._execute = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

        result = await runner.run(issue, "fix the test", "CI failed", Path("/tmp/wt"))

        assert result.success is False
        assert result.error == "RuntimeError('boom')"

    @pytest.mark.asyncio
    async def test_run_publishes_start_and_end_events(self, config, event_bus) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)

        runner._execute = AsyncMock(return_value="transcript")  # type: ignore[method-assign]
        runner._verify_quality = AsyncMock(
            return_value=LoopResult(passed=True, summary="OK")
        )  # type: ignore[method-assign]
        runner._save_transcript = lambda *a: None  # type: ignore[method-assign]

        await runner.run(issue, "fix it", "CI failed", Path("/tmp/wt"))

        hitl_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_UPDATE
        ]
        statuses = [e.data["status"] for e in hitl_events]
        assert "running" in statuses
        assert "done" in statuses

    @pytest.mark.asyncio
    async def test_run_failure_publishes_failed_status(self, config, event_bus) -> None:
        runner = HITLRunner(config, event_bus)
        issue = IssueFactory.create(number=42)

        runner._execute = AsyncMock(return_value="transcript")  # type: ignore[method-assign]
        runner._verify_quality = AsyncMock(  # type: ignore[method-assign]
            return_value=LoopResult(passed=False, summary="quality failed")
        )
        runner._save_transcript = lambda *a: None  # type: ignore[method-assign]

        await runner.run(issue, "fix it", "CI failed", Path("/tmp/wt"))

        hitl_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_UPDATE
        ]
        statuses = [e.data["status"] for e in hitl_events]
        assert "failed" in statuses


# ---------------------------------------------------------------------------
# Transcript saving
# ---------------------------------------------------------------------------


class TestSaveTranscript:
    def test_saves_transcript_to_disk(self, hitl_runner, config) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        hitl_runner._save_transcript("hitl-issue", 42, "test transcript content")

        path = config.repo_root / ".hydraflow" / "logs" / "hitl-issue-42.txt"
        assert path.exists()
        assert path.read_text() == "test transcript content"

    def test_save_transcript_handles_oserror(
        self, config: HydraFlowConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = HITLRunner(config, EventBus())

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            runner._save_transcript("hitl-issue", 42, "transcript")  # should not raise

        assert "Could not save transcript" in caplog.text


# ---------------------------------------------------------------------------
# Terminate
# ---------------------------------------------------------------------------


class TestTerminate:
    def test_terminate_with_no_active_procs(self, hitl_runner) -> None:
        assert len(hitl_runner._active_procs) == 0
        hitl_runner.terminate()  # Should not raise

    def test_terminate_calls_terminate_processes(self, hitl_runner) -> None:
        with patch("base_runner.terminate_processes") as mock_term:
            hitl_runner.terminate()
            mock_term.assert_called_once_with(hitl_runner._active_procs)


# ---------------------------------------------------------------------------
# HITLResult model
# ---------------------------------------------------------------------------


class TestHITLResult:
    def test_hitl_result_failure_has_empty_transcript_and_zero_duration(self) -> None:
        result = HITLResultFactory.create(success=False)
        assert result.issue_number == 42
        assert result.success is False
        assert result.error is None
        assert result.transcript == ""
        assert result.duration_seconds == 0.0

    def test_hitl_result_success_sets_true_and_stores_transcript(self) -> None:
        result = HITLResultFactory.create(transcript="done")
        assert result.success is True
        assert result.transcript == "done"


# ---------------------------------------------------------------------------
# _verify_quality — timeout
# ---------------------------------------------------------------------------


class TestVerifyQualityTimeout:
    @pytest.mark.asyncio
    async def test_verify_quality_timeout_returns_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """_verify_quality should return LoopResult(passed=False, ...) when make quality times out."""
        runner = HITLRunner(config, EventBus())

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("asyncio.wait_for", side_effect=TimeoutError),
        ):
            result = await runner._verify_quality(Path("/tmp/wt"))

        assert result.passed is False
        assert "timed out" in result.summary

    @pytest.mark.asyncio
    async def test_verify_quality_timeout_kills_process(
        self, config: HydraFlowConfig
    ) -> None:
        """_verify_quality should kill the process on timeout."""
        runner = HITLRunner(config, EventBus())

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("asyncio.wait_for", side_effect=TimeoutError),
        ):
            await runner._verify_quality(Path("/tmp/wt"))

        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_awaited_once()
