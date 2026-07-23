"""Tests for execution.py — SubprocessRunner protocol and HostRunner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from execution import HostRunner, SimpleResult, SubprocessRunner, get_default_runner

# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestSubprocessRunnerProtocol:
    """Verify the SubprocessRunner protocol is runtime-checkable."""

    def test_host_runner_is_subprocess_runner(self) -> None:
        runner = HostRunner()
        assert isinstance(runner, SubprocessRunner)

    def test_mock_implementing_both_methods_satisfies_protocol(self) -> None:
        mock = AsyncMock(spec=SubprocessRunner)
        assert isinstance(mock, SubprocessRunner)


# ---------------------------------------------------------------------------
# SimpleResult
# ---------------------------------------------------------------------------


class TestSimpleResult:
    """SimpleResult dataclass tests."""

    def test_simple_result_stores_stdout_stderr_and_returncode(self) -> None:
        result = SimpleResult(stdout="hello", stderr="", returncode=0)
        assert result.stdout == "hello"
        assert result.stderr == ""
        assert result.returncode == 0

    def test_non_zero_returncode(self) -> None:
        result = SimpleResult(stdout="", stderr="error", returncode=1)
        assert result.returncode == 1
        assert result.stderr == "error"


# ---------------------------------------------------------------------------
# HostRunner.create_streaming_process
# ---------------------------------------------------------------------------


class TestHostRunnerCreateStreamingProcess:
    @pytest.mark.asyncio
    async def test_calls_create_subprocess_exec_with_correct_args(self) -> None:
        mock_proc = AsyncMock()
        mock_create = AsyncMock(return_value=mock_proc)

        runner = HostRunner()
        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await runner.create_streaming_process(
                ["claude", "-p"],
                cwd="/tmp/work",
                env={"FOO": "bar"},
                limit=1024 * 1024,
                start_new_session=True,
            )

        assert result is mock_proc
        mock_create.assert_called_once_with(
            "claude",
            "-p",
            cwd="/tmp/work",
            env={"FOO": "bar"},
            stdin=None,
            stdout=None,
            stderr=None,
            limit=1024 * 1024,
            start_new_session=True,
        )

    @pytest.mark.asyncio
    async def test_cwd_none_when_not_given(self) -> None:
        mock_proc = AsyncMock()
        mock_create = AsyncMock(return_value=mock_proc)

        runner = HostRunner()
        with patch("asyncio.create_subprocess_exec", mock_create):
            await runner.create_streaming_process(["echo", "hi"])

        _, kwargs = mock_create.call_args
        assert kwargs["cwd"] is None

    @pytest.mark.asyncio
    async def test_default_limit_and_start_new_session(self) -> None:
        mock_proc = AsyncMock()
        mock_create = AsyncMock(return_value=mock_proc)

        runner = HostRunner()
        with patch("asyncio.create_subprocess_exec", mock_create):
            await runner.create_streaming_process(["echo", "hi"])

        _, kwargs = mock_create.call_args
        assert kwargs["limit"] == 1024 * 1024
        assert kwargs["start_new_session"] is True

    @pytest.mark.asyncio
    async def test_custom_env_forwarded(self) -> None:
        mock_proc = AsyncMock()
        mock_create = AsyncMock(return_value=mock_proc)

        runner = HostRunner()
        env = {"PATH": "/usr/bin", "HOME": "/root"}
        with patch("asyncio.create_subprocess_exec", mock_create):
            await runner.create_streaming_process(["ls"], env=env)

        _, kwargs = mock_create.call_args
        assert kwargs["env"] == env


# ---------------------------------------------------------------------------
# HostRunner.run_simple
# ---------------------------------------------------------------------------


class TestHostRunnerRunSimple:
    @pytest.mark.asyncio
    async def test_success_returns_simple_result(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"  output  ", b""))

        runner = HostRunner()
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await runner.run_simple(["echo", "hi"])

        assert isinstance(result, SimpleResult)
        assert result.stdout == "output"
        assert result.stderr == ""
        assert result.returncode == 0

    @pytest.mark.asyncio
    async def test_non_zero_exit_returns_correct_returncode(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error msg"))

        runner = HostRunner()
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await runner.run_simple(["false"])

        assert result.returncode == 1
        assert result.stderr == "error msg"

    @pytest.mark.asyncio
    async def test_timeout_reaps_process_group_and_raises(self) -> None:
        """On timeout the WHOLE process group is reaped, not just the child.

        Regression for #9648: run_simple previously called ``proc.kill()`` on
        timeout, which only reaps the direct child and orphans sub-make / pytest
        / agent grandchildren. With ``start_new_session=True`` the child is a
        group leader (pid == pgid), so ``os.killpg(proc.pid, SIGKILL)`` tears
        down the entire tree.
        """
        mock_proc = MagicMock()
        mock_proc.pid = 4242
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        runner = HostRunner()
        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)),
            patch("process_group.os.killpg") as mock_killpg,
            pytest.raises(TimeoutError),
        ):
            await runner.run_simple(["sleep", "999"], timeout=0.01)

        import signal

        mock_killpg.assert_called_once_with(4242, signal.SIGKILL)
        # The direct child must not be killed individually — the group kill covers it.
        mock_proc.kill.assert_not_called()
        mock_proc.wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_falls_back_to_kill_when_no_pid(self) -> None:
        """When proc.pid is None there is no group to reap; fall back to kill()."""
        mock_proc = MagicMock()
        mock_proc.pid = None
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        runner = HostRunner()
        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)),
            patch("process_group.os.killpg") as mock_killpg,
            pytest.raises(TimeoutError),
        ):
            await runner.run_simple(["sleep", "999"], timeout=0.01)

        mock_killpg.assert_not_called()
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_suppresses_process_lookup_error(self) -> None:
        """If the group already exited, killpg raises ProcessLookupError; the
        TimeoutError (the intended signal) must still propagate. (#9794/#9814)"""
        mock_proc = MagicMock()
        mock_proc.pid = 4242
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        runner = HostRunner()
        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)),
            patch("process_group.os.killpg", side_effect=ProcessLookupError),
            pytest.raises(TimeoutError),
        ):
            await runner.run_simple(["sleep", "999"], timeout=0.01)

    @pytest.mark.asyncio
    async def test_timeout_non_int_pid_falls_back_to_kill(self) -> None:
        """A non-int pid must NOT reach os.killpg — the reap falls back to
        proc.kill(). This guards the central run_simple path against firing a
        real killpg at a fabricated pid: a mock pid int-coerces to 1, which
        would signal an unrelated — possibly our own — process group and, in a
        root CI container, SIGKILL PID 1 and hang the job. (#9648)"""
        mock_proc = MagicMock()
        mock_proc.pid = MagicMock()  # not an int (e.g. a test double / mock)
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        runner = HostRunner()
        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)),
            patch("process_group.os.killpg") as mock_killpg,
            pytest.raises(TimeoutError),
        ):
            await runner.run_simple(["sleep", "999"], timeout=0.01)

        mock_killpg.assert_not_called()
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancellation_reaps_process_group(self) -> None:
        """External cancellation (e.g. a loop watchdog) must reap the whole
        process group too, not orphan the child and its grandchildren — the
        #9648 defect on the cancel trigger rather than the timeout one. Shared
        reap mirrors stream_claude_process's TimeoutError/cancel handling."""
        import asyncio
        import signal

        mock_proc = MagicMock()
        mock_proc.pid = 4242
        mock_proc.communicate = AsyncMock(side_effect=asyncio.CancelledError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        runner = HostRunner()
        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)),
            patch("process_group.os.killpg") as mock_killpg,
            pytest.raises(asyncio.CancelledError),
        ):
            await runner.run_simple(["sleep", "999"], timeout=999)

        mock_killpg.assert_called_once_with(4242, signal.SIGKILL)
        mock_proc.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_spawn_uses_start_new_session(self) -> None:
        """run_simple must spawn with start_new_session=True so the child owns a
        process group that can be reaped as a unit on timeout. (#9648)"""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_create = AsyncMock(return_value=mock_proc)

        runner = HostRunner()
        with patch("asyncio.create_subprocess_exec", mock_create):
            await runner.run_simple(["echo", "hi"])

        _, kwargs = mock_create.call_args
        assert kwargs["start_new_session"] is True

    @pytest.mark.asyncio
    async def test_cwd_forwarded(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_create = AsyncMock(return_value=mock_proc)

        runner = HostRunner()
        with patch("asyncio.create_subprocess_exec", mock_create):
            await runner.run_simple(["ls"], cwd="/tmp/dir")

        _, kwargs = mock_create.call_args
        assert kwargs["cwd"] == "/tmp/dir"

    @pytest.mark.asyncio
    async def test_env_forwarded(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_create = AsyncMock(return_value=mock_proc)

        runner = HostRunner()
        env = {"MY_VAR": "123"}
        with patch("asyncio.create_subprocess_exec", mock_create):
            await runner.run_simple(["env"], env=env)

        _, kwargs = mock_create.call_args
        assert kwargs["env"] == env

    @pytest.mark.asyncio
    async def test_stdout_stderr_are_stripped(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(b"\n  hello world  \n", b"  warn  \n")
        )

        runner = HostRunner()
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await runner.run_simple(["echo"])

        assert result.stdout == "hello world"
        assert result.stderr == "warn"

    @pytest.mark.asyncio
    async def test_file_not_found_propagates(self) -> None:
        """FileNotFoundError from create_subprocess_exec must propagate to the caller."""
        runner = HostRunner()
        with (
            patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError),
            pytest.raises(FileNotFoundError),
        ):
            await runner.run_simple(["nonexistent-binary"])

    @pytest.mark.asyncio
    async def test_input_opens_stdin_pipe_and_passes_data(self) -> None:
        """When input is provided, stdin=PIPE and data is forwarded to communicate."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"response", b""))
        mock_create = AsyncMock(return_value=mock_proc)

        runner = HostRunner()
        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await runner.run_simple(["cat"], input=b"hello world")

        # Verify stdin pipe was opened
        _, kwargs = mock_create.call_args
        import asyncio

        assert kwargs["stdin"] == asyncio.subprocess.PIPE

        # Verify input was passed to communicate
        mock_proc.communicate.assert_called_once_with(input=b"hello world")
        assert result.stdout == "response"

    @pytest.mark.asyncio
    async def test_no_input_does_not_open_stdin_pipe(self) -> None:
        """When input is None (default), stdin should be None."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
        mock_create = AsyncMock(return_value=mock_proc)

        runner = HostRunner()
        with patch("asyncio.create_subprocess_exec", mock_create):
            await runner.run_simple(["echo", "hi"])

        _, kwargs = mock_create.call_args
        assert kwargs["stdin"] is None

    @pytest.mark.asyncio
    async def test_non_utf8_bytes_are_replaced_not_raised(self) -> None:
        """Non-UTF-8 bytes must be replaced, not raise UnicodeDecodeError."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        # \xff\xfe is invalid in UTF-8 (valid only in UTF-16 BOM context)
        mock_proc.communicate = AsyncMock(
            return_value=(b"\xff\xfe bad output", b"\xff")
        )

        runner = HostRunner()
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await runner.run_simple(["make", "quality"])

        assert result.returncode == 1
        assert "\ufffd" in result.stdout  # replacement character present
        assert "\ufffd" in result.stderr


# ---------------------------------------------------------------------------
# get_default_runner
# ---------------------------------------------------------------------------


class TestGetDefaultRunner:
    def test_returns_host_runner(self) -> None:
        import execution

        # Reset singleton to ensure clean state
        execution._default_runner = None
        runner = get_default_runner()
        assert isinstance(runner, HostRunner)

    def test_returns_same_instance_on_repeated_calls(self) -> None:
        import execution

        execution._default_runner = None
        runner1 = get_default_runner()
        runner2 = get_default_runner()
        assert runner1 is runner2

    def test_returns_subprocess_runner_protocol(self) -> None:
        """get_default_runner returns a SubprocessRunner protocol instance."""
        import execution

        execution._default_runner = None
        runner = get_default_runner()
        assert isinstance(runner, SubprocessRunner)
