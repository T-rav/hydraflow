"""Tests for runner_utils.py extracted helper functions."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from runner_utils import (
    AuthenticationRetryError,
    create_agent_process,
    feed_stdin,
    prepare_command,
    read_and_publish_stream,
    validate_post_stream,
)
from subprocess_util import CreditExhaustedError

# ---------------------------------------------------------------------------
# prepare_command
# ---------------------------------------------------------------------------


class TestPrepareCommand:
    """Tests for prepare_command."""

    def test_claude_print_inserts_prompt_after_flag(self) -> None:
        cmd = ["claude", "-p", "--model", "sonnet"]
        cmd_out, use_arg = prepare_command(cmd, "hello")
        assert use_arg is True
        assert cmd_out == ["claude", "-p", "hello", "--model", "sonnet"]

    def test_codex_exec_appends_prompt(self) -> None:
        cmd = ["codex", "exec"]
        cmd_out, use_arg = prepare_command(cmd, "prompt text")
        assert use_arg is True
        assert cmd_out == ["codex", "exec", "prompt text"]

    def test_pi_print_inserts_prompt(self) -> None:
        cmd = ["pi", "-p"]
        cmd_out, use_arg = prepare_command(cmd, "ask")
        assert use_arg is True
        assert cmd_out == ["pi", "-p", "ask"]

    def test_pi_long_flag_inserts_prompt(self) -> None:
        cmd = ["pi", "--print", "--model", "x"]
        cmd_out, use_arg = prepare_command(cmd, "ask")
        assert use_arg is True
        assert cmd_out == ["pi", "--print", "ask", "--model", "x"]

    def test_unknown_command_uses_stdin(self) -> None:
        cmd = ["other-tool", "--flag"]
        cmd_out, use_arg = prepare_command(cmd, "prompt")
        assert use_arg is False
        assert cmd_out == ["other-tool", "--flag"]

    def test_empty_command(self) -> None:
        cmd_out, use_arg = prepare_command([], "prompt")
        assert use_arg is False
        assert cmd_out == []


# ---------------------------------------------------------------------------
# validate_post_stream
# ---------------------------------------------------------------------------


class TestValidatePostStream:
    """Tests for validate_post_stream."""

    def _make_parser(self) -> MagicMock:
        parser = MagicMock()
        parser.usage_snapshot = {"total_tokens": 100}
        return parser

    def test_returns_result_text_first(self) -> None:
        transcript = validate_post_stream(
            raw_lines=["line1"],
            stderr_text="",
            accumulated_text="accumulated",
            result_text="result",
            early_killed=False,
            returncode=0,
            parser=self._make_parser(),
            logger=logging.getLogger("test"),
            usage_stats=None,
        )
        assert transcript == "result"

    def test_falls_back_to_accumulated(self) -> None:
        transcript = validate_post_stream(
            raw_lines=["line1"],
            stderr_text="",
            accumulated_text="accumulated\n",
            result_text="",
            early_killed=False,
            returncode=0,
            parser=self._make_parser(),
            logger=logging.getLogger("test"),
            usage_stats=None,
        )
        assert transcript == "accumulated"

    def test_falls_back_to_raw_lines(self) -> None:
        transcript = validate_post_stream(
            raw_lines=["raw1", "raw2"],
            stderr_text="",
            accumulated_text="",
            result_text="",
            early_killed=False,
            returncode=0,
            parser=self._make_parser(),
            logger=logging.getLogger("test"),
            usage_stats=None,
        )
        assert transcript == "raw1\nraw2"

    def test_raises_auth_error(self) -> None:
        with pytest.raises(AuthenticationRetryError):
            validate_post_stream(
                raw_lines=['{"error":"authentication_failed"}'],
                stderr_text="",
                accumulated_text="",
                result_text="",
                early_killed=False,
                returncode=1,
                parser=self._make_parser(),
                logger=logging.getLogger("test"),
                usage_stats=None,
            )

    def test_skips_auth_check_when_early_killed(self) -> None:
        # Should NOT raise even though auth_failed is present
        transcript = validate_post_stream(
            raw_lines=['{"error":"authentication_failed"}'],
            stderr_text="",
            accumulated_text="output\n",
            result_text="",
            early_killed=True,
            returncode=-9,
            parser=self._make_parser(),
            logger=logging.getLogger("test"),
            usage_stats=None,
        )
        assert transcript == "output"

    def test_raises_credit_exhausted(self) -> None:
        with pytest.raises(CreditExhaustedError):
            validate_post_stream(
                raw_lines=[],
                stderr_text="Your credit balance is too low",
                accumulated_text="",
                result_text="",
                early_killed=False,
                returncode=1,
                parser=self._make_parser(),
                logger=logging.getLogger("test"),
                usage_stats=None,
            )

    def test_skips_credit_check_when_early_killed(self) -> None:
        transcript = validate_post_stream(
            raw_lines=[],
            stderr_text="Your credit balance is too low",
            accumulated_text="result\n",
            result_text="",
            early_killed=True,
            returncode=-9,
            parser=self._make_parser(),
            logger=logging.getLogger("test"),
            usage_stats=None,
        )
        assert transcript == "result"

    def test_updates_usage_stats(self) -> None:
        stats: dict[str, object] = {}
        validate_post_stream(
            raw_lines=["x"],
            stderr_text="",
            accumulated_text="text\n",
            result_text="",
            early_killed=False,
            returncode=0,
            parser=self._make_parser(),
            logger=logging.getLogger("test"),
            usage_stats=stats,
        )
        assert "total_tokens" in stats

    def test_logs_stderr_when_transcript_empty(self) -> None:
        mock_logger = MagicMock()
        validate_post_stream(
            raw_lines=[],
            stderr_text="error details",
            accumulated_text="",
            result_text="",
            early_killed=False,
            returncode=1,
            parser=self._make_parser(),
            logger=mock_logger,
            usage_stats=None,
        )
        mock_logger.warning.assert_called()

    def test_logs_nonzero_exit_code(self) -> None:
        mock_logger = MagicMock()
        validate_post_stream(
            raw_lines=[],
            stderr_text="error",
            accumulated_text="output\n",
            result_text="",
            early_killed=False,
            returncode=1,
            parser=self._make_parser(),
            logger=mock_logger,
            usage_stats=None,
        )
        assert any(
            "exited with code" in str(c) for c in mock_logger.warning.call_args_list
        )


# ---------------------------------------------------------------------------
# create_agent_process
# ---------------------------------------------------------------------------


class TestCreateAgentProcess:
    """Tests for create_agent_process."""

    @pytest.mark.asyncio
    async def test_creates_process_with_prompt_arg(self) -> None:
        mock_runner = MagicMock()
        mock_proc = MagicMock()
        mock_runner.create_streaming_process = AsyncMock(return_value=mock_proc)

        proc, use_prompt = await create_agent_process(
            cmd=["claude", "-p"],
            prompt="hello",
            cwd=Path("/tmp"),
            runner=mock_runner,
        )
        assert proc is mock_proc
        assert use_prompt is True
        mock_runner.create_streaming_process.assert_awaited_once()
        # Verify stdin is DEVNULL when prompt is in args
        call_kwargs = mock_runner.create_streaming_process.call_args[1]
        assert call_kwargs["stdin"] == asyncio.subprocess.DEVNULL

    @pytest.mark.asyncio
    async def test_creates_process_with_stdin(self) -> None:
        mock_runner = MagicMock()
        mock_proc = MagicMock()
        mock_runner.create_streaming_process = AsyncMock(return_value=mock_proc)

        proc, use_prompt = await create_agent_process(
            cmd=["other-tool"],
            prompt="hello",
            cwd=Path("/tmp"),
            runner=mock_runner,
        )
        assert proc is mock_proc
        assert use_prompt is False
        call_kwargs = mock_runner.create_streaming_process.call_args[1]
        assert call_kwargs["stdin"] == asyncio.subprocess.PIPE


# ---------------------------------------------------------------------------
# feed_stdin
# ---------------------------------------------------------------------------


class TestFeedStdin:
    """Tests for feed_stdin."""

    @pytest.mark.asyncio
    async def test_writes_and_closes(self) -> None:
        mock_stdin = MagicMock()
        mock_stdin.drain = AsyncMock()
        mock_proc = MagicMock()
        mock_proc.stdin = mock_stdin

        await feed_stdin(mock_proc, "test prompt")

        mock_stdin.write.assert_called_once_with(b"test prompt")
        mock_stdin.drain.assert_awaited_once()
        mock_stdin.close.assert_called_once()


# ---------------------------------------------------------------------------
# read_and_publish_stream
# ---------------------------------------------------------------------------


class TestReadAndPublishStream:
    """Tests for read_and_publish_stream."""

    @pytest.mark.asyncio
    async def test_reads_stdout_and_returns_transcript(self, event_bus) -> None:
        mock_proc = MagicMock()
        # Simulate stdout with stream-json lines
        lines = [
            b'{"type":"text","text":"hello"}\n',
            b'{"type":"text","text":"world"}\n',
        ]

        async def _aiter():
            for line in lines:
                yield line

        mock_proc.stdout = _aiter()
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock()

        async def _empty_stderr() -> bytes:
            return b""

        stderr_task = asyncio.create_task(_empty_stderr())

        with patch("runner_utils.StreamParser") as MockParser:
            parser_inst = MockParser.return_value
            parser_inst.parse.side_effect = [("hello", None), ("world", None)]
            parser_inst.usage_snapshot = {}

            transcript = await read_and_publish_stream(
                proc=mock_proc,
                stderr_task=stderr_task,
                event_bus=event_bus,
                event_data={"issue": 1, "source": "test"},
                logger=logging.getLogger("test"),
            )

        assert "hello" in transcript
        assert "world" in transcript

    @pytest.mark.asyncio
    async def test_early_kill_on_output_callback(self, event_bus) -> None:
        mock_proc = MagicMock()
        lines = [b"line1\n", b"line2\n"]

        async def _aiter():
            for line in lines:
                yield line

        mock_proc.stdout = _aiter()
        mock_proc.returncode = -9
        mock_proc.wait = AsyncMock()
        mock_proc.kill = MagicMock()

        async def _empty_stderr() -> bytes:
            return b""

        stderr_task = asyncio.create_task(_empty_stderr())

        with patch("runner_utils.StreamParser") as MockParser:
            parser_inst = MockParser.return_value
            parser_inst.parse.return_value = ("display", None)
            parser_inst.usage_snapshot = {}

            await read_and_publish_stream(
                proc=mock_proc,
                stderr_task=stderr_task,
                event_bus=event_bus,
                event_data={"issue": 1, "source": "test"},
                on_output=lambda _: True,  # Always signal kill
                logger=logging.getLogger("test"),
            )

        mock_proc.kill.assert_called_once()
