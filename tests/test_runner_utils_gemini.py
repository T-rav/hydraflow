"""Tests for gemini prompt routing and backend detection in runner_utils."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from runner_utils import _route_prompt_to_cmd


def test_route_prompt_splices_after_p_for_gemini() -> None:
    cmd = [
        "gemini",
        "-p",
        "--output-format",
        "stream-json",
        "--model",
        "gemini-3-pro",
    ]
    cmd_to_run, stdin_mode = _route_prompt_to_cmd(cmd, "do the thing")

    p_idx = cmd_to_run.index("-p")
    assert cmd_to_run[p_idx + 1] == "do the thing"
    assert cmd_to_run[p_idx + 2] == "--output-format"
    assert stdin_mode == asyncio.subprocess.DEVNULL


def test_route_prompt_leaves_non_gemini_cmds_alone() -> None:
    cmd = ["pytest", "-v"]
    cmd_to_run, stdin_mode = _route_prompt_to_cmd(cmd, "hello")
    assert cmd_to_run == cmd
    assert stdin_mode == asyncio.subprocess.PIPE
