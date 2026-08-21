"""Regression test for #11501.

`git worktree add <dir> <branch>` fails loudly when `<dir>` already exists,
but the failure is easy to miss: in a chained shell invocation
(`git worktree add ...; cd ...; git merge ...`) the later commands still run
against whatever branch the stale directory happened to be checked out to.
`scripts/hf_worktree.sh` is the safe wrapper: create when the dir is absent,
succeed silently (idempotent) when the dir already holds the requested
branch, and fail loudly -- without ever deleting or repointing the directory
-- on any other mismatch (different branch, detached HEAD, or a directory
that isn't a registered worktree at all).
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "hf_worktree.sh"

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, **_GIT_ENV}
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
        env=env,
    )


def _make_repo(base: Path) -> Path:
    """Minimal git repo on `main`, plus two divergent branches to mismatch between."""
    repo = base / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("# Test\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    _git(repo, "branch", "feature-a")
    _git(repo, "branch", "feature-b")
    return repo


def _run_helper(repo: Path, target_dir: str, branch: str) -> subprocess.CompletedProcess:
    env = {**os.environ, **_GIT_ENV}
    return subprocess.run(
        [str(HELPER), target_dir, branch],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


class TestHelperExists:
    def test_script_exists_and_is_executable(self) -> None:
        assert HELPER.exists(), "scripts/hf_worktree.sh must exist"
        mode = HELPER.stat().st_mode
        assert mode & stat.S_IXUSR, "scripts/hf_worktree.sh must be executable"


class TestAbsentDirectory:
    def test_creates_worktree_when_dir_absent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)

        result = _run_helper(repo, "wt-absent", "feature-a")

        assert result.returncode == 0, result.stderr
        target = repo / "wt-absent"
        assert target.is_dir()
        branch = _git(target, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        assert branch == "feature-a"

    def test_prints_resolved_branch_on_success(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)

        result = _run_helper(repo, "wt-absent2", "feature-a")

        assert "feature-a" in result.stdout

    def test_invalid_branch_name_propagates_git_failure(self, tmp_path: Path) -> None:
        """Error-path coverage: an upstream git failure unrelated to the
        existing-dir case (typo'd branch name) must not be swallowed."""
        repo = _make_repo(tmp_path)

        result = _run_helper(repo, "wt-badbranch", "does-not-exist-anywhere")

        assert result.returncode != 0
        registered = _git(repo, "worktree", "list").stdout
        assert "wt-badbranch" not in registered


class TestMatchingBranch:
    def test_exit_zero_when_dir_already_on_requested_branch(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _git(repo, "worktree", "add", "wt-match", "feature-a")

        result = _run_helper(repo, "wt-match", "feature-a")

        assert result.returncode == 0, result.stderr
        assert "feature-a" in result.stdout


class TestMismatchedBranch:
    def test_nonzero_exit_names_expected_and_actual_branch(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _git(repo, "worktree", "add", "wt-mismatch", "feature-b")

        result = _run_helper(repo, "wt-mismatch", "feature-a")

        assert result.returncode != 0
        assert "feature-a" in result.stderr
        assert "feature-b" in result.stderr

    def test_prints_worktree_remove_command(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _git(repo, "worktree", "add", "wt-mismatch2", "feature-b")

        result = _run_helper(repo, "wt-mismatch2", "feature-a")

        assert "git worktree remove wt-mismatch2" in result.stderr

    def test_stale_worktree_and_uncommitted_work_survive_mismatch(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _git(repo, "worktree", "add", "wt-mismatch3", "feature-b")
        stale_dir = repo / "wt-mismatch3"
        (stale_dir / "scratch.txt").write_text("uncommitted work\n")

        result = _run_helper(repo, "wt-mismatch3", "feature-a")

        assert result.returncode != 0
        assert stale_dir.is_dir()
        assert (stale_dir / "scratch.txt").read_text() == "uncommitted work\n"
        branch = _git(stale_dir, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        assert branch == "feature-b"

    def test_enumerates_registered_worktrees_in_mismatch_message(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _git(repo, "worktree", "add", "wt-mismatch4", "feature-b")

        result = _run_helper(repo, "wt-mismatch4", "feature-a")

        assert "wt-mismatch4" in result.stderr
        # the runtime `git worktree list` enumeration includes the main worktree too
        assert str(repo) in result.stderr


class TestNonWorktreeDirectory:
    def test_nonzero_when_dir_exists_but_is_not_a_registered_worktree(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo(tmp_path)
        plain_dir = repo / "plain-dir"
        plain_dir.mkdir()
        (plain_dir / "file.txt").write_text("hi\n")

        result = _run_helper(repo, "plain-dir", "feature-a")

        assert result.returncode != 0
        # never touched: no delete, no repoint
        assert (plain_dir / "file.txt").read_text() == "hi\n"


class TestDetachedHead:
    def test_detached_head_reported_and_treated_as_mismatch(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = _git(repo, "rev-parse", "feature-b").stdout.strip()
        _git(repo, "worktree", "add", "--detach", "wt-detached", sha)

        result = _run_helper(repo, "wt-detached", "feature-a")

        assert result.returncode != 0
        assert "detached" in result.stderr.lower()
        assert sha[:7] in result.stderr


class TestArgValidation:
    def test_missing_args_prints_usage_and_exits_nonzero(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)

        result = subprocess.run([str(HELPER)], cwd=repo, capture_output=True, text=True)

        assert result.returncode != 0
        assert "usage" in (result.stdout + result.stderr).lower()

    def test_single_arg_prints_usage_and_exits_nonzero(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)

        result = subprocess.run(
            [str(HELPER), "only-a-dir"], cwd=repo, capture_output=True, text=True
        )

        assert result.returncode != 0
        assert "usage" in (result.stdout + result.stderr).lower()

    def test_extra_args_prints_usage_and_exits_nonzero(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)

        result = subprocess.run(
            [str(HELPER), "dir", "branch", "extra"],
            cwd=repo,
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "usage" in (result.stdout + result.stderr).lower()


class TestSubdirectoryInvocation:
    def test_works_when_invoked_from_a_repo_subdirectory(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        subdir = repo / "src"
        subdir.mkdir()

        env = {**os.environ, **_GIT_ENV}
        result = subprocess.run(
            [str(HELPER), "../wt-from-subdir", "feature-a"],
            cwd=subdir,
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        target = repo / "wt-from-subdir"
        assert target.is_dir()


class TestDocumentation:
    def test_claude_md_documents_the_helper(self) -> None:
        text = (REPO_ROOT / "CLAUDE.md").read_text()
        assert "hf_worktree.sh" in text

    def test_gotchas_documents_the_helper(self) -> None:
        text = (REPO_ROOT / "docs" / "wiki" / "gotchas.md").read_text()
        assert "hf_worktree.sh" in text


class TestLivenessCounterPin:
    """Proves the sandbox actually reproduces the bug the helper fixes. If this
    test ever goes green for the wrong reason (`git worktree add` stops
    failing on an existing dir, or `cd` stops succeeding into a stale one),
    the fix in hf_worktree.sh would no longer be addressing a real defect."""

    def test_bare_chained_recipe_succeeds_on_wrong_branch(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _git(repo, "worktree", "add", "stale-dir", "feature-b")

        chained = (
            "git worktree add stale-dir feature-a; "
            "cd stale-dir && git rev-parse --abbrev-ref HEAD"
        )
        result = subprocess.run(
            ["sh", "-c", chained],
            cwd=repo,
            capture_output=True,
            text=True,
            env={**os.environ, **_GIT_ENV},
        )

        assert "already exists" in result.stderr.lower()
        assert result.stdout.strip() == "feature-b"
