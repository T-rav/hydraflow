"""Integration tests for workspace.py using a real local git repo.

Verifies workspace create/destroy lifecycle, branch management,
environment setup helpers, and git operations.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


def _git(repo: Path, *args: str) -> str:
    """Run a git command in *repo* and return stdout."""
    env = {**os.environ, **_GIT_ENV}
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def _make_repo(base: Path, name: str = "repo") -> Path:
    """Create a minimal git repo with an initial commit on main."""
    repo = base / name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("# Test\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


# ---------------------------------------------------------------------------
# Setup helpers (_setup_dotenv, _setup_claude_settings, _setup_node_modules)
# ---------------------------------------------------------------------------


class TestSetupDotenv:
    """Integration tests for WorkspaceManager._setup_dotenv."""

    def _make_manager(self, tmp_path: Path, repo: Path, *, docker: bool = False):
        from tests.helpers import ConfigFactory

        execution_mode = "docker" if docker else "host"
        config = ConfigFactory.create(
            repo_root=repo,
            worktree_base=tmp_path / "worktrees",
            execution_mode=execution_mode,
        )
        from workspace import WorkspaceManager

        return WorkspaceManager(config)

    def test_symlinks_env_in_host_mode(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "repo")
        (repo / ".env").write_text("SECRET=abc\n")
        wt_path = tmp_path / "workspace"
        wt_path.mkdir()

        mgr = self._make_manager(tmp_path, repo, docker=False)
        mgr._setup_dotenv(wt_path, docker=False)

        env_dst = wt_path / ".env"
        assert env_dst.is_symlink()
        assert env_dst.read_text() == "SECRET=abc\n"

    def test_copies_env_in_docker_mode(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "repo")
        (repo / ".env").write_text("SECRET=xyz\n")
        wt_path = tmp_path / "workspace"
        wt_path.mkdir()

        mgr = self._make_manager(tmp_path, repo, docker=True)
        mgr._setup_dotenv(wt_path, docker=True)

        env_dst = wt_path / ".env"
        assert not env_dst.is_symlink()
        assert env_dst.read_text() == "SECRET=xyz\n"

    def test_no_env_file_is_noop(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "repo")
        wt_path = tmp_path / "workspace"
        wt_path.mkdir()

        mgr = self._make_manager(tmp_path, repo, docker=False)
        mgr._setup_dotenv(wt_path, docker=False)

        assert not (wt_path / ".env").exists()


class TestSetupClaudeSettings:
    """Integration tests for WorkspaceManager._setup_claude_settings."""

    def _make_manager(self, tmp_path: Path, repo: Path):
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            repo_root=repo,
            worktree_base=tmp_path / "worktrees",
        )
        from workspace import WorkspaceManager

        return WorkspaceManager(config)

    def test_copies_settings_file(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "repo")
        settings_dir = repo / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.local.json").write_text('{"key": "value"}')

        wt_path = tmp_path / "workspace"
        wt_path.mkdir()

        mgr = self._make_manager(tmp_path, repo)
        mgr._setup_claude_settings(wt_path)

        dst = wt_path / ".claude" / "settings.local.json"
        assert dst.exists()
        assert dst.read_text() == '{"key": "value"}'

    def test_no_settings_is_noop(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "repo")
        wt_path = tmp_path / "workspace"
        wt_path.mkdir()

        mgr = self._make_manager(tmp_path, repo)
        mgr._setup_claude_settings(wt_path)

        assert not (wt_path / ".claude").exists()


# ---------------------------------------------------------------------------
# Workspace destroy
# ---------------------------------------------------------------------------


class TestWorkspaceDestroy:
    """Integration tests for workspace destroy operations."""

    @pytest.mark.asyncio
    async def test_destroy_removes_directory(self, tmp_path: Path) -> None:
        from tests.helpers import ConfigFactory

        repo = _make_repo(tmp_path, "repo")
        config = ConfigFactory.create(
            repo_root=repo,
            worktree_base=tmp_path / "worktrees",
        )
        from workspace import WorkspaceManager

        mgr = WorkspaceManager(config)

        # Create the workspace directory manually
        wt_path = config.worktree_path_for_issue(42)
        wt_path.mkdir(parents=True, exist_ok=True)
        (wt_path / "file.txt").write_text("test")

        await mgr.destroy(42)
        assert not wt_path.exists()

    @pytest.mark.asyncio
    async def test_destroy_nonexistent_is_noop(self, tmp_path: Path) -> None:
        from tests.helpers import ConfigFactory

        repo = _make_repo(tmp_path, "repo")
        config = ConfigFactory.create(
            repo_root=repo,
            worktree_base=tmp_path / "worktrees",
        )
        from workspace import WorkspaceManager

        mgr = WorkspaceManager(config)
        # Should not raise
        await mgr.destroy(999)


# ---------------------------------------------------------------------------
# UI directory detection
# ---------------------------------------------------------------------------


class TestDetectUiDirs:
    """Integration tests for WorkspaceManager._detect_ui_dirs."""

    def test_detects_package_json_in_subdirs(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "repo")
        ui_dir = repo / "src" / "ui"
        ui_dir.mkdir(parents=True)
        (ui_dir / "package.json").write_text("{}")

        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            repo_root=repo,
            worktree_base=tmp_path / "worktrees",
        )
        from workspace import WorkspaceManager

        mgr = WorkspaceManager(config)
        assert "src/ui" in mgr._ui_dirs

    def test_ignores_node_modules(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "repo")
        nm = repo / "node_modules" / "some-pkg"
        nm.mkdir(parents=True)
        (nm / "package.json").write_text("{}")

        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            repo_root=repo,
            worktree_base=tmp_path / "worktrees",
        )
        from workspace import WorkspaceManager

        mgr = WorkspaceManager(config)
        assert all("node_modules" not in d for d in mgr._ui_dirs)

    def test_ignores_root_package_json(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, "repo")
        (repo / "package.json").write_text("{}")

        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            repo_root=repo,
            worktree_base=tmp_path / "worktrees",
        )
        from workspace import WorkspaceManager

        mgr = WorkspaceManager(config)
        assert "." not in mgr._ui_dirs


# ---------------------------------------------------------------------------
# Git clone integration (local-only, no remote)
# ---------------------------------------------------------------------------


class TestLocalGitClone:
    """Integration tests verifying git clone --local produces valid repos."""

    def test_local_clone_has_independent_git(self, tmp_path: Path) -> None:
        """A local clone has its own .git directory."""
        repo = _make_repo(tmp_path, "origin")
        clone_path = tmp_path / "clone"

        env = {**os.environ, **_GIT_ENV}
        subprocess.run(
            ["git", "clone", "--local", str(repo), str(clone_path)],
            check=True,
            capture_output=True,
            env=env,
        )

        assert (clone_path / ".git").exists()
        assert (clone_path / "README.md").read_text() == "# Test\n"

    def test_local_clone_branch_creation(self, tmp_path: Path) -> None:
        """Can create a new branch on a local clone."""
        repo = _make_repo(tmp_path, "origin")
        clone_path = tmp_path / "clone"

        env = {**os.environ, **_GIT_ENV}
        subprocess.run(
            ["git", "clone", "--local", str(repo), str(clone_path)],
            check=True,
            capture_output=True,
            env=env,
        )

        _git(clone_path, "checkout", "-b", "agent/issue-42")
        (clone_path / "new_file.py").write_text("print('hello')\n")
        _git(clone_path, "add", ".")
        _git(clone_path, "commit", "-m", "add file")

        # Verify branch exists with commit
        log = _git(clone_path, "log", "--oneline", "-1")
        assert "add file" in log

    def test_local_clone_merge(self, tmp_path: Path) -> None:
        """A local clone can merge changes from the origin."""
        repo = _make_repo(tmp_path, "origin")
        clone_path = tmp_path / "clone"

        env = {**os.environ, **_GIT_ENV}
        subprocess.run(
            ["git", "clone", "--local", str(repo), str(clone_path)],
            check=True,
            capture_output=True,
            env=env,
        )

        # Create a branch in the clone
        _git(clone_path, "checkout", "-b", "feature")
        (clone_path / "feature.py").write_text("x = 1\n")
        _git(clone_path, "add", ".")
        _git(clone_path, "commit", "-m", "feature commit")

        # Add a commit to main in origin
        (repo / "main_change.py").write_text("y = 2\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "main change")

        # Fetch and merge from origin
        _git(clone_path, "fetch", "origin", "main")
        _git(clone_path, "merge", "origin/main", "--no-edit")

        # Both files should exist
        assert (clone_path / "feature.py").exists()
        assert (clone_path / "main_change.py").exists()
