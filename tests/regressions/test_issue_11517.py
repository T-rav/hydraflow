"""Regression #11517: an epic release tags the promoted ``main`` SHA, never
the factory checkout ``HEAD``.

ADR-0011's release path called ``PRManager.create_tag(tag)`` with the
default ``ref="HEAD"``. Under ADR-0042 the factory checkout sits on
``staging`` (or an agent branch mid-work), so the first versioned epic
would have minted ``vX.Y.Z`` at a commit that never passed the RC gate.

The fixture builds the exact topology that exposes the bug — three
distinct commits:

- ``head``        — the factory clone's ``HEAD`` (a ``staging``-only commit),
- ``stale_main``  — the clone's *local* ``origin/main`` (what a no-fetch
                    ``git tag v1 origin/main`` would have used),
- ``promoted``    — the remote's current ``main`` (advanced AFTER the clone).

Only ``promoted`` is acceptable; a fix that tags ``HEAD`` or skips the fetch
fails here. The fail-closed branch (``origin/<main>`` unresolvable) must
skip the release rather than fall back to ``HEAD``.
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path
from typing import NamedTuple
from unittest.mock import AsyncMock, patch

import pytest

from epic import EpicCompletionChecker
from events import EventBus
from pr_manager import PRManager
from state import StateTracker
from tests.helpers import ConfigFactory

_EPIC_TITLE = "[Epic] v1.0.0 — stable base"


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _identity(repo: Path) -> None:
    # CI runners carry no global git config — every repo sets its own.
    _git(repo, "config", "user.email", "t@e.dev")
    _git(repo, "config", "user.name", "t")


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


class TwoTierRepo(NamedTuple):
    origin: Path
    factory: Path
    promoted: str
    head: str
    stale_main: str


@pytest.fixture
def two_tier_repo(tmp_path: Path) -> TwoTierRepo:
    """A bare ``origin`` plus a factory clone parked on ``staging``.

    ``main`` advances on the remote *after* the factory cloned, so the
    clone's local ``origin/main`` is stale and only a fetch sees the
    promoted SHA.
    """
    seed = tmp_path / "seed"
    _git(tmp_path, "init", "-q", "-b", "main", str(seed))
    _identity(seed)
    stale_main = _commit(seed, "a.txt")

    origin = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(seed), str(origin))
    _git(seed, "remote", "add", "origin", str(origin))

    factory = tmp_path / "factory"
    _git(tmp_path, "clone", "-q", str(origin), str(factory))
    _identity(factory)
    _git(factory, "checkout", "-q", "-b", "staging")
    head = _commit(factory, "staging-only.txt")

    promoted = _commit(seed, "promoted.txt")
    _git(seed, "push", "-q", "origin", "main")

    assert len({head, stale_main, promoted}) == 3, "fixture must yield 3 SHAs"
    assert _git(factory, "rev-parse", "origin/main") == stale_main
    return TwoTierRepo(origin, factory, promoted, head, stale_main)


def _checker(
    repo: TwoTierRepo, tmp_path: Path, *, main_branch: str = "main"
) -> tuple[EpicCompletionChecker, PRManager, StateTracker]:
    config = ConfigFactory.create(repo="org/repo", repo_root=repo.factory).model_copy(
        update={"main_branch": main_branch}
    )
    prs = PRManager(config, EventBus())
    state = StateTracker(tmp_path / "state.json")
    return EpicCompletionChecker(config, prs, AsyncMock(), state=state), prs, state


def test_create_tag_requires_an_explicit_ref() -> None:
    """``ref`` has no default — no caller can silently tag ``HEAD`` again."""
    param = inspect.signature(PRManager.create_tag).parameters["ref"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty


async def test_resolve_remote_branch_sha_fetches_so_origin_main_is_current(
    two_tier_repo: TwoTierRepo, tmp_path: Path
) -> None:
    _, prs, _ = _checker(two_tier_repo, tmp_path)

    sha = await prs.resolve_remote_branch_sha("main")

    assert sha == two_tier_repo.promoted
    assert sha != two_tier_repo.stale_main
    assert _git(two_tier_repo.factory, "rev-parse", "origin/main") == sha


async def test_release_tags_promoted_main_sha_not_checkout_head(
    two_tier_repo: TwoTierRepo, tmp_path: Path
) -> None:
    checker, prs, state = _checker(two_tier_repo, tmp_path)

    with (
        patch(
            "epic._completion.generate_changelog", AsyncMock(return_value="## v1.0.0")
        ) as mock_gen,
        patch.object(prs, "_run_with_body_file", AsyncMock(return_value="")),
    ):
        url, changelog = await checker._create_release_for_epic(
            100, _EPIC_TITLE, [1, 2]
        )

    assert mock_gen.await_count == 1, "patch target wrong — mock never consulted"
    assert url == "https://github.com/org/repo/releases/tag/v1.0.0"
    assert changelog == "## v1.0.0"
    tagged = _git(two_tier_repo.factory, "rev-parse", "v1.0.0^{commit}")
    assert tagged == two_tier_repo.promoted
    assert tagged != two_tier_repo.head, "tagged the factory checkout HEAD"
    assert tagged != two_tier_repo.stale_main, "tagged a stale origin/main"
    assert _git(two_tier_repo.origin, "rev-parse", "v1.0.0^{commit}") == tagged
    # The factory checkout itself is untouched by the release.
    assert _git(two_tier_repo.factory, "rev-parse", "HEAD") == two_tier_repo.head
    assert _git(two_tier_repo.factory, "rev-parse", "--abbrev-ref", "HEAD") == (
        "staging"
    )
    release = state.get_release(100)
    assert release is not None
    assert release.tag == "v1.0.0"


async def test_release_skips_fail_closed_when_main_cannot_be_resolved(
    two_tier_repo: TwoTierRepo, tmp_path: Path
) -> None:
    checker, prs, state = _checker(two_tier_repo, tmp_path, main_branch="no-such")
    create_tag = AsyncMock(wraps=prs.create_tag)
    create_release = AsyncMock(wraps=prs.create_release)

    with (
        patch(
            "epic._completion.generate_changelog", AsyncMock(return_value="## v1.0.0")
        ) as mock_gen,
        patch.object(prs, "create_tag", create_tag),
        patch.object(prs, "create_release", create_release),
    ):
        url, changelog = await checker._create_release_for_epic(
            100, _EPIC_TITLE, [1, 2]
        )

    assert mock_gen.await_count == 1, "patch target wrong — mock never consulted"
    assert url == ""
    assert changelog == "## v1.0.0", "changelog is preserved for the caller"
    create_tag.assert_not_awaited()
    create_release.assert_not_awaited()
    assert "v1.0.0" not in _git(two_tier_repo.factory, "tag", "--list").split()
    assert "v1.0.0" not in _git(two_tier_repo.origin, "tag", "--list").split()
    assert state.get_release(100) is None
