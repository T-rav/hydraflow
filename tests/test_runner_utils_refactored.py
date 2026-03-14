"""Tests for runner_utils.py extracted helper functions."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from runner_utils import (
    AuthenticationRetryError,
    prepare_command,
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
