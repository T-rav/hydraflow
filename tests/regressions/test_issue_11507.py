"""Real-git regression for #11507 — GC phases 1-2 never destroy unlanded work.

Before #11530, ``WorkspaceGCLoop._do_work`` phase 1 (tracked-state sweep) and
phase 2 (``_collect_orphaned_dirs``) called ``WorkspacePort.destroy`` on
``_is_safe_to_gc`` alone. Every closed issue was destroyable with no check
that its ``issue-<N>`` worktree's commits had ever been pushed or merged, so
closing an issue as not-planned while an agent still held unpushed commits
lost that work on the next GC cycle — the #10459/#6413 invariant, violated on
the standard factory path that phase 5 had already been guarding.

These pins run a full ``_do_work`` cycle against a REAL git repository (bare
remote + clone + registered ``issue-<N>`` worktrees) with the real
``FakeGitHub`` PRPort — no mocked ``run_subprocess`` — so the shared
``_worktree_work_has_landed`` predicate is proven on both phases against
actual git semantics rather than a stubbed contract.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_workspace import FakeWorkspace
from state import StateTracker
from tests.helpers import BgLoopDeps, make_bg_loop_deps
from workspace_gc_loop import WorkspaceGCLoop

_TRACKED_UNPUSHED = 11507
_ORPHAN_UNPUSHED = 11508
_TRACKED_CLEAN = 11509
_ORPHAN_SQUASHED = 11510


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit_exists(repo: Path, sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


@pytest.fixture
def deps(tmp_path: Path) -> BgLoopDeps:
    """Loop deps whose ``repo_root`` is a real clone with ``origin/staging``.

    Phase 5 is disabled so the pins isolate phases 1-2 — the standard
    ``issue-<N>`` paths are skipped by the all-root sweep anyway.
    """
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
        workspace_base=tmp_path / "workspaces",
        worktree_gc_all_roots_enabled=False,
        worktree_gc_min_age_seconds=0,
    )


def _add_issue_worktree(deps: BgLoopDeps, issue_number: int) -> tuple[Path, str]:
    """Register a real ``issue-<N>`` worktree on ``agent/issue-<N>`` off staging."""
    config = deps.config
    path = config.workspace_path_for_issue(issue_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    branch = config.branch_for_issue(issue_number)
    _git(config.repo_root, "worktree", "add", "-b", branch, str(path), "staging")
    return path, branch


def _commit_unpushed_work(path: Path, issue_number: int) -> str:
    """Leave the only copy of a commit in *path*; never push it anywhere."""
    (path / f"only-copy-{issue_number}.txt").write_text("must survive GC\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", f"unpushed work for #{issue_number}")
    return _git(path, "rev-parse", "HEAD")


def _make_loop(
    deps: BgLoopDeps, github: FakeGitHub, state: StateTracker
) -> tuple[WorkspaceGCLoop, FakeWorkspace]:
    workspaces = FakeWorkspace(deps.config.workspace_base)
    loop = WorkspaceGCLoop(
        config=deps.config,
        workspaces=workspaces,
        prs=github,
        state=state,
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda _issue: False,
    )
    return loop, workspaces


def _closed_not_planned(github: FakeGitHub, issue_number: int) -> None:
    github.add_issue(issue_number, f"Issue {issue_number}", "", state="closed")
    github.issue(issue_number).state_reason = "NOT_PLANNED"


class TestPhasesOneAndTwoRequireLandedWork:
    """#11507: issue closure is never sufficient to destroy an issue-N worktree."""

    @pytest.mark.asyncio
    async def test_phase1_keeps_tracked_closed_issue_with_unpushed_commit(
        self, deps: BgLoopDeps
    ) -> None:
        """Closed-as-not-planned + tracked in state + unpushed commit ⇒ skipped,
        state entry retained, commit and files untouched."""
        path, branch = _add_issue_worktree(deps, _TRACKED_UNPUSHED)
        sha = _commit_unpushed_work(path, _TRACKED_UNPUSHED)
        github = FakeGitHub()
        _closed_not_planned(github, _TRACKED_UNPUSHED)
        state = StateTracker(deps.config.state_file)
        state.set_workspace(_TRACKED_UNPUSHED, str(path))
        state.set_branch(_TRACKED_UNPUSHED, branch)
        loop, workspaces = _make_loop(deps, github, state)

        result = await loop._do_work()

        assert result == {"collected": 0, "skipped": 1, "errors": 0}
        assert workspaces.destroyed == []
        assert state.get_active_workspaces() == {_TRACKED_UNPUSHED: str(path)}
        assert (
            _git(path, "rev-parse", "HEAD"),
            _commit_exists(deps.config.repo_root, sha),
        ) == (
            sha,
            True,
        )
        assert (
            path / f"only-copy-{_TRACKED_UNPUSHED}.txt"
        ).read_text() == "must survive GC\n"

    @pytest.mark.asyncio
    async def test_phase2_keeps_orphaned_closed_issue_dir_with_unpushed_commit(
        self, deps: BgLoopDeps
    ) -> None:
        """Same invariant on the orphan-dir scan: an untracked ``issue-<N>`` dir
        whose branch holds an unpushed commit is never destroyed."""
        path, _branch = _add_issue_worktree(deps, _ORPHAN_UNPUSHED)
        sha = _commit_unpushed_work(path, _ORPHAN_UNPUSHED)
        github = FakeGitHub()
        _closed_not_planned(github, _ORPHAN_UNPUSHED)
        loop, workspaces = _make_loop(
            deps, github, StateTracker(deps.config.state_file)
        )

        result = await loop._do_work()

        assert result == {"collected": 0, "skipped": 0, "errors": 0}
        assert workspaces.destroyed == []
        assert (path.exists(), _commit_exists(deps.config.repo_root, sha)) == (
            True,
            True,
        )

    @pytest.mark.asyncio
    async def test_phase1_fails_closed_when_base_ref_is_unknown(
        self, deps: BgLoopDeps
    ) -> None:
        """A git error inside the landed check (``origin/staging`` missing) must
        skip, not destroy — even for a worktree with no unique commits."""
        path, branch = _add_issue_worktree(deps, _TRACKED_CLEAN)
        _git(deps.config.repo_root, "update-ref", "-d", "refs/remotes/origin/staging")
        github = FakeGitHub()
        github.add_issue(_TRACKED_CLEAN, "Clean", "", state="closed")
        state = StateTracker(deps.config.state_file)
        state.set_workspace(_TRACKED_CLEAN, str(path))
        state.set_branch(_TRACKED_CLEAN, branch)
        loop, workspaces = _make_loop(deps, github, state)

        result = await loop._do_work()

        assert result == {"collected": 0, "skipped": 1, "errors": 0}
        assert workspaces.destroyed == []
        assert _TRACKED_CLEAN in state.get_active_workspaces()

    @pytest.mark.asyncio
    async def test_phases_1_and_2_still_collect_landed_issue_worktrees(
        self, deps: BgLoopDeps
    ) -> None:
        """Liveness: the guard must not freeze collection. A tracked worktree
        with no unique commits (phase 1) and an orphaned worktree whose exact
        HEAD was squash-merged into staging before staging advanced (phase 2)
        are both still collected in one cycle."""
        repo = deps.config.repo_root
        clean_path, clean_branch = _add_issue_worktree(deps, _TRACKED_CLEAN)
        squashed_path, squashed_branch = _add_issue_worktree(deps, _ORPHAN_SQUASHED)
        (squashed_path / "feature.txt").write_text("squash me\n")
        _git(squashed_path, "add", "feature.txt")
        _git(squashed_path, "commit", "-m", "feature to squash")
        merged_head = _git(squashed_path, "rev-parse", "HEAD")
        _git(squashed_path, "push", "-u", "origin", squashed_branch)
        # GitHub-style squash merge: same tree, brand-new SHA on staging, then
        # staging advances so neither ancestry nor the two-rev tree diff can
        # prove the squash — only the exact historical PR HEAD can.
        _git(repo, "merge", "--squash", squashed_branch)
        _git(repo, "commit", "-m", f"squash-merge #{_ORPHAN_SQUASHED}")
        (repo / "later.txt").write_text("staging advanced\n")
        _git(repo, "add", "later.txt")
        _git(repo, "commit", "-m", "advance staging")
        _git(repo, "push", "origin", "staging")
        _git(squashed_path, "fetch", "origin", "staging")

        github = FakeGitHub()
        github.add_issue(_TRACKED_CLEAN, "Clean", "", state="closed")
        github.add_issue(_ORPHAN_SQUASHED, "Squashed", "", state="closed")
        github.add_pr(
            number=_ORPHAN_SQUASHED,
            issue_number=_ORPHAN_SQUASHED,
            branch=squashed_branch,
            head_sha=merged_head,
            base_branch="staging",
            merged=True,
        )
        state = StateTracker(deps.config.state_file)
        state.set_workspace(_TRACKED_CLEAN, str(clean_path))
        state.set_branch(_TRACKED_CLEAN, clean_branch)
        loop, workspaces = _make_loop(deps, github, state)

        result = await loop._do_work()

        assert (result["collected"], result["errors"]) == (2, 0)
        assert workspaces.destroyed == [_TRACKED_CLEAN, _ORPHAN_SQUASHED]
        assert state.get_active_workspaces() == {}
