"""Regression pins for the #11720 origin-guard policy change.

#11703 fixed the mechanical fail-open (dotted repo names) but deliberately left
the *policy* fail-open: an origin URL the pattern could not parse was warned
about and execution continued. #11720 took the two coupled decisions that
deferred:

1. **Fail closed.** An origin the guard cannot parse is an origin it cannot
   verify, and "could not verify" is not a pass for the check whose whole job is
   to stop HydraFlow mutating the wrong repository.
2. **Host boundary.** The pattern was unanchored, so ``github\\.com`` matched
   inside a longer host: ``https://evilgithub.com/owner/repo`` parsed as
   ``owner/repo`` and was **accepted**. These are coupled — under fail-open,
   tightening the host would have converted a wrong *accept* into a silent
   *skip*, which is strictly worse.

The escape hatches that keep fail-closed safe are pinned here too, because a
kill-switch nobody has watched work is not a kill-switch:

- ``config.github_host`` keeps a GitHub Enterprise Server deployment **guarded**
  rather than exempt.
- ``config.origin_guard_fail_closed=False`` restores warn-and-continue for
  checkouts whose origin is a filesystem path.

The guard fires on every workspace creation from five loops, so the raised
message must be self-sufficient: origin, expected repo, and the setting to
change.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _manager(
    repo: str = "owner/repo",
    *,
    github_host: str = "github.com",
    fail_closed: bool = True,
):
    from workspace import WorkspaceManager

    config = MagicMock()
    config.repo = repo
    config.repo_root = Path("/tmp/repo")  # noqa: S108
    config.repo_slug = repo.replace("/", "-")
    config.workspace_base = Path("/tmp/worktrees")  # noqa: S108
    config.main_branch = "main"
    config.dry_run = False
    config.ui_dirs = []
    # Never left to MagicMock: an auto-created attribute is truthy, so the
    # fail-closed flag would read as ON no matter what a test meant.
    config.github_host = github_host
    config.origin_guard_fail_closed = fail_closed
    with patch.object(WorkspaceManager, "_detect_ui_dirs", return_value=[]):
        return WorkspaceManager(config)


# ---------------------------------------------------------------------------
# Decision 1 — fail closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.example/owner/repo.git",
        "https://github.mycorp.com/owner/repo.git",
        "/tmp/fixture-repo",
        "file:///tmp/fixture-repo",
        "../sibling-repo",
    ],
    ids=["other_host", "ghes_on_default_host", "fs_path", "file_url", "relative_path"],
)
async def test_unparseable_origin_raises_instead_of_continuing(url: str) -> None:
    wm = _manager()
    with patch("workspace._remote.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = f"{url}\n"
        with pytest.raises(RuntimeError):
            await wm._assert_origin_matches_repo()
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_origin_is_refused() -> None:
    """An origin that came back blank is one we could not determine — so refuse.

    Found by the full suite rather than by design: seven tests in
    ``test_workspace_create.py``/``test_workspace_env.py`` mock
    ``create_subprocess_exec`` generically, so ``git remote get-url origin``
    answered with ``""`` and, under fail-open, validation quietly no-opped.
    Fail-closed refuses instead. Real git prints a URL or exits non-zero, so
    this is not a shape production produces — but it is exactly the "cannot
    verify" case the guard now exists to stop, and those tests stub the guard
    out, so it is pinned here instead of nowhere.
    """
    wm = _manager("owner/repo")
    with patch("workspace._remote.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "\n"
        with pytest.raises(RuntimeError, match="not a recognised"):
            await wm._assert_origin_matches_repo()
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_raise_message_is_self_sufficient() -> None:
    """Fires per issue — a stalled factory must be fixable from the log text."""
    wm = _manager("owner/repo")
    with patch("workspace._remote.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "/tmp/fixture-repo\n"
        with pytest.raises(RuntimeError) as excinfo:
            await wm._assert_origin_matches_repo()
    mock_run.assert_awaited_once()
    message = str(excinfo.value)
    assert "/tmp/fixture-repo" in message  # the actual origin
    assert "owner/repo" in message  # the expected repo
    assert "HYDRAFLOW_GITHUB_HOST" in message  # how to fix it properly
    assert "HYDRAFLOW_ORIGIN_GUARD_FAIL_CLOSED" in message  # how to opt out


# ---------------------------------------------------------------------------
# Decision 2 — host boundary (coupled: only correct once fail-closed is on)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://evilgithub.com/owner/repo",
        "https://evilgithub.com/owner/repo.git",
        "git@notgithub.com:owner/repo.git",
        # The host as a PATH SEGMENT of a foreign origin — the same hole one
        # level down, which a ``[@/]`` boundary would still have let through.
        "https://evil.com/github.com/owner/repo",
        "https://evil.com/github.com/owner/repo.git",
        "/srv/mirror/github.com/owner/repo",
        # Userinfo trick: the real host appears before an ``@``, not after it.
        "https://github.com@evil.com/owner/repo",
    ],
    ids=[
        "lookalike_https",
        "lookalike_https_suffix",
        "lookalike_scp",
        "host_as_path_segment",
        "host_as_path_segment_suffix",
        "host_in_local_mirror_path",
        "host_in_userinfo",
    ],
)
async def test_lookalike_host_is_refused_not_accepted(url: str) -> None:
    """These parsed to ``owner/repo`` and were ACCEPTED before the boundary."""
    wm = _manager("owner/repo")
    with patch("workspace._remote.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = f"{url}\n"
        with pytest.raises(RuntimeError, match="not a recognised"):
            await wm._assert_origin_matches_repo()
    mock_run.assert_awaited_once()


def test_host_is_regex_escaped() -> None:
    """A dotted host stays literal — its dots must not act as wildcards."""
    from workspace._remote import origin_url_pattern

    pattern = origin_url_pattern("github.mycorp.com")
    assert pattern.search("https://github.mycorp.com/o/r.git").group(1) == "o/r"
    assert pattern.search("https://githubXmycorpYcom/o/r.git") is None


# ---------------------------------------------------------------------------
# The escape hatches that make fail-closed safe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configured_host_keeps_ghes_guarded_not_exempt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    wm = _manager("owner/repo", github_host="github.mycorp.com")
    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
        patch("workspace._remote.run_subprocess", new_callable=AsyncMock) as mock_run,
    ):
        mock_run.return_value = "git@github.mycorp.com:owner/repo.git\n"
        result = await wm._assert_origin_matches_repo()
    mock_run.assert_awaited_once()
    assert "Origin validation SKIPPED" not in caplog.text
    assert result is None


@pytest.mark.asyncio
async def test_configured_host_still_raises_on_a_foreign_repo() -> None:
    """Relaxing the host must not relax the identity check itself."""
    wm = _manager("owner/repo", github_host="github.mycorp.com")
    with patch("workspace._remote.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "git@github.mycorp.com:other/project.git\n"
        with pytest.raises(RuntimeError, match="expected 'owner/repo'"):
            await wm._assert_origin_matches_repo()
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["/tmp/fixture-repo", "file:///tmp/fixture-repo", "../sibling-repo"],
    ids=["fs_path", "file_url", "relative_path"],
)
async def test_kill_switch_restores_warn_and_continue(
    url: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Filesystem origins are fail-closed's realistic casualty; this covers them."""
    wm = _manager("owner/repo", fail_closed=False)
    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
        patch("workspace._remote.run_subprocess", new_callable=AsyncMock) as mock_run,
    ):
        mock_run.return_value = f"{url}\n"
        result = await wm._assert_origin_matches_repo()
    mock_run.assert_awaited_once()
    assert "Origin validation SKIPPED" in caplog.text
    assert "did NOT run" in caplog.text
    assert result is None


