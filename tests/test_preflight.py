"""Tests for startup preflight dependency checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from preflight import (
    CheckResult,
    CheckStatus,
    _check_agent_cli,
    _check_disk_space,
    _check_docker,
    _check_docker_agent_credential,
    _check_gh_auth,
    _check_gh_cli,
    _check_git,
    _check_pipeline_target,
    _check_repo_root,
    log_preflight_results,
    run_preflight_checks,
)
from tests.helpers import config_mock

# ---------------------------------------------------------------------------
# _check_git
# ---------------------------------------------------------------------------


#: The host-mode preflight set, asserted BY NAME rather than by count.
#: `assert len(results) == 9` says nothing about WHICH checks ran and rots on
#: every addition — it broke when `stray-quality` landed, reporting a number
#: instead of naming the gap.
#: The mode-independent preflight checks, asserted BY NAME. A bare
#: `assert len(results) == 9` says nothing about WHICH checks ran and rots on
#: every addition — it broke when `stray-quality` landed, reporting a number
#: instead of naming the gap.
#:
#: `agent-cli-*` entries are deliberately excluded: there is one per configured
#: tool field, so pinning them here would couple this test to tool defaults it
#: is not about.
_MODE_INDEPENDENT_CHECKS = {
    "disk-space",
    "pipeline-target",
    "gh-auth",
    "gh-cli",
    "git",
    "plugins",
    "repo-root",
    "stray-quality",
    "contracts-sandbox",
}


def test_check_git_found() -> None:
    with patch("preflight.shutil.which", return_value="/usr/bin/git"):
        result = _check_git()
    assert result.status == CheckStatus.PASS
    assert result.name == "git"


def test_check_git_missing() -> None:
    with patch("preflight.shutil.which", return_value=None):
        result = _check_git()
    assert result.status == CheckStatus.FAIL


# ---------------------------------------------------------------------------
# _check_gh_cli
# ---------------------------------------------------------------------------


def test_check_gh_cli_found() -> None:
    with patch("preflight.shutil.which", return_value="/usr/bin/gh"):
        result = _check_gh_cli()
    assert result.status == CheckStatus.PASS


def test_check_gh_cli_missing() -> None:
    with patch("preflight.shutil.which", return_value=None):
        result = _check_gh_cli()
    assert result.status == CheckStatus.FAIL


# ---------------------------------------------------------------------------
# _check_gh_auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_gh_auth_ok() -> None:
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)
    with (
        patch("preflight.shutil.which", return_value="/usr/bin/gh"),
        patch("preflight.asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await _check_gh_auth()
    assert result.status == CheckStatus.PASS


@pytest.mark.asyncio
async def test_check_gh_auth_not_authenticated() -> None:
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=1)
    with (
        patch("preflight.shutil.which", return_value="/usr/bin/gh"),
        patch("preflight.asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await _check_gh_auth()
    assert result.status == CheckStatus.FAIL
    assert "not authenticated" in result.message


@pytest.mark.asyncio
async def test_check_gh_auth_gh_missing() -> None:
    with patch("preflight.shutil.which", return_value=None):
        result = await _check_gh_auth()
    assert result.status == CheckStatus.FAIL
    assert "not found" in result.message


@pytest.mark.asyncio
async def test_check_gh_auth_oserror() -> None:
    with (
        patch("preflight.shutil.which", return_value="/usr/bin/gh"),
        patch(
            "preflight.asyncio.create_subprocess_exec",
            side_effect=OSError("spawn failed"),
        ),
    ):
        result = await _check_gh_auth()
    assert result.status == CheckStatus.FAIL
    assert "spawn failed" in result.message


@pytest.mark.asyncio
async def test_check_gh_auth_timeout_warns_not_fails() -> None:
    """Slow `gh auth status` (e.g. keychain unlock) must not abort startup.

    Regression: keychain-backed gh installs can take 5–10s on first call. A
    1s timeout produced spurious FAILs; the check now WARNs and lets startup
    proceed since downstream gh calls do their own auth handling.
    """
    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(side_effect=TimeoutError)
    mock_proc.kill = MagicMock()
    with (
        patch("preflight.shutil.which", return_value="/usr/bin/gh"),
        patch("preflight.asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        result = await _check_gh_auth()
    assert result.status == CheckStatus.WARN
    assert "15s" in result.message
    mock_proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# _check_repo_root
# ---------------------------------------------------------------------------


def test_check_repo_root_valid(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    result = _check_repo_root(tmp_path)
    assert result.status == CheckStatus.PASS


def test_check_repo_root_no_git(tmp_path: Path) -> None:
    result = _check_repo_root(tmp_path)
    assert result.status == CheckStatus.WARN


def test_check_repo_root_missing() -> None:
    result = _check_repo_root(Path("/nonexistent/path"))
    assert result.status == CheckStatus.FAIL


# ---------------------------------------------------------------------------
# _check_disk_space
# ---------------------------------------------------------------------------


def test_check_disk_space_plenty(tmp_path: Path) -> None:
    with patch(
        "preflight.shutil.disk_usage",
        return_value=MagicMock(free=10 * 1024**3),
    ):
        result = _check_disk_space(tmp_path)
    assert result.status == CheckStatus.PASS


def test_check_disk_space_low(tmp_path: Path) -> None:
    with patch(
        "preflight.shutil.disk_usage",
        return_value=MagicMock(free=500 * 1024**2),  # 500 MB
    ):
        result = _check_disk_space(tmp_path)
    assert result.status == CheckStatus.WARN
    assert "Low disk space" in result.message


def test_check_disk_space_oserror(tmp_path: Path) -> None:
    with patch("preflight.shutil.disk_usage", side_effect=OSError("no access")):
        result = _check_disk_space(tmp_path)
    assert result.status == CheckStatus.WARN


def test_check_disk_space_nonexistent_path() -> None:
    with patch(
        "preflight.shutil.disk_usage",
        return_value=MagicMock(free=5 * 1024**3),
    ):
        result = _check_disk_space(Path("/tmp/nonexistent/deeply/nested"))
    assert result.status == CheckStatus.PASS


# ---------------------------------------------------------------------------
# _check_docker
# ---------------------------------------------------------------------------


def test_check_docker_missing() -> None:
    with patch("preflight.shutil.which", return_value=None):
        result = _check_docker()
    assert result.status == CheckStatus.FAIL
    assert "not found" in result.message


def test_check_docker_ok() -> None:
    with (
        patch("preflight.shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.run", return_value=MagicMock(returncode=0)),
    ):
        result = _check_docker()
    assert result.status == CheckStatus.PASS


def test_check_docker_daemon_down() -> None:
    with (
        patch("preflight.shutil.which", return_value="/usr/bin/docker"),
        patch("subprocess.run", return_value=MagicMock(returncode=1)),
    ):
        result = _check_docker()
    assert result.status == CheckStatus.FAIL
    assert "not reachable" in result.message


def test_check_docker_timeout() -> None:
    import subprocess

    with (
        patch("preflight.shutil.which", return_value="/usr/bin/docker"),
        patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired("docker info", 10),
        ),
    ):
        result = _check_docker()
    assert result.status == CheckStatus.FAIL


# ---------------------------------------------------------------------------
# _check_agent_cli
# ---------------------------------------------------------------------------


def test_check_agent_cli_found() -> None:
    with patch("preflight.shutil.which", return_value="/usr/local/bin/claude"):
        result = _check_agent_cli("claude")
    assert result.status == CheckStatus.PASS
    assert result.name == "agent-cli-claude"


def test_check_agent_cli_missing() -> None:
    with patch("preflight.shutil.which", return_value=None):
        result = _check_agent_cli("codex")
    assert result.status == CheckStatus.WARN
    assert "codex" in result.message


# ---------------------------------------------------------------------------
# log_preflight_results
# ---------------------------------------------------------------------------


def test_log_preflight_results_all_pass() -> None:
    results = [
        CheckResult("a", CheckStatus.PASS, "ok"),
        CheckResult("b", CheckStatus.WARN, "meh"),
    ]
    assert log_preflight_results(results) is True


def test_log_preflight_results_has_fail() -> None:
    results = [
        CheckResult("a", CheckStatus.PASS, "ok"),
        CheckResult("b", CheckStatus.FAIL, "bad"),
    ]
    assert log_preflight_results(results) is False


def test_log_preflight_results_empty() -> None:
    assert log_preflight_results([]) is True


# ---------------------------------------------------------------------------
# run_preflight_checks integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_preflight_checks_host_mode(tmp_path: Path) -> None:
    """Covers the full run with execution_mode='host'."""
    config = config_mock()
    config.repo_root = tmp_path
    config.data_root = tmp_path
    config.execution_mode = "host"
    config.implementation_tool = "claude"
    config.review_tool = "claude"
    config.planner_tool = "claude"

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with (
        patch("preflight.shutil.which", return_value="/usr/bin/git"),
        patch("preflight.asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "preflight.shutil.disk_usage",
            return_value=MagicMock(free=10 * 1024**3),
        ),
    ):
        results = await run_preflight_checks(config)

    # Assert the SET, not a count. `assert len(results) == 9` says nothing
    # about WHICH checks ran and rots on every addition — it broke when
    # `stray-quality` landed, naming a number instead of the gap.
    assert {r.name for r in results} == {
        "git",
        "gh-cli",
        "gh-auth",
        "repo-root",
        "pipeline-target",
        "disk-space",
        "agent-cli-claude",
        "plugins",
        "stray-quality",
        "abandoned-factory",
        "contracts-sandbox",
    }
    # No docker check in host mode
    assert not any(r.name == "docker" for r in results)


@pytest.mark.asyncio
async def test_run_preflight_checks_docker_mode(tmp_path: Path) -> None:
    """Docker mode adds a docker check."""
    config = config_mock()
    config.repo_root = tmp_path
    config.data_root = tmp_path
    config.execution_mode = "docker"
    config.implementation_tool = "claude"
    config.review_tool = "claude"
    config.planner_tool = "claude"

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with (
        patch("preflight.shutil.which", return_value="/usr/bin/something"),
        patch("preflight.asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "preflight.shutil.disk_usage",
            return_value=MagicMock(free=10 * 1024**3),
        ),
        patch("subprocess.run", return_value=MagicMock(returncode=0)),
    ):
        results = await run_preflight_checks(config)

    names = {r.name for r in results}
    assert "docker" in names, "docker mode must add the docker daemon check"
    assert "docker-agent-credential" in names, (
        "docker mode must add the claude-credential check (#12040)"
    )
    # Docker mode is host mode PLUS docker — nothing may be dropped.
    assert names >= _MODE_INDEPENDENT_CHECKS


@pytest.mark.asyncio
async def test_run_preflight_checks_deduplicates_tools(tmp_path: Path) -> None:
    """When all tools are the same, we still get 3 agent-cli checks (one per field)."""
    config = config_mock()
    config.repo_root = tmp_path
    config.data_root = tmp_path
    config.execution_mode = "host"
    config.implementation_tool = "codex"
    config.review_tool = "codex"
    config.planner_tool = "codex"

    mock_proc = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)

    with (
        patch("preflight.shutil.which", return_value="/usr/bin/x"),
        patch("preflight.asyncio.create_subprocess_exec", return_value=mock_proc),
        patch(
            "preflight.shutil.disk_usage",
            return_value=MagicMock(free=10 * 1024**3),
        ),
    ):
        results = await run_preflight_checks(config)

    agent_checks = [r for r in results if r.name.startswith("agent-cli")]
    assert len(agent_checks) == 3


# ---------------------------------------------------------------------------
# server._run_preflight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_run_preflight_skipped() -> None:
    """skip_preflight=True bypasses checks."""
    from server import _run_preflight

    config = config_mock()
    config.skip_preflight = True
    assert await _run_preflight(config) is True


@pytest.mark.asyncio
async def test_server_run_preflight_passes() -> None:
    """Healthy checks let startup proceed."""
    from server import _run_preflight

    config = config_mock()
    config.skip_preflight = False

    with (
        patch(
            "preflight.run_preflight_checks",
            return_value=[CheckResult("a", CheckStatus.PASS, "ok")],
        ),
        patch("preflight.log_preflight_results", return_value=True),
    ):
        assert await _run_preflight(config) is True


@pytest.mark.asyncio
async def test_server_run_preflight_fails() -> None:
    """Failed checks block startup."""
    from server import _run_preflight

    config = config_mock()
    config.skip_preflight = False

    with (
        patch(
            "preflight.run_preflight_checks",
            return_value=[CheckResult("a", CheckStatus.FAIL, "bad")],
        ),
        patch("preflight.log_preflight_results", return_value=False),
    ):
        assert await _run_preflight(config) is False


@pytest.mark.asyncio
async def test_server_run_aborts_on_preflight_failure() -> None:
    """_run should return early without calling dashboard/headless when preflight fails."""
    from server import _run

    config = config_mock()
    config.skip_preflight = False
    config.dashboard_enabled = True

    with (
        patch("server._run_preflight", return_value=False),
        patch("server._run_with_dashboard") as mock_dash,
        patch("server._run_headless") as mock_headless,
    ):
        await _run(config)

    mock_dash.assert_not_called()
    mock_headless.assert_not_called()


@pytest.mark.asyncio
async def test_server_run_proceeds_on_preflight_success() -> None:
    """_run should proceed to dashboard when preflight passes."""
    from server import _run

    config = config_mock()
    config.skip_preflight = False
    config.dashboard_enabled = True

    with (
        patch("server._run_preflight", return_value=True),
        patch("server._run_with_dashboard") as mock_dash,
    ):
        await _run(config)

    mock_dash.assert_called_once_with(config)


# ---------------------------------------------------------------------------
# _check_pipeline_target (#12040)
# ---------------------------------------------------------------------------


def test_pipeline_target_set_passes() -> None:
    config = config_mock()
    config.repo = "acme/project-x"
    result = _check_pipeline_target(config)
    assert result.status == CheckStatus.PASS
    assert "acme/project-x" in result.message


def test_pipeline_target_unset_warns_with_detected_remote(tmp_path: Path) -> None:
    config = config_mock()
    config.repo = ""
    config.repo_root = tmp_path
    with patch("preflight._detect_repo_slug", return_value="acme/checkout"):
        result = _check_pipeline_target(config)
    assert result.status == CheckStatus.WARN
    assert "HYDRAFLOW_GITHUB_REPO" in result.message
    assert "idle" in result.message
    assert "acme/checkout" in result.message
    assert "never targeted automatically" in result.message


def test_pipeline_target_unset_warns_without_remote(tmp_path: Path) -> None:
    config = config_mock()
    config.repo = ""
    config.repo_root = tmp_path
    with patch("preflight._detect_repo_slug", return_value=""):
        result = _check_pipeline_target(config)
    assert result.status == CheckStatus.WARN
    assert "never targeted automatically" not in result.message


# ---------------------------------------------------------------------------
# _check_docker_agent_credential (#12040)
# ---------------------------------------------------------------------------


def _docker_cred_config(tmp_path: Path, provider: str = "direct") -> Any:
    config = config_mock()
    config.repo_root = tmp_path
    config.implementation_tool = "claude"
    config.review_tool = "codex"
    config.planner_tool = "claude"
    config.implementation_provider = provider
    config.review_provider = provider
    config.planner_provider = provider
    return config


def test_docker_credential_missing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = _check_docker_agent_credential(_docker_cred_config(tmp_path))
    assert result.status == CheckStatus.FAIL
    assert "claude setup-token" in result.message
    assert "implementation_tool" in result.message
    assert "planner_tool" in result.message
    assert "review_tool" not in result.message  # codex role is not claude


def test_docker_credential_from_process_env_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-test")
    result = _check_docker_agent_credential(_docker_cred_config(tmp_path))
    assert result.status == CheckStatus.PASS
    assert "CLAUDE_CODE_OAUTH_TOKEN" in result.message


def test_docker_credential_api_key_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    result = _check_docker_agent_credential(_docker_cred_config(tmp_path))
    assert result.status == CheckStatus.PASS


def test_docker_credential_from_dotenv_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented home for the token is repo_root/.env — same lookup
    make_docker_env uses, so preflight and the container agree."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch(
        "preflight._dotenv_lookup",
        side_effect=lambda _root, *keys: (
            "sk-ant-oat01-dotenv" if "CLAUDE_CODE_OAUTH_TOKEN" in keys else ""
        ),
    ):
        result = _check_docker_agent_credential(_docker_cred_config(tmp_path))
    assert result.status == CheckStatus.PASS


def test_docker_credential_gateway_roles_exempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A role routed via the gateway gets per-spawn virtual keys — no host
    credential is required, and the check must not fail the boot."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = _check_docker_agent_credential(
        _docker_cred_config(tmp_path, provider="gateway")
    )
    assert result.status == CheckStatus.PASS
    assert "no direct-claude roles" in result.message


def test_docker_credential_non_claude_tools_exempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = _docker_cred_config(tmp_path)
    config.implementation_tool = "codex"
    config.planner_tool = "gemini"
    result = _check_docker_agent_credential(config)
    assert result.status == CheckStatus.PASS
