"""A locked registration whose directory is gone survives every prune (#11908).

`git worktree add` writes `.git/worktrees/<name>/locked` containing
`initializing` while it works and clears it on success. Killed partway, the
lock persists — and `parse_git_worktrees` deliberately *excludes locked rows*,
so the dead registration is invisible to the collector. Nothing in the repo
ever calls `git worktree prune` either.

`genpr-arch-regen-auto-20260728000053` sat that way for over a month.

The safe predicate is not the lock, it is the directory: if the worktree path
no longer exists there is nothing a lock could be protecting. A lock on a
worktree that DOES exist is a live operator lock and must survive untouched.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from workspace_gc_landed_safety import dead_registrations  # noqa: E402


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    root.mkdir()
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "t@example.com", cwd=root)
    _git("config", "user.name", "t", cwd=root)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=root)
    return root


def _add_worktree(repo: Path, name: str) -> Path:
    _git("branch", name, cwd=repo)
    path = repo.parent / name
    _git("worktree", "add", str(path), name, cwd=repo)
    return path


class TestDeadRegistrationsAreFound:
    def test_a_live_worktree_is_not_dead(self, repo: Path):
        _add_worktree(repo, "live")

        assert (
            dead_registrations(_git("worktree", "list", "--porcelain", cwd=repo)) == []
        )

    def test_a_registration_whose_directory_is_gone_is_dead(self, repo: Path):
        path = _add_worktree(repo, "gone")
        __import__("shutil").rmtree(path)

        dead = dead_registrations(_git("worktree", "list", "--porcelain", cwd=repo))

        assert [p.name for p in dead] == ["gone"]

    def test_a_LOCKED_registration_whose_directory_is_gone_is_still_dead(
        self, repo: Path
    ):
        """The exact #11908 shape — the lock is why prune skipped it."""
        path = _add_worktree(repo, "phantom")
        _git("worktree", "lock", str(path), cwd=repo)
        __import__("shutil").rmtree(path)

        dead = dead_registrations(_git("worktree", "list", "--porcelain", cwd=repo))

        assert [p.name for p in dead] == ["phantom"]

    def test_a_LOCKED_worktree_that_still_exists_is_never_dead(self, repo: Path):
        """Decoy: a live operator lock must survive the sweep untouched."""
        path = _add_worktree(repo, "locked_live")
        _git("worktree", "lock", str(path), cwd=repo)

        dead = dead_registrations(_git("worktree", "list", "--porcelain", cwd=repo))

        assert dead == [], f"a live locked worktree was marked dead: {dead}"

    def test_the_primary_worktree_is_never_dead(self, repo: Path):
        _add_worktree(repo, "other")

        dead = dead_registrations(_git("worktree", "list", "--porcelain", cwd=repo))

        assert repo.resolve() not in [p.resolve() for p in dead]


class TestTheAdapterActuallyPrunesThem:
    @pytest.mark.asyncio
    async def test_a_dead_locked_registration_is_unlocked_then_pruned(
        self, repo: Path, monkeypatch
    ):
        """End to end through the loop's own phase, against real git."""

        from workspace import WorkspaceManager

        path = _add_worktree(repo, "phantom")
        _git("worktree", "lock", str(path), cwd=repo)
        __import__("shutil").rmtree(path)

        # Sanity: plain prune cannot clear it — that is the whole defect.
        _git("worktree", "prune", cwd=repo)
        assert "phantom" in _git("worktree", "list", cwd=repo)

        mgr = WorkspaceManager.__new__(WorkspaceManager)
        mgr._repo_root = repo

        pruned = await mgr.prune_dead_registrations()

        assert [p.name for p in pruned] == ["phantom"]
        assert "phantom" not in _git("worktree", "list", cwd=repo)

    @pytest.mark.asyncio
    async def test_a_live_locked_worktree_survives_the_phase(self, repo: Path):
        from workspace import WorkspaceManager

        path = _add_worktree(repo, "locked_live")
        _git("worktree", "lock", str(path), cwd=repo)

        mgr = WorkspaceManager.__new__(WorkspaceManager)
        mgr._repo_root = repo

        pruned = await mgr.prune_dead_registrations()

        assert pruned == []
        assert "locked_live" in _git("worktree", "list", cwd=repo)
        assert path.exists()
