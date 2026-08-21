"""Real-git regression for #11570 — a tracked entry whose directory is gone is pruned.

Since #11530, phase 1 of ``WorkspaceGCLoop._do_work`` gates ``remove_workspace``
+ ``destroy`` on the landed proof, whose preflight fails closed on a missing
path. A tracked ``active_workspaces`` entry whose directory was removed
out-of-band (review/HITL cleanup crashing between ``destroy`` and state
removal, or an operator ``rm -rf``) was therefore logged "unlanded work —
skipping" on every cycle forever, and ``issue_number in active_workspaces``
kept phases 3-4 from ever judging that issue's branch or branch-state entry.

The fix distinguishes "gone" (nothing at the destroy target while the
repo-scoped workspace root is present) from "unavailable" (the root itself is
missing — the #6413 transient-mount shape) and from "present but unlanded".
Only the first is pruned, and only state is touched: nothing is destroyed and
no branch is deleted on this path. These pins run full ``_do_work`` cycles
against a REAL git repository with the real ``FakeGitHub`` PRPort — no mocked
``run_subprocess``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_workspace import FakeWorkspace
from state import StateTracker
from tests.helpers import BgLoopDeps, make_bg_loop_deps
from workspace_gc_loop import WorkspaceGCLoop

_GONE = 11570
_UNAVAILABLE = 11577
_PRESENT_UNLANDED = 11578
_GC_LOGGER = "hydraflow.workspace_gc_loop"


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
        workspace_base=tmp_path / "workspaces",
        worktree_gc_all_roots_enabled=False,
        worktree_gc_min_age_seconds=0,
    )


def _add_tracked_issue_worktree(
    deps: BgLoopDeps, state: StateTracker, issue_number: int
) -> tuple[Path, str, str]:
    """Register a real ``issue-<N>`` worktree, track it, and leave an unpushed commit."""
    config = deps.config
    path = config.workspace_path_for_issue(issue_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    branch = config.branch_for_issue(issue_number)
    _git(config.repo_root, "worktree", "add", "-b", branch, str(path), "staging")
    (path / f"only-copy-{issue_number}.txt").write_text("must survive GC\n")
    _git(path, "add", ".")
    _git(path, "commit", "-m", f"unpushed work for #{issue_number}")
    sha = _git(path, "rev-parse", "HEAD")
    state.set_workspace(issue_number, str(path))
    state.set_branch(issue_number, branch)
    return path, branch, sha


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


def _gc_records(caplog: pytest.LogCaptureFixture, *, level: int) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _GC_LOGGER and record.levelno == level
    ]


class TestPhaseOneMissingDirectory:
    """#11570: gone is pruned; unavailable and present-but-unlanded stay fail-closed."""

    @pytest.mark.asyncio
    async def test_tracked_entry_whose_dir_is_gone_is_pruned_without_destroying(
        self, deps: BgLoopDeps, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Directory removed out-of-band and its registration pruned (the
        most adversarial shape: nothing protects the branch but the phase-3
        proof). One cycle evicts the workspace entry at INFO, destroys
        nothing, and the unpushed branch survives phase 3 (#11571)."""
        repo = deps.config.repo_root
        github = FakeGitHub()
        _closed_not_planned(github, _GONE)
        state = StateTracker(deps.config.state_file)
        path, branch, sha = _add_tracked_issue_worktree(deps, state, _GONE)
        shutil.rmtree(path)
        _git(repo, "worktree", "prune")
        loop, workspaces = _make_loop(deps, github, state)

        with caplog.at_level(logging.DEBUG, logger=_GC_LOGGER):
            result = await loop._do_work()

        assert result == {"collected": 2, "skipped": 0, "errors": 0}
        assert workspaces.destroyed == []
        assert (state.get_active_workspaces(), state.get_branch(_GONE)) == ({}, None)
        assert (
            _git(repo, "rev-parse", branch),
            _commit_exists(repo, sha),
        ) == (sha, True)
        assert _gc_records(caplog, level=logging.WARNING) == []
        assert any(
            "pruned tracked workspace entry" in message and str(_GONE) in message
            for message in _gc_records(caplog, level=logging.INFO)
        )

    @pytest.mark.asyncio
    async def test_tracked_entry_is_kept_when_workspace_root_is_unavailable(
        self, deps: BgLoopDeps
    ) -> None:
        """The whole ``workspace_base/<slug>`` root missing is the transient
        mount shape (#6413): indistinguishable from "gone" at the path
        level, so the entry stays and nothing is destroyed."""
        github = FakeGitHub()
        _closed_not_planned(github, _UNAVAILABLE)
        state = StateTracker(deps.config.state_file)
        path, _branch, _sha = _add_tracked_issue_worktree(deps, state, _UNAVAILABLE)
        shutil.rmtree(deps.config.workspace_base)
        loop, workspaces = _make_loop(deps, github, state)

        result = await loop._do_work()

        assert result == {"collected": 0, "skipped": 1, "errors": 0}
        assert workspaces.destroyed == []
        assert state.get_active_workspaces() == {_UNAVAILABLE: str(path)}

    @pytest.mark.asyncio
    async def test_tracked_entry_with_existing_unlanded_worktree_is_still_skipped(
        self, deps: BgLoopDeps, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The contrast case: the directory exists and holds unlanded work.
        That is the #11507 shape and must keep failing closed — the new
        prune keys on the path being absent, never on the proof failing."""
        github = FakeGitHub()
        _closed_not_planned(github, _PRESENT_UNLANDED)
        state = StateTracker(deps.config.state_file)
        path, _branch, sha = _add_tracked_issue_worktree(deps, state, _PRESENT_UNLANDED)
        loop, workspaces = _make_loop(deps, github, state)

        with caplog.at_level(logging.DEBUG, logger=_GC_LOGGER):
            result = await loop._do_work()

        assert result == {"collected": 0, "skipped": 1, "errors": 0}
        assert workspaces.destroyed == []
        assert state.get_active_workspaces() == {_PRESENT_UNLANDED: str(path)}
        assert _git(path, "rev-parse", "HEAD") == sha
        assert _gc_records(caplog, level=logging.INFO) == []
