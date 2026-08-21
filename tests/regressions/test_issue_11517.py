"""Regression #11517: epic release tags the factory checkout HEAD, not origin/main.

ADR-0011's epic-completion release path mints ``vX.Y.Z`` via
``EpicCompletionChecker._create_release_for_epic`` → ``PRManager.create_tag(tag)``
with the default ``ref="HEAD"``, so the tag lands on whatever the factory
checkout happens to be on. Under ADR-0042 the factory runs on ``staging``
(``HydraFlowConfig().base_branch()``) — a release tag would point at a staging
commit (or a mid-work agent branch) instead of the promoted ``main`` SHA that
passed the RC gate.

The pins below use real ``git`` in a temp repo (no ``_run_gh`` mocking) so the
assertion observes the SHA the tag actually landed on:

* a completed versioned epic in a checkout whose HEAD has diverged from
  ``origin/main`` must tag the resolved ``origin/<main_branch>`` SHA — RED
  before the fix, which tags ``HEAD``;
* an unresolvable ``origin/<main_branch>`` must fail closed — no tag minted
  on the checkout HEAD — RED before the fix, which mints one;
* an unversioned epic title still skips the release entirely (scope guard
  for the eventual fix; green today and must stay green).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from epic import EpicCompletionChecker
from events import EventBus
from pr_manager import PRManager
from tests.helpers import ConfigFactory

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git binary not on PATH"
)


def _git(repo: Path, *args: str) -> str:
    """Run git in *repo* and return stripped stdout (fails the test on error)."""
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def diverged_checkout(tmp_path: Path) -> Path:
    """A factory checkout on ``staging`` whose HEAD has diverged from ``origin/main``.

    Mirrors production shape (ADR-0042): the promoted commit lives at
    ``origin/main``; the checkout has moved on to agent work on ``staging``.
    """
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.name", "HydraFlow Test")
    _git(work, "config", "user.email", "hydraflow-test@example.com")
    _git(work, "remote", "add", "origin", str(origin))

    # The promoted main commit, pushed through the (fake) remote.
    _git(work, "commit", "--allow-empty", "-m", "promoted to main")
    _git(work, "push", "origin", "main")

    # The factory checkout moves on: HEAD is now a staging commit.
    _git(work, "checkout", "-b", "staging")
    _git(work, "commit", "--allow-empty", "-m", "factory work on staging")
    return work


@requires_git
async def test_versioned_epic_tags_promoted_main_not_checkout_head(
    diverged_checkout: Path,
) -> None:
    """A completed versioned epic must tag origin/main, never checkout HEAD."""
    config = ConfigFactory.create(
        repo="test-org/test-repo",
        repo_root=diverged_checkout,
        staging_enabled=True,
        gh_max_retries=0,
    )
    prs = PRManager(config, EventBus())
    checker = EpicCompletionChecker(config, prs, AsyncMock())

    head_sha = _git(diverged_checkout, "rev-parse", "HEAD")
    main_sha = _git(diverged_checkout, "rev-parse", "origin/main")
    # Fixture sanity: the pin below is only meaningful when the refs diverge.
    assert head_sha != main_sha

    with (
        # Changelog PR lookups and the gh release call are network-bound;
        # neither touches the tagging seam under test.
        patch.object(prs, "get_pr_for_issue", AsyncMock(return_value=0)),
        patch.object(prs, "create_release", AsyncMock(return_value=True)),
    ):
        await checker._create_release_for_epic(
            100, "[Epic] v1.0.0 — Stable base", [1, 2]
        )

    tag_sha = _git(diverged_checkout, "rev-parse", "v1.0.0")
    # RED pre-fix: the tag was minted on the checkout HEAD (staging tip).
    assert tag_sha == main_sha, (
        "release tag must point at the promoted origin/main SHA, "
        f"got HEAD-adjacent {tag_sha} (main is {main_sha})"
    )
    assert tag_sha != head_sha


@requires_git
async def test_unresolvable_main_fails_closed_no_head_tag(
    tmp_path: Path,
) -> None:
    """When origin/<main_branch> cannot be resolved, no tag is minted at all.

    Pre-fix the path happily tags the checkout HEAD (then fails the push),
    leaving a stale HEAD-pointed tag behind — the exact shape #11517 forbids.
    """
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "staging")
    _git(work, "config", "user.name", "HydraFlow Test")
    _git(work, "config", "user.email", "hydraflow-test@example.com")
    _git(work, "commit", "--allow-empty", "-m", "checkout with no remote")

    config = ConfigFactory.create(
        repo="test-org/test-repo",
        repo_root=work,
        staging_enabled=True,
        gh_max_retries=0,
    )
    prs = PRManager(config, EventBus())
    checker = EpicCompletionChecker(config, prs, AsyncMock())

    with (
        patch.object(prs, "get_pr_for_issue", AsyncMock(return_value=0)),
        patch.object(prs, "create_release", AsyncMock(return_value=True)) as rel,
    ):
        await checker._create_release_for_epic(200, "[Epic] v2.0.0 — No remote", [3])

    # Fail closed: never leave a tag pointing at the checkout HEAD.
    assert _git(work, "tag", "-l", "v2.0.0") == ""
    rel.assert_not_called()


@requires_git
async def test_unversioned_epic_still_skips_release(tmp_path: Path) -> None:
    """Scope guard: no version in the title → no tag, no release (unchanged)."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "staging")
    _git(work, "config", "user.name", "HydraFlow Test")
    _git(work, "config", "user.email", "hydraflow-test@example.com")
    _git(work, "commit", "--allow-empty", "-m", "unversioned epic repo")

    config = ConfigFactory.create(
        repo="test-org/test-repo",
        repo_root=work,
        staging_enabled=True,
        gh_max_retries=0,
    )
    prs = PRManager(config, EventBus())
    checker = EpicCompletionChecker(config, prs, AsyncMock())

    with (
        patch.object(prs, "create_tag", AsyncMock(return_value=True)) as tag,
        patch.object(prs, "create_release", AsyncMock(return_value=True)) as rel,
    ):
        release_url, _ = await checker._create_release_for_epic(
            300, "[Epic] No version here", [5]
        )

    assert release_url == ""
    tag.assert_not_called()
    rel.assert_not_called()
