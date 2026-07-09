"""Tests for the transcript summarization system."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from events import EventType
from execution import SimpleResult
from tests.helpers import ConfigFactory
from transcript_summarizer import (
    TranscriptSummarizer,
    _truncate_transcript,
    build_phase_summary_comment,
    build_transcript_summary_body,
)

# --- build_transcript_summary_body tests ---


class TestBuildTranscriptSummaryBody:
    def test_includes_all_metadata(self) -> None:
        body = build_transcript_summary_body(
            issue_number=42,
            phase="implement",
            summary_content="### Key Decisions\n- Used factory pattern",
            issue_title="Add logging feature",
            duration_seconds=120.5,
        )
        assert "## Transcript Summary" in body
        assert "#42 — Add logging feature" in body
        assert "**Phase:** implement" in body
        assert "**Duration:** 120s" in body
        assert "### Key Decisions" in body
        assert "Used factory pattern" in body

    def test_footer_present(self) -> None:
        body = build_transcript_summary_body(
            issue_number=7,
            phase="review",
            summary_content="Some summary",
        )
        assert "Auto-generated from transcript of issue #7 (review phase)" in body

    def test_no_title(self) -> None:
        body = build_transcript_summary_body(
            issue_number=99,
            phase="plan",
            summary_content="Summary",
        )
        assert "**Issue:** #99" in body
        assert "—" not in body.split("\n")[2]

    def test_no_duration(self) -> None:
        body = build_transcript_summary_body(
            issue_number=1,
            phase="hitl",
            summary_content="Summary",
            duration_seconds=0.0,
        )
        assert "Duration" not in body


# --- build_phase_summary_comment tests ---


class TestBuildPhaseSummaryComment:
    def test_includes_phase_header_status_and_summary(self) -> None:
        body = build_phase_summary_comment(
            phase="implement",
            status="success",
            summary_content="### Key Decisions\n- Used factory pattern",
            duration_seconds=90.0,
            log_file=".hydraflow/logs/issue-42.txt",
        )
        assert "## Phase Summary: Implement" in body
        assert "**Status:** success" in body
        assert "**Duration:** 90s" in body
        assert "### Key Decisions" in body
        assert "Used factory pattern" in body

    def test_includes_collapsible_transcript_reference(self) -> None:
        body = build_phase_summary_comment(
            phase="plan",
            status="success",
            summary_content="Summary",
            log_file=".hydraflow/logs/plan-issue-42.txt",
        )
        assert "<details>" in body
        assert "<summary>Full transcript</summary>" in body
        assert "`.hydraflow/logs/plan-issue-42.txt`" in body
        assert "</details>" in body

    def test_no_log_file_omits_details(self) -> None:
        body = build_phase_summary_comment(
            phase="review",
            status="failed",
            summary_content="Summary",
        )
        assert "<details>" not in body
        assert "Full transcript" not in body

    def test_no_duration_omits_field(self) -> None:
        body = build_phase_summary_comment(
            phase="plan",
            status="success",
            summary_content="Summary",
        )
        assert "Duration" not in body

    def test_footer_present(self) -> None:
        body = build_phase_summary_comment(
            phase="review",
            status="completed",
            summary_content="Summary",
        )
        assert "Auto-generated phase summary (review)" in body


# --- _truncate_transcript tests ---


class TestTruncateTranscript:
    def test_under_limit_unchanged(self) -> None:
        text = "Short transcript"
        result = _truncate_transcript(text, max_chars=1000)
        assert result == text

    def test_over_limit_truncated_from_beginning(self) -> None:
        text = "A" * 100 + "B" * 100
        result = _truncate_transcript(text, max_chars=150)
        # End should be preserved (the Bs)
        assert result.endswith("B" * 100)
        assert "truncated" in result
        assert len(result) <= 150

    def test_empty_transcript(self) -> None:
        result = _truncate_transcript("", max_chars=100)
        assert result == ""

    def test_exactly_at_limit(self) -> None:
        text = "x" * 100
        result = _truncate_transcript(text, max_chars=100)
        assert result == text


# --- Helpers for mock runner ---


def _make_mock_runner(
    *, stdout: str = "", stderr: str = "", returncode: int = 0
) -> AsyncMock:
    """Build a mock SubprocessRunner whose run_simple returns a SimpleResult."""
    runner = AsyncMock()
    runner.run_simple = AsyncMock(
        return_value=SimpleResult(stdout=stdout, stderr=stderr, returncode=returncode)
    )
    return runner


# --- TranscriptSummarizer.summarize_and_comment tests ---


class TestSummarizeAndComment:
    @pytest.mark.asyncio
    async def test_happy_path_posts_comment(self, tmp_path: Path) -> None:
        """Model returns summary, post_comment called on correct issue."""
        config = ConfigFactory.create(repo_root=tmp_path)
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        bus.publish = AsyncMock()
        state = MagicMock()
        runner = _make_mock_runner(stdout="### Key Decisions\n- Used factory pattern")

        summarizer = TranscriptSummarizer(config, prs, bus, state, runner=runner)
        result = await summarizer.summarize_and_comment(
            transcript="x" * 1000,
            issue_number=42,
            phase="implement",
            status="success",
            duration_seconds=60.0,
            log_file=".hydraflow/logs/issue-42.txt",
        )

        assert result is True
        prs.post_comment.assert_awaited_once()
        call_args = prs.post_comment.call_args
        assert call_args[0][0] == 42
        body = call_args[0][1]
        assert "Phase Summary: Implement" in body
        assert "**Status:** success" in body
        assert "Key Decisions" in body

    @pytest.mark.asyncio
    async def test_emits_transcript_summary_event(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        bus.publish = AsyncMock()
        state = MagicMock()
        runner = _make_mock_runner(stdout="Summary")

        summarizer = TranscriptSummarizer(config, prs, bus, state, runner=runner)
        await summarizer.summarize_and_comment(
            transcript="x" * 1000,
            issue_number=42,
            phase="review",
        )

        bus.publish.assert_called_once()
        event = bus.publish.call_args[0][0]
        assert event.type == EventType.TRANSCRIPT_SUMMARY
        assert event.data["source_issue"] == 42
        assert event.data["phase"] == "review"
        assert event.data["posted_as"] == "comment"

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path, transcript_summarization_enabled=False
        )
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        state = MagicMock()

        summarizer = TranscriptSummarizer(config, prs, bus, state)
        result = await summarizer.summarize_and_comment(
            transcript="x" * 1000, issue_number=42, phase="implement"
        )

        assert result is False
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_empty_transcript(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        state = MagicMock()

        summarizer = TranscriptSummarizer(config, prs, bus, state)

        for empty in ("", "   ", "\n\n"):
            result = await summarizer.summarize_and_comment(
                transcript=empty, issue_number=42, phase="implement"
            )
            assert result is False

        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_short_transcript(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        state = MagicMock()

        summarizer = TranscriptSummarizer(config, prs, bus, state)
        result = await summarizer.summarize_and_comment(
            transcript="x" * 499, issue_number=42, phase="implement"
        )

        assert result is False
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_model_failure(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        state = MagicMock()
        runner = _make_mock_runner(returncode=1, stderr="error")

        summarizer = TranscriptSummarizer(config, prs, bus, state, runner=runner)
        result = await summarizer.summarize_and_comment(
            transcript="x" * 1000, issue_number=42, phase="implement"
        )

        assert result is False
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_post_comment_failure(self, tmp_path: Path) -> None:
        """post_comment raises, but summarize_and_comment returns False (no crash)."""
        config = ConfigFactory.create(repo_root=tmp_path)
        prs = MagicMock()
        prs.post_comment = AsyncMock(side_effect=RuntimeError("network error"))
        bus = MagicMock()
        bus.publish = AsyncMock()
        state = MagicMock()
        runner = _make_mock_runner(stdout="Summary")

        summarizer = TranscriptSummarizer(config, prs, bus, state, runner=runner)
        result = await summarizer.summarize_and_comment(
            transcript="x" * 1000, issue_number=42, phase="implement"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_handles_timeout(self, tmp_path: Path) -> None:
        """Model timeout causes summarize_and_comment to return False (no crash)."""
        config = ConfigFactory.create(repo_root=tmp_path)
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        state = MagicMock()
        runner = AsyncMock()
        runner.run_simple = AsyncMock(side_effect=TimeoutError)

        summarizer = TranscriptSummarizer(config, prs, bus, state, runner=runner)
        result = await summarizer.summarize_and_comment(
            transcript="x" * 1000, issue_number=42, phase="implement"
        )

        assert result is False
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_subprocess_error(self, tmp_path: Path) -> None:
        """Missing claude binary causes summarize_and_comment to return False (no crash)."""
        config = ConfigFactory.create(repo_root=tmp_path)
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        state = MagicMock()
        runner = AsyncMock()
        runner.run_simple = AsyncMock(side_effect=FileNotFoundError("claude not found"))

        summarizer = TranscriptSummarizer(config, prs, bus, state, runner=runner)
        result = await summarizer.summarize_and_comment(
            transcript="x" * 1000, issue_number=42, phase="implement"
        )

        assert result is False
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_configured_timeout(self, tmp_path: Path) -> None:
        """run_simple is called with timeout from config.transcript_summary_timeout."""
        config = ConfigFactory.create(
            repo_root=tmp_path, transcript_summary_timeout=300
        )
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        bus.publish = AsyncMock()
        state = MagicMock()
        runner = _make_mock_runner(stdout="Summary")

        summarizer = TranscriptSummarizer(config, prs, bus, state, runner=runner)
        await summarizer.summarize_and_comment(
            transcript="x" * 1000, issue_number=42, phase="implement"
        )

        runner.run_simple.assert_awaited_once()
        call_kwargs = runner.run_simple.call_args[1]
        assert call_kwargs["timeout"] == 300

    @pytest.mark.asyncio
    async def test_calls_run_simple_not_raw_subprocess(self, tmp_path: Path) -> None:
        """Verify run_simple is used and prompt is passed as CLI arg (not stdin)."""
        config = ConfigFactory.create(repo_root=tmp_path)
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        bus.publish = AsyncMock()
        state = MagicMock()
        runner = _make_mock_runner(stdout="Summary")

        summarizer = TranscriptSummarizer(config, prs, bus, state, runner=runner)
        await summarizer.summarize_and_comment(
            transcript="x" * 1000, issue_number=42, phase="implement"
        )

        runner.run_simple.assert_awaited_once()
        call_args = runner.run_simple.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "claude"
        assert cmd[1] == "-p"
        # Prompt must be immediately after -p for the CLI to recognise it.
        assert cmd[2] not in ("--model",), "prompt must follow -p, not a flag"
        assert call_args[1].get("input") is None

    @pytest.mark.asyncio
    async def test_codex_tool_passes_prompt_as_cli_arg(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path,
            transcript_summary_tool="codex",
            transcript_summary_model="gpt-5-codex",
        )
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        bus.publish = AsyncMock()
        state = MagicMock()
        runner = _make_mock_runner(stdout="Summary")

        summarizer = TranscriptSummarizer(config, prs, bus, state, runner=runner)
        await summarizer.summarize_and_comment(
            transcript="x" * 1000, issue_number=42, phase="implement"
        )

        runner.run_simple.assert_awaited_once()
        call_args = runner.run_simple.call_args[0][0]
        call_kwargs = runner.run_simple.call_args[1]
        assert call_args[:3] == ["codex", "exec", "--json"]
        assert call_args[call_args.index("--model") + 1] == "gpt-5-codex"
        assert "--skip-git-repo-check" in call_args
        assert call_args[-1]
        assert call_kwargs["input"] is None


# Note: TestSummarizeAndPublish removed — method was a deprecated no-op, now deleted.
# Note: TestExtractAndFileMemoryItems was removed in the tribal-memory rollout
# (2026-04-07). Transcript-summary auto-filing was removed because the bullets
# routinely produced implementation-detail noise below the tribal-knowledge bar.
# Use the explicit tribal_recorder tool to deliberately preserve hard-won facts.


# --- CH-6 issue-label threading (#9734 convergence review finding 1) ---


class TestIssueLabelThreading:
    """summarize_and_comment threads issue labels down to the prompt gate."""

    @staticmethod
    def _make(config):
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        bus.publish = AsyncMock()
        state = MagicMock()
        runner = _make_mock_runner(stdout="Summary")
        return TranscriptSummarizer(config, prs, bus, state, runner=runner), runner

    @pytest.mark.asyncio
    async def test_elevating_label_blocks_spawn_on_internal_repo(
        self, tmp_path: Path
    ) -> None:
        """A data-class label elevates the gate: no backend allowed → no spawn."""
        config = ConfigFactory.create(repo_root=tmp_path).model_copy(
            update={"data_class_allowed_backends": {}}
        )
        summarizer, runner = self._make(config)

        result = await summarizer.summarize_and_comment(
            transcript="x" * 1000,
            issue_number=42,
            phase="implement",
            issue_labels=["data-class:regulated-phi"],
        )

        assert result is False
        runner.run_simple.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_labels_spawns_normally_on_internal_repo(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path).model_copy(
            update={"data_class_allowed_backends": {}}
        )
        summarizer, runner = self._make(config)

        result = await summarizer.summarize_and_comment(
            transcript="x" * 1000, issue_number=42, phase="implement"
        )

        assert result is True
        runner.run_simple.assert_awaited_once()


# --- Prompt-gate block escalation (#9734 review finding 3 adoption) ---


class TestGateBlockEscalation:
    """A gate-blocked _call_model must escalate loudly, once per condition."""

    @staticmethod
    def _configs(tmp_path: Path):
        base = ConfigFactory.create(repo_root=tmp_path / "repo")
        blocked = base.model_copy(
            update={
                "repo_data_class": "regulated-phi",
                "data_class_allowed_backends": {},
            }
        )
        allowed = base.model_copy(
            update={
                "repo_data_class": "regulated-phi",
                "data_class_allowed_backends": {"regulated-phi": ["claude"]},
            }
        )
        return blocked, allowed

    @staticmethod
    def _make(config):
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        bus = MagicMock()
        bus.publish = AsyncMock()
        state = MagicMock()
        runner = MagicMock()
        runner.run_simple = AsyncMock()
        summarizer = TranscriptSummarizer(config, prs, bus, state, runner=runner)
        return summarizer, bus, runner

    @pytest.mark.asyncio
    async def test_block_logs_error_and_alerts_once_across_two_ticks(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        blocked, _ = self._configs(tmp_path)
        summarizer, bus, runner = self._make(blocked)

        with caplog.at_level(logging.ERROR, logger="hydraflow.prompt_gate_alerts"):
            assert await summarizer._call_model("prompt one") is None
            assert await summarizer._call_model("prompt two") is None

        runner.run_simple.assert_not_awaited()  # blocked BEFORE any spawn
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 2  # loud on every blocked tick
        assert bus.publish.await_count == 1  # SYSTEM_ALERT deduped
        event = bus.publish.await_args_list[0].args[0]
        assert event.type == EventType.SYSTEM_ALERT
        assert event.data["kind"] == "prompt_gate_blocked"
        assert event.data["source"] == "transcript_summary"
        assert event.data["repo"] == blocked.repo

    @pytest.mark.asyncio
    async def test_dedup_cleared_on_success_then_realerts(self, tmp_path: Path) -> None:
        blocked, allowed = self._configs(tmp_path)
        summarizer, bus, runner = self._make(blocked)

        assert await summarizer._call_model("p") is None  # block -> alert #1
        assert bus.publish.await_count == 1

        summarizer._config = allowed
        runner.run_simple = AsyncMock(
            return_value=SimpleResult(returncode=0, stdout="ok")
        )
        assert await summarizer._call_model("p") == "ok"  # success clears dedup

        summarizer._config = blocked
        assert await summarizer._call_model("p") is None  # new block -> alert #2
        assert bus.publish.await_count == 2

    @pytest.mark.asyncio
    async def test_generic_failure_still_soft_warns_without_alert(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A transient rc!=0 keeps the old soft-failure path: no SYSTEM_ALERT."""
        import logging

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        summarizer, bus, runner = self._make(config)
        runner.run_simple = AsyncMock(
            return_value=SimpleResult(returncode=1, stderr="boom")
        )

        with caplog.at_level(logging.WARNING, logger="hydraflow.transcript_summarizer"):
            assert await summarizer._call_model("p") is None

        bus.publish.assert_not_awaited()
        assert any("rc=1" in r.getMessage() for r in caplog.records)
