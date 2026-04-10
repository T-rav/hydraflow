"""Tests for _route_prompt_to_cmd — pure function extracted from stream_claude_process."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from runner_utils import _route_prompt_to_cmd


class TestClaudePrintMode:
    """Claude -p flag: prompt inserted immediately after -p."""

    def test_prompt_inserted_after_p_flag(self) -> None:
        cmd = ["claude", "-p", "--output-format", "stream-json"]
        prompt = "evaluate this"
        result_cmd, stdin_mode = _route_prompt_to_cmd(cmd, prompt)
        p_idx = result_cmd.index("-p")
        assert result_cmd[p_idx + 1] == prompt
        assert stdin_mode == asyncio.subprocess.DEVNULL

    def test_prompt_does_not_corrupt_disallowed_tools(self) -> None:
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--disallowedTools",
            "Write,Edit,NotebookEdit",
        ]
        prompt = "Plan this issue: " + "x" * 100
        result_cmd, stdin_mode = _route_prompt_to_cmd(cmd, prompt)
        p_idx = result_cmd.index("-p")
        assert result_cmd[p_idx + 1] == prompt
        dt_idx = result_cmd.index("--disallowedTools")
        assert result_cmd[dt_idx + 1] == "Write,Edit,NotebookEdit"
        assert stdin_mode == asyncio.subprocess.DEVNULL


class TestPiPrintMode:
    """Pi -p / --print flag: prompt inserted immediately after flag."""

    def test_pi_p_flag_inserts_prompt(self) -> None:
        cmd = ["pi", "-p", "--mode", "json"]
        prompt = "do the thing"
        result_cmd, stdin_mode = _route_prompt_to_cmd(cmd, prompt)
        p_idx = result_cmd.index("-p")
        assert result_cmd[p_idx + 1] == prompt
        assert stdin_mode == asyncio.subprocess.DEVNULL

    def test_pi_print_flag_inserts_prompt(self) -> None:
        cmd = ["pi", "--print", "--mode", "json"]
        prompt = "do the thing"
        result_cmd, stdin_mode = _route_prompt_to_cmd(cmd, prompt)
        p_idx = result_cmd.index("--print")
        assert result_cmd[p_idx + 1] == prompt
        assert stdin_mode == asyncio.subprocess.DEVNULL


class TestCodexExecMode:
    """Codex exec: prompt appended as trailing positional argument."""

    def test_codex_exec_appends_prompt(self) -> None:
        cmd = ["codex", "exec", "--json", "--model", "gpt-5.3"]
        prompt = "do the thing"
        result_cmd, stdin_mode = _route_prompt_to_cmd(cmd, prompt)
        assert result_cmd[-1] == prompt
        assert stdin_mode == asyncio.subprocess.DEVNULL


class TestStdinFallback:
    """No recognized flag: cmd unchanged, stdin=PIPE."""

    def test_stdin_fallback_for_unknown_command(self) -> None:
        cmd = ["claude", "--verbose"]
        prompt = "hello"
        result_cmd, stdin_mode = _route_prompt_to_cmd(cmd, prompt)
        assert result_cmd == cmd
        assert stdin_mode == asyncio.subprocess.PIPE

    def test_empty_cmd_returns_pipe(self) -> None:
        result_cmd, stdin_mode = _route_prompt_to_cmd([], "hello")
        assert result_cmd == []
        assert stdin_mode == asyncio.subprocess.PIPE
