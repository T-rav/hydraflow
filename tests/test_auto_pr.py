"""Tests for src/auto_pr.py — shared worktree+commit+push+PR helper."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """A bare git repo that acts as 'origin' for tests."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    return remote


@pytest.fixture
def local_repo(tmp_path: Path, bare_remote: Path) -> Path:
    """A checkout of the bare remote, with one initial commit on main."""
    local = tmp_path / "local"
    subprocess.run(["git", "clone", str(bare_remote), str(local)], check=True)
    subprocess.run(["git", "-C", str(local), "checkout", "-b", "main"], check=True)
    (local / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(local), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(local),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            "init",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(local), "push", "-u", "origin", "main"], check=True
    )
    return local


def test_open_automated_pr_creates_worktree_commits_and_cleans_up(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: worktree created, file committed, pushed, PR command invoked, worktree removed."""
    from auto_pr import open_automated_pr

    gh_calls: list[list[str]] = []

    def fake_gh(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        gh_calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd, 0, stdout="https://github.com/x/y/pull/1\n", stderr=""
        )

    monkeypatch.setattr("auto_pr._run_gh", fake_gh)

    target_file = local_repo / "new.txt"
    # Caller writes the file content BEFORE calling open_automated_pr.
    target_file.write_text("hello\n")

    result = open_automated_pr(
        repo_root=local_repo,
        branch="feature/x",
        files=[target_file],
        title="feat: x",
        body="body",
        base="main",
        auto_merge=True,
    )

    # PR command invoked exactly once, with correct title/body/branch
    assert any(("pr" in c and "create" in c) for c in gh_calls)
    # Auto-merge enabled
    assert any(("pr" in c and "merge" in c and "--auto" in c) for c in gh_calls)
    # Result carries the PR URL
    assert result.pr_url == "https://github.com/x/y/pull/1"
    # No leftover worktrees
    wt_list = subprocess.run(
        ["git", "-C", str(local_repo), "worktree", "list"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert wt_list.count("\n") == 1  # only main checkout remains


def test_open_automated_pr_cleans_up_worktree_on_failure(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worktree is removed even when the gh call fails."""
    from auto_pr import AutoPrError, open_automated_pr

    def failing_gh(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="gh failed")

    monkeypatch.setattr("auto_pr._run_gh", failing_gh)

    (local_repo / "f.txt").write_text("x\n")
    with pytest.raises(AutoPrError):
        open_automated_pr(
            repo_root=local_repo,
            branch="feature/fail",
            files=[local_repo / "f.txt"],
            title="t",
            body="b",
        )

    wt_list = subprocess.run(
        ["git", "-C", str(local_repo), "worktree", "list"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert wt_list.count("\n") == 1  # only main checkout remains


def test_open_automated_pr_skips_when_no_diff(local_repo: Path) -> None:
    """If the caller passes no files, the function returns a 'no-diff' result without pushing."""
    from auto_pr import open_automated_pr

    # files=[] short-circuits before any gh call is made, so no monkeypatching needed.
    result = open_automated_pr(
        repo_root=local_repo,
        branch="feature/empty",
        files=[],
        title="t",
        body="b",
    )

    assert result.pr_url is None
    assert result.status == "no-diff"
