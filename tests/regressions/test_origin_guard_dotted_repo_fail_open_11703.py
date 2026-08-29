"""Regression pins for the #11703 origin-guard fail-open.

The bug: ``WorkspaceManager._assert_origin_matches_repo`` exists to raise when a
checkout's ``origin`` remote is not the configured repo. Both of its origin
patterns spelled the repo-name segment ``[^/.]+?``, which forbids a dot anywhere
in the repo name. GitHub permits dots (``socket.io``, ``next.js``, ``Vue.js``),
so for any such origin **both patterns missed**, ``match`` was ``None``, and the
guard took its ``else`` branch: a ``logger.warning`` and a plain ``return``.

No raise. The guard silently permitted operating against a repo it could not
verify — the one thing it exists to prevent. Same fail-open class as
``SELF_MODIFYING_PATHS`` in #11669: a safety check that is inert rather than red.
HydraFlow's own repo has no dot, which is why nothing ever went red.

Pins:
1. A dotted repo name parses (the root cause), including ``.git`` stripping.
2. A dotted-name origin that does NOT match the configured repo **raises**,
   rather than warning and continuing.
3. A dotted-name origin that DOES match is validated, not skipped — the log must
   not report a skipped validation.
4. ``_ORIGIN_SSH_RE`` stays deleted. It was unreachable: the surviving pattern's
   ``[/:]`` class already matches scp-style's ``:`` separator, and the call is
   ``.search()``, so the ``git@`` prefix is irrelevant.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _manager(repo: str):
    from workspace import WorkspaceManager

    config = MagicMock()
    config.repo = repo
    config.repo_root = Path("/tmp/repo")  # noqa: S108
    config.repo_slug = repo.replace("/", "-")
    config.workspace_base = Path("/tmp/worktrees")  # noqa: S108
    config.main_branch = "main"
    config.dry_run = False
    config.ui_dirs = []
    # Explicit, never MagicMock-derived: an auto-created attribute is truthy,
    # so the #11720 fail-closed flag would read as ON regardless of intent and
    # the host would reach ``re.escape`` as a Mock.
    config.github_host = "github.com"
    config.origin_guard_fail_closed = True
    with patch.object(WorkspaceManager, "_detect_ui_dirs", return_value=[]):
        return WorkspaceManager(config)


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("git@github.com:socketio/socket.io.git", "socketio/socket.io"),
        ("https://github.com/vercel/next.js", "vercel/next.js"),
        ("https://github.com/vercel/next.js.git", "vercel/next.js"),
        ("ssh://git@github.com/vercel/next.js.git", "vercel/next.js"),
    ],
)
def test_dotted_repo_name_parses(url: str, slug: str) -> None:
    """The root cause: ``[^/.]+?`` refused a dot, so these parsed to nothing."""
    from workspace._remote import origin_url_pattern

    match = origin_url_pattern("github.com").search(url)
    assert match is not None, f"{url!r} did not parse — the guard would fail open"
    assert match.group(1) == slug


@pytest.mark.asyncio
async def test_dotted_origin_mismatch_raises_instead_of_failing_open() -> None:
    """The fail-open signature: a foreign dotted origin must abort, not warn."""
    wm = _manager("socketio/socket.io")
    with patch("workspace._remote.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "git@github.com:evilcorp/socket.io.git\n"
        with pytest.raises(RuntimeError, match="expected 'socketio/socket.io'"):
            await wm._assert_origin_matches_repo()
    mock_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_dotted_origin_match_is_validated_not_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A matching dotted origin passes *because it parsed*, not because it was skipped."""
    wm = _manager("vercel/next.js")
    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
        patch("workspace._remote.run_subprocess", new_callable=AsyncMock) as mock_run,
    ):
        mock_run.return_value = "https://github.com/vercel/next.js.git\n"
        result = await wm._assert_origin_matches_repo()
    mock_run.assert_awaited_once()
    assert "Origin validation SKIPPED" not in caplog.text
    assert result is None


def test_dead_ssh_pattern_stays_deleted() -> None:
    """``_ORIGIN_SSH_RE`` was unreachable; the surviving pattern covers scp-style."""
    from workspace import WorkspaceManager
    from workspace._remote import origin_url_pattern

    assert not hasattr(WorkspaceManager, "_ORIGIN_SSH_RE")
    assert (
        origin_url_pattern("github.com")
        .search("git@github.com:owner/repo.git")
        .group(1)
        == "owner/repo"
    )
