"""Tests for base_runner.py — BaseRunner class."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_runner import BaseRunner
from events import EventBus
from execution import HostRunner
from runner_utils import AuthenticationRetryError

# ---------------------------------------------------------------------------
# Concrete subclass for testing (BaseRunner has abstract _log ClassVar)
# ---------------------------------------------------------------------------


class _TestRunner(BaseRunner):
    """Minimal concrete subclass used in tests."""

    _log = logging.getLogger("hydraflow.test_runner")


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestBaseRunnerInit:
    def test_init_stores_config_reference(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        assert runner._config is config

    def test_init_stores_event_bus_reference(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        assert runner._bus is event_bus

    def test_active_procs_starts_empty(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        assert runner._active_procs == set()

    def test_active_count_starts_at_zero(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        assert runner.active_count == 0

    def test_active_count_reflects_active_procs_size(
        self, config, event_bus: EventBus
    ) -> None:
        runner = _TestRunner(config, event_bus)
        mock_proc1 = MagicMock()
        mock_proc1.pid = 1
        mock_proc2 = MagicMock()
        mock_proc2.pid = 2
        runner._active_procs.add(mock_proc1)
        assert runner.active_count == 1
        runner._active_procs.add(mock_proc2)
        assert runner.active_count == 2
        runner._active_procs.discard(mock_proc1)
        assert runner.active_count == 1

    def test_uses_provided_runner(self, config, event_bus: EventBus) -> None:
        mock_runner = MagicMock()
        runner = _TestRunner(config, event_bus, runner=mock_runner)
        assert runner._runner is mock_runner

    def test_uses_default_runner_when_none(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        assert runner._runner is not None


# ---------------------------------------------------------------------------
# terminate
# ---------------------------------------------------------------------------


class TestTerminate:
    def test_calls_terminate_processes(self, config, event_bus: EventBus) -> None:
        runner = _TestRunner(config, event_bus)
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        runner._active_procs.add(mock_proc)

        with patch("base_runner.terminate_processes") as mock_tp:
            runner.terminate()
        mock_tp.assert_called_once_with(runner._active_procs)

    def test_terminate_with_empty_procs_does_not_raise(
        self, config, event_bus: EventBus
    ) -> None:
        runner = _TestRunner(config, event_bus)
        runner.terminate()  # Should not raise
        assert len(runner._active_procs) == 0  # empty procs remain unchanged


# ---------------------------------------------------------------------------
# _save_transcript
# ---------------------------------------------------------------------------


class TestSaveTranscript:
    def test_writes_file_with_prefix_and_identifier(
        self, config, event_bus: EventBus
    ) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = _TestRunner(config, event_bus)
        runner._save_transcript("issue", 42, "transcript content")

        path = config.repo_root / ".hydraflow" / "logs" / "issue-42.txt"
        assert path.exists()
        assert path.read_text() == "transcript content"

    def test_creates_log_directory(self, config, event_bus: EventBus) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert not log_dir.exists()

        runner = _TestRunner(config, event_bus)
        runner._save_transcript("plan-issue", 7, "content")

        assert log_dir.is_dir()

    def test_different_prefixes_produce_different_files(
        self, config, event_bus: EventBus
    ) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = _TestRunner(config, event_bus)

        runner._save_transcript("issue", 1, "agent transcript")
        runner._save_transcript("review-pr", 1, "review transcript")

        log_dir = config.repo_root / ".hydraflow" / "logs"
        assert (log_dir / "issue-1.txt").read_text() == "agent transcript"
        assert (log_dir / "review-pr-1.txt").read_text() == "review transcript"

    def test_handles_oserror(
        self, config, event_bus: EventBus, caplog: pytest.LogCaptureFixture
    ) -> None:
        config.repo_root.mkdir(parents=True, exist_ok=True)
        runner = _TestRunner(config, event_bus)

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            runner._save_transcript("issue", 42, "content")  # should not raise

        assert "Could not save transcript" in caplog.text


# ---------------------------------------------------------------------------
# _execute
# ---------------------------------------------------------------------------


class TestExecute:
    @pytest.mark.asyncio
    async def test_delegates_to_stream_claude_process(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        runner = _TestRunner(config, event_bus)

        with patch("base_runner.stream_claude_process", new_callable=AsyncMock) as mock:
            mock.return_value = "transcript output"
            result = await runner._execute(
                ["claude", "-p"], "prompt", tmp_path, {"issue": 42}
            )

        assert result == "transcript output"
        mock.assert_awaited_once()
        call_kwargs = mock.call_args[1]
        assert call_kwargs["cmd"] == ["claude", "-p"]
        assert call_kwargs["prompt"] == "prompt"
        assert call_kwargs["cwd"] == tmp_path
        assert call_kwargs["event_data"] == {"issue": 42}
        assert call_kwargs["config"].on_output is None
        assert call_kwargs["config"].gh_token == runner._credentials.gh_token

    @pytest.mark.asyncio
    async def test_passes_on_output_callback(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        runner = _TestRunner(config, event_bus)

        def callback(text: str) -> bool:
            return "DONE" in text

        with patch("base_runner.stream_claude_process", new_callable=AsyncMock) as mock:
            mock.return_value = "output"
            await runner._execute(
                ["claude", "-p"],
                "prompt",
                tmp_path,
                {"issue": 42},
                on_output=callback,
            )

        call_kwargs = mock.call_args[1]
        assert call_kwargs["config"].on_output is callback

    @pytest.mark.asyncio
    async def test_auth_failure_retries_with_backoff(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Auth failures are retried 3 times before raising."""
        runner = _TestRunner(config, event_bus)

        with (
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                side_effect=AuthenticationRetryError("auth failed"),
            ) as mock,
            patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
            pytest.raises(AuthenticationRetryError),
        ):
            await runner._execute(["claude", "-p"], "prompt", tmp_path, {"issue": 42})

        assert mock.await_count == 3
        # 2 sleeps: 5s after attempt 1, 10s after attempt 2
        assert sleep_mock.await_count == 2
        sleep_mock.assert_any_await(5.0)
        sleep_mock.assert_any_await(10.0)

    @pytest.mark.asyncio
    async def test_auth_failure_succeeds_on_retry(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Auth succeeds on second attempt after transient failure."""
        runner = _TestRunner(config, event_bus)

        with (
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                side_effect=[
                    AuthenticationRetryError("auth failed"),
                    "transcript output",
                ],
            ) as mock,
            patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
        ):
            result = await runner._execute(
                ["claude", "-p"], "prompt", tmp_path, {"issue": 42}
            )

        assert result == "transcript output"
        assert mock.await_count == 2
        assert sleep_mock.await_count == 1

    @pytest.mark.asyncio
    async def test_gateway_env_is_resolved_once_across_auth_retries(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """A retry reuses one spawn key instead of minting a second session."""
        runner = _TestRunner(config, event_bus)
        runner._resolve_provider = lambda: "gateway"  # type: ignore[method-assign]

        with (
            patch(
                "base_runner.resolve_harness_env",
                new_callable=AsyncMock,
                return_value={
                    "ANTHROPIC_BASE_URL": "http://gateway:8080",
                    "ANTHROPIC_AUTH_TOKEN": "hfgw_once",
                    "ANTHROPIC_API_KEY": "",
                },
            ) as resolve_mock,
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                side_effect=[
                    AuthenticationRetryError("transient"),
                    "transcript output",
                ],
            ) as stream_mock,
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(
                "base_runner.renew_gateway_key_if_needed",
                new_callable=AsyncMock,
                return_value=False,
            ) as renew_mock,
            patch(
                "base_runner.revoke_gateway_key",
                new_callable=AsyncMock,
            ) as revoke_mock,
        ):
            result = await runner._execute(
                ["claude", "--model", "sonnet", "-p"],
                "prompt",
                tmp_path,
                {"issue": 42, "source": "test_runner"},
            )

        assert result == "transcript output"
        assert resolve_mock.await_count == 1
        assert stream_mock.await_count == 2
        assert renew_mock.await_count == 1
        assert revoke_mock.await_count == 1
        revoke_mock.assert_awaited_once_with(resolve_mock.return_value)
        telemetry_rows = [
            json.loads(line)
            for line in config.cost_inferences_path.read_text().splitlines()
            if line
        ]
        assert telemetry_rows[-1]["tool"] == "gateway"
        assert telemetry_rows[-1]["model"] == "sonnet"

    @pytest.mark.asyncio
    async def test_terminal_gateway_uses_owned_isolated_runner_for_stream(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """The terminal fleet profile must never stream through ``HostRunner``."""
        object.__setattr__(config, "execution_mode", "docker")
        object.__setattr__(config, "gateway_fleet_ratchet_enabled", True)
        host_runner = HostRunner()
        isolated_runner = AsyncMock()
        runner = _TestRunner(config, event_bus, runner=host_runner)

        with (
            patch(
                "base_runner.resolve_harness_env",
                new_callable=AsyncMock,
                return_value={
                    "ANTHROPIC_BASE_URL": "http://gateway:8080",
                    "ANTHROPIC_AUTH_TOKEN": "hfgw_terminal",
                    "ANTHROPIC_API_KEY": "",
                },
            ),
            patch(
                "runner_utils.get_docker_runner",
                return_value=isolated_runner,
            ) as docker_runner_mock,
            patch.object(
                host_runner,
                "cleanup",
                new_callable=AsyncMock,
            ) as host_cleanup_mock,
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                return_value="terminal gateway transcript",
            ) as stream_mock,
            patch(
                "base_runner.revoke_gateway_key",
                new_callable=AsyncMock,
            ),
        ):
            result = await runner._execute(
                ["claude", "--model", "sonnet", "-p"],
                "terminal gateway prompt",
                tmp_path,
                {"issue": 42, "source": "test_runner"},
            )

        stream_config = stream_mock.await_args.kwargs["config"]
        assert result == "terminal gateway transcript"
        assert stream_config.runner is isolated_runner
        assert stream_config.runner is not host_runner
        docker_runner_mock.assert_called_once_with(config)
        isolated_runner.cleanup.assert_awaited_once_with()
        host_cleanup_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_terminal_gateway_cleans_owned_resources_on_stream_failure(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """A stream failure must not bypass key revocation or runner cleanup."""
        object.__setattr__(config, "execution_mode", "docker")
        object.__setattr__(config, "gateway_fleet_ratchet_enabled", True)
        host_runner = HostRunner()
        isolated_runner = AsyncMock()
        runner = _TestRunner(config, event_bus, runner=host_runner)
        harness_env = {
            "ANTHROPIC_BASE_URL": "http://gateway:8080",
            "ANTHROPIC_AUTH_TOKEN": "hfgw_terminal_failure",
            "ANTHROPIC_API_KEY": "",
        }
        stream_failure = RuntimeError("terminal gateway stream failed")

        with (
            patch(
                "base_runner.resolve_harness_env",
                new_callable=AsyncMock,
                return_value=harness_env,
            ) as resolve_mock,
            patch(
                "runner_utils.get_docker_runner",
                return_value=isolated_runner,
            ),
            patch.object(
                host_runner,
                "cleanup",
                new_callable=AsyncMock,
            ) as host_cleanup_mock,
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                side_effect=stream_failure,
            ) as stream_mock,
            patch(
                "base_runner.revoke_gateway_key",
                new_callable=AsyncMock,
            ) as revoke_mock,
            pytest.raises(RuntimeError) as exc_info,
        ):
            await runner._execute(
                ["claude", "--model", "sonnet", "-p"],
                "terminal gateway prompt",
                tmp_path,
                {"issue": 42, "source": "test_runner"},
            )

        assert exc_info.value is stream_failure
        resolve_mock.assert_awaited_once()
        assert stream_mock.await_args.kwargs["config"].runner is isolated_runner
        revoke_mock.assert_awaited_once_with(harness_env)
        isolated_runner.cleanup.assert_awaited_once_with()
        host_cleanup_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_finite_usage_payload_does_not_fail_the_run(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Telemetry runs unguarded in _execute's ``finally``: a NaN in a
        backend raw_usage payload must not convert a SUCCESSFUL agent run
        into a hard failure (it would burn attempt budget), and the
        telemetry record must still land."""
        runner = _TestRunner(config, event_bus)

        with patch("base_runner.stream_claude_process", new_callable=AsyncMock) as mock:
            mock.return_value = "transcript output"
            result = await runner._execute(
                ["claude", "-p"],
                "prompt",
                tmp_path,
                {"issue": 42},
                telemetry_stats={
                    "raw_usage": [
                        {
                            "backend": "claude",
                            "event_type": "result",
                            "payload": {"tokens_per_second": float("nan")},
                        }
                    ]
                },
            )

        assert result == "transcript output"
        inf_file = config.cost_inferences_path
        rows = [
            json.loads(ln) for ln in inf_file.read_text().splitlines() if ln.strip()
        ]
        assert len(rows) == 1
        assert rows[0]["raw_usage"][0]["payload"]["tokens_per_second"] == "NaN"


# ---------------------------------------------------------------------------
# _inject_memory
# ---------------------------------------------------------------------------


class TestVerifyQuality:
    @pytest.mark.asyncio
    async def test_verify_quality_returns_true_on_success(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        mock_runner = MagicMock()
        mock_runner.run_simple = AsyncMock(
            return_value=MagicMock(returncode=0, stdout="OK", stderr="")
        )
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        result = await runner._verify_quality(tmp_path)

        assert result.passed is True
        assert result.summary == "OK"

    @pytest.mark.asyncio
    async def test_failure_nonzero_returncode(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        mock_runner = MagicMock()
        mock_runner.run_simple = AsyncMock(
            return_value=MagicMock(
                returncode=1, stdout="FAILED test_foo", stderr="error details"
            )
        )
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        result = await runner._verify_quality(tmp_path)

        assert result.passed is False
        assert "`make quality` failed" in result.summary
        assert "FAILED test_foo" in result.summary

    @pytest.mark.asyncio
    async def test_file_not_found(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        mock_runner = MagicMock()
        mock_runner.run_simple = AsyncMock(side_effect=FileNotFoundError)
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        result = await runner._verify_quality(tmp_path)

        assert result.passed is False
        assert "make not found" in result.summary

    @pytest.mark.asyncio
    async def test_verify_quality_returns_false_on_timeout(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        mock_runner = MagicMock()
        mock_runner.run_simple = AsyncMock(side_effect=TimeoutError)
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        result = await runner._verify_quality(tmp_path)

        assert result.passed is False
        assert "timed out" in result.summary

    @pytest.mark.asyncio
    async def test_verify_quality_truncates_long_failure_output(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        mock_runner = MagicMock()
        long_output = "x" * 5000
        mock_runner.run_simple = AsyncMock(
            return_value=MagicMock(returncode=1, stdout=long_output, stderr="")
        )
        runner = _TestRunner(config, event_bus, runner=mock_runner)

        result = await runner._verify_quality(tmp_path)

        assert result.passed is False
        # Output should be truncated to last 3000 chars
        assert len(result.summary) < 5000 + 100  # some overhead for prefix text


# ---------------------------------------------------------------------------
# _build_command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_build_command_starts_with_claude(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert cmd[0] == "claude"

    def test_build_command_uses_implementation_tool_and_model(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == config.model
        assert "--max-budget-usd" not in cmd

    def test_build_command_path_argument_is_unused(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """The workspace_path arg is accepted for API compatibility but not included in cmd."""
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command(tmp_path)
        assert "--cwd" not in cmd

    def test_build_command_accepts_none_workspace_path(
        self, config, event_bus: EventBus
    ) -> None:
        """The workspace_path parameter is optional (None) for runners that don't need worktrees."""
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command(None)
        assert cmd[0] == "claude"

    def test_build_command_works_without_arguments(
        self, config, event_bus: EventBus
    ) -> None:
        """The workspace_path parameter defaults to None when omitted."""
        runner = _TestRunner(config, event_bus)
        cmd = runner._build_command()
        assert cmd[0] == "claude"


class TestGatewayAttribution:
    @pytest.mark.asyncio
    async def test_execute_threads_issue_and_pr_into_harness_env(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """The gateway mint attributes spend to the issue/PR in event_data."""
        runner = _TestRunner(config, event_bus)
        with (
            patch(
                "base_runner.resolve_harness_env",
                new_callable=AsyncMock,
                return_value={},
            ) as resolve_mock,
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                return_value="transcript output",
            ),
        ):
            await runner._execute(
                ["claude", "--model", "sonnet", "-p"],
                "prompt",
                tmp_path,
                {"issue": 42, "pr": "77", "source": "test_runner"},
            )

        assert resolve_mock.await_args.kwargs["issue_number"] == 42
        assert resolve_mock.await_args.kwargs["pr_number"] == 77
