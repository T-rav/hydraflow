"""Real-git regression for #11503 — closed issues still require landed work.

``WorkspaceGCLoop._reap_worktree_if_safe`` (phase 5, all-root sweep) used to
bypass the unmerged-commit guard entirely whenever the attributed issue's
state was ``"closed"``, on the docstring claim that "a closed issue is
authoritatively merged/abandoned". That is false for an issue closed as
not-planned/duplicate/wontfix while its worktree still holds commits that
were never pushed or merged — exactly the #10459/#6413 data-loss invariant the
guard exists to protect.

Since #11530 every reap path shares one HEAD-aware landed proof and issue
closure is never a shortcut past it. These pins drive the real reap decision
— real ``_is_safe_to_gc`` policy over ``FakeGitHub``, real git worktrees on a
bare remote, no mocked ``run_subprocess`` — so the closed-issue path is proven
against actual git semantics, including the squash-merge shapes that must
still reap (the fix must not freeze collection).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mockworld.fakes.fake_github import FakeGitHub
from state import StateTracker
from tests.helpers import BgLoopDeps, make_bg_loop_deps
from workspace_gc_loop import WorkspaceGCLoop

_ISSUE = 11503
_BRANCH = f"fix/closed-issue-landed-{_ISSUE}"  # attributes to _ISSUE via fix/*-N


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def deps(tmp_path: Path) -> BgLoopDeps:
    """Loop deps whose ``repo_root`` is a real clone with ``origin/staging``."""
    remote = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "clone", str(remote), str(repo)], check=True, capture_output=True
    )
    _git(repo, "config", "user.name", "Workspace GC Test")
    _git(repo, "config", "user.email", "workspace-gc@example.test")
    _git(repo, "checkout", "-b", "staging")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "seed staging")
    _git(repo, "push", "-u", "origin", "staging")
    return make_bg_loop_deps(
        tmp_path,
        staging_enabled=True,
        worktree_gc_roots=[str(tmp_path / "gc-roots")],
        worktree_gc_min_age_seconds=0,
    )


def _add_worktree(deps: BgLoopDeps) -> Path:
    path = Path(deps.config.worktree_gc_root_paths()[0]) / f"wt-{_ISSUE}"
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(deps.config.repo_root, "worktree", "add", "-b", _BRANCH, str(path), "staging")
    return path


def _commit(path: Path, filename: str, content: str, message: str) -> str:
    (path / filename).write_text(content)
    _git(path, "add", filename)
    _git(path, "commit", "-m", message)
    return _git(path, "rev-parse", "HEAD")


def _squash_onto_staging(deps: BgLoopDeps, path: Path, *, advance: bool) -> None:
    """Replay *path*'s branch onto staging as one NEW commit (GitHub squash)."""
    repo = deps.config.repo_root
    _git(repo, "merge", "--squash", _BRANCH)
    _git(repo, "commit", "-m", f"squash-merge #{_ISSUE}")
    if advance:
        (repo / "later.txt").write_text("staging advanced\n")
        _git(repo, "add", "later.txt")
        _git(repo, "commit", "-m", "advance staging")
    _git(repo, "push", "origin", "staging")
    _git(path, "fetch", "origin", "staging")


def _make_loop(
    deps: BgLoopDeps, *, state_reason: str = "", github: FakeGitHub | None = None
) -> WorkspaceGCLoop:
    github = github or FakeGitHub()
    github.add_issue(_ISSUE, f"Issue {_ISSUE}", "", state="closed")
    github.issue(_ISSUE).state_reason = state_reason
    return WorkspaceGCLoop(
        config=deps.config,
        workspaces=MagicMock(),
        prs=github,
        state=StateTracker(deps.config.state_file),
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda _issue: False,
    )


class TestClosedIssueStillRequiresLandedWork:
    """#11503: closed-issue attribution must not bypass the landed proof."""

    @pytest.mark.asyncio
    async def test_closed_not_planned_issue_with_unpushed_commit_is_kept(
        self, deps: BgLoopDeps
    ) -> None:
        """The data-loss shape from the issue: closed as not-planned while the
        worktree holds the only copy of a commit. Must NOT be reaped."""
        path = _add_worktree(deps)
        sha = _commit(path, "feature.txt", "work in progress\n", "unpushed work")
        loop = _make_loop(deps, state_reason="NOT_PLANNED")

        reaped = await loop._reap_worktree_if_safe(path, _BRANCH, _ISSUE)

        assert reaped is False
        assert (path.exists(), _git(path, "rev-parse", "HEAD")) == (True, sha)
        assert _git(deps.config.repo_root, "branch", "--list", _BRANCH) != ""

    @pytest.mark.asyncio
    async def test_closed_issue_with_no_unique_commits_is_reaped(
        self, deps: BgLoopDeps
    ) -> None:
        """Liveness: a closed issue whose worktree is identical to
        ``origin/staging`` is still reaped — the fix must not freeze GC."""
        path = _add_worktree(deps)
        loop = _make_loop(deps)

        reaped = await loop._reap_worktree_if_safe(path, _BRANCH, _ISSUE)

        assert reaped is True
        assert not path.exists()
        assert _git(deps.config.repo_root, "branch", "--list", _BRANCH) == ""

    @pytest.mark.asyncio
    async def test_closed_issue_squash_merged_before_base_advances_is_reaped(
        self, deps: BgLoopDeps
    ) -> None:
        """Ancestry still reports the squashed commit as unique, but the
        two-rev tree diff against ``origin/staging`` is empty — landed by
        content, no PR evidence needed."""
        path = _add_worktree(deps)
        _commit(path, "feature.txt", "squash me\n", "work to be squashed")
        _squash_onto_staging(deps, path, advance=False)
        loop = _make_loop(deps)

        assert int(_git(path, "rev-list", "--count", "origin/staging..HEAD")) > 0
        reaped = await loop._reap_worktree_if_safe(path, _BRANCH, _ISSUE)

        assert reaped is True
        assert not path.exists()

    @pytest.mark.asyncio
    async def test_closed_issue_squash_merged_after_base_advances_is_kept_without_pr(
        self, deps: BgLoopDeps
    ) -> None:
        """Once staging advances past the squash, neither ancestry nor content
        can prove the landing; with no PR on record for this exact HEAD the
        proof fails closed and the worktree is kept."""
        path = _add_worktree(deps)
        _commit(path, "feature.txt", "squash me\n", "work to be squashed")
        _squash_onto_staging(deps, path, advance=True)
        loop = _make_loop(deps)

        reaped = await loop._reap_worktree_if_safe(path, _BRANCH, _ISSUE)

        assert (reaped, path.exists()) == (False, True)

    @pytest.mark.asyncio
    async def test_closed_issue_squash_merged_after_base_advances_is_reaped_with_exact_head_pr(
        self, deps: BgLoopDeps
    ) -> None:
        """The authoritative rung: a merged PR into staging whose historical
        head is this worktree's exact HEAD proves the squash landed."""
        path = _add_worktree(deps)
        merged_head = _commit(path, "feature.txt", "squash me\n", "work to be squashed")
        _squash_onto_staging(deps, path, advance=True)
        github = FakeGitHub()
        github.add_pr(
            number=_ISSUE,
            issue_number=_ISSUE,
            branch=_BRANCH,
            head_sha=merged_head,
            base_branch="staging",
            merged=True,
        )
        loop = _make_loop(deps, github=github)

        reaped = await loop._reap_worktree_if_safe(path, _BRANCH, _ISSUE)

        assert reaped is True
        assert not path.exists()