@pytest.mark.asyncio
async def test_kill_switch_does_not_disable_a_real_mismatch() -> None:
    """The switch covers only the unparseable case, never a parsed mismatch."""
    wm = _manager("owner/repo", fail_closed=False)
    with patch("workspace._remote.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "git@github.com:other/project.git\n"
        with pytest.raises(RuntimeError, match="expected 'owner/repo'"):
            await wm._assert_origin_matches_repo()
    mock_run.assert_awaited_once()


# ---------------------------------------------------------------------------
# Config surface
# ---------------------------------------------------------------------------


def test_config_defaults_are_guard_on_default_host() -> None:
    from config import HydraFlowConfig

    config = HydraFlowConfig()
    assert config.github_host == "github.com"
    assert config.origin_guard_fail_closed is True


def test_both_settings_are_env_overridable() -> None:
    from config import declared_env_keys

    keys = declared_env_keys()
    assert "HYDRAFLOW_GITHUB_HOST" in keys
    assert "HYDRAFLOW_ORIGIN_GUARD_FAIL_CLOSED" in keys


def test_both_settings_are_operator_reachable_in_the_ui() -> None:
    """Fail-closed stalls every issue, so the way out must not need a restart."""
    from settings_registry import SETTINGS

    assert "origin_guard_fail_closed" in SETTINGS
    assert "github_host" in SETTINGS


@pytest.mark.asyncio
async def test_kill_switch_is_re_read_per_call_not_captured_at_construction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Justifies ``live=True`` in the settings registry.

    The registry's honesty rule is that ``live=True`` may only be claimed when
    the running system genuinely re-reads the value. The settings route mutates
    the config object in place, so this asserts the guard reads the flag on each
    invocation rather than snapshotting it when the manager was built — flip it
    after construction and the very next call must follow the new value.
    """
    wm = _manager("owner/repo", fail_closed=True)

    with patch("workspace._remote.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "/tmp/fixture-repo\n"
        with pytest.raises(RuntimeError):
            await wm._assert_origin_matches_repo()
        mock_run.assert_awaited_once()

        # Operator flips the switch on the live config object — no restart.
        wm._config.origin_guard_fail_closed = False

        mock_run.reset_mock()
        with caplog.at_level(logging.WARNING, logger="hydraflow.workspace"):
            result = await wm._assert_origin_matches_repo()
        mock_run.assert_awaited_once()
    assert result is None
    assert "Origin validation SKIPPED" in caplog.text
