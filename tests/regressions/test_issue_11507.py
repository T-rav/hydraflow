"""Regression pin for issue #11507 — GC phases 1-2 destroy unlanded work.

``WorkspaceGCLoop._do_work`` phase 1 (state sweep) and phase 2
(``_collect_orphaned_dirs``) call ``WorkspacePort.destroy`` for any issue where
``_is_safe_to_gc`` returns True. ``_is_safe_to_gc`` returns True for *every*
closed issue once the active/HITL/pipeline/retry-window checks pass — there is
no unmerged-commit or work-has-landed guard on either path
(``src/workspace_gc_loop.py:87-92`` and ``:329-330``). An issue closed as
``NOT_PLANNED`` while unpushed commits sit in its ``issue-<N>`` worktree loses
that work on the next GC cycle.

Phase 5 (``_reap_worktree_if_safe``) already runs ``_worktree_has_unmerged_commits``
for the open-issue case; #11503 closes its closed-issue hole. This pin covers the
same gap on the standard ``issue-<N>`` worktrees that phases 1-2 own.

Tests use a *real* git repo + bare remote + real ``git worktree`` (no mocked
``run_subprocess``), so any landed-or-provably-empty predicate the fix reaches
for — ``rev-list``, ``diff``, ``merge-base`` — is exercised for real.

RED (the defect):
  * ``test_phase1_closed_issue_with_unpushed_commits_not_destroyed``
  * ``test_phase2_orphan_dir_with_unpushed_commits_not_destroyed``
  * ``test_phase2_fails_closed_when_landed_check_errors``

GREEN counter-pins (must stay green — a guard that freezes all collection is
not a fix; the squash-merge case is the *common* path for a closed issue):
  * ``test_phase1_landed_worktree_still_collected``
  * ``test_phase2_squash_merged_worktree_still_collected``
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Repo root on sys.path so ``tests.helpers`` imports (``src`` via PYTHONPATH).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from state import StateTracker  # noqa: E402
from tests.helpers import make_bg_loop_deps  # noqa: E402
from workspace_gc_loop import WorkspaceGCLoop  # noqa: E402

ISSUE = 11507

_GIT_IDENTITY = (
    "-c",
    "user.name=hydraflow-test",
    "-c",
    "user.email=test@example.com",
    "-c",
    "commit.gpgsign=false",
)


def _git(*args: str, cwd: Path) -> str:
    """Run a real git command, failing loudly with stderr on non-zero exit."""
    proc = subprocess.run(
        ["git", *_GIT_IDENTITY, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}"
        )
    return proc.stdout


class _GCEnv:
    """A WorkspaceGCLoop wired to a real repo/remote, with the port mocked."""

    def __init__(self, tmp_path: Path) -> None:
        deps = make_bg_loop_deps(tmp_path)
        self.config = deps.config
        self.base = self.config.base_branch()
        self.repo_root = self.config.repo_root
        self.remote = tmp_path / "remote.git"

        # Bare remote + local clone so ``origin/<base>`` is a real ref.
        self.remote.mkdir(parents=True, exist_ok=True)
        _git("init", "--bare", str(self.remote), cwd=tmp_path)
        _git("clone", str(self.remote), str(self.repo_root), cwd=tmp_path)
        _git("checkout", "-b", self.base, cwd=self.repo_root)
        (self.repo_root / "README.md").write_text("init\n")
        _git("add", "README.md", cwd=self.repo_root)
        _git("commit", "-m", "init", cwd=self.repo_root)
        _git("push", "-u", "origin", self.base, cwd=self.repo_root)

        self.state = StateTracker(self.config.state_file)
        self.workspaces = MagicMock()
        self.workspaces.destroy = AsyncMock()
        self.prs = MagicMock()
        # Closed as not-planned — the exact close reason in the issue report.
        self.prs.get_issue_state = AsyncMock(return_value="NOT_PLANNED")
        self.prs.get_issue_labels = AsyncMock(return_value=[])
        self.prs.find_open_pr_for_branch = AsyncMock(return_value=None)

        self.loop = WorkspaceGCLoop(
            config=self.config,
            workspaces=self.workspaces,
            prs=self.prs,
            state=self.state,
            deps=deps.loop_deps,
            is_in_pipeline_cb=lambda _n: False,
        )

    def make_worktree(self, issue_number: int, *, commits: int = 0) -> Path:
        """Create the standard ``issue-<N>`` worktree, optionally with commits.

        *commits* > 0 leaves work that is NOT on ``origin/<base>`` — exactly the
        state a crashed/abandoned session leaves behind.
        """
        path = self.config.workspace_path_for_issue(issue_number)
        path.parent.mkdir(parents=True, exist_ok=True)
        branch = self.config.branch_for_issue(issue_number)
        _git("worktree", "add", "-b", branch, str(path), self.base, cwd=self.repo_root)
        for index in range(commits):
            (path / f"work-{index}.txt").write_text(f"unpushed work {index}\n")
            _git("add", f"work-{index}.txt", cwd=path)
            _git("commit", "-m", f"wip {index}", cwd=path)
        return path

    def unpushed_commit_count(self, path: Path) -> int:
        out = _git("rev-list", "--count", f"origin/{self.base}..HEAD", cwd=path)
        return int(out.strip())

    def isolate_phase1(self) -> None:
        """Stub phases 2-5 so ``_do_work`` exercises only the state sweep."""
        self.loop._collect_orphaned_dirs = AsyncMock(return_value=0)  # type: ignore[method-assign]
        self.loop._collect_orphaned_branches = AsyncMock(return_value=0)  # type: ignore[method-assign]
        self.loop._prune_stale_branch_entries = AsyncMock(return_value=0)  # type: ignore[method-assign]
        self.loop._collect_orphaned_worktrees = AsyncMock(return_value=0)  # type: ignore[method-assign]


@pytest.fixture
def env(tmp_path: Path) -> _GCEnv:
    return _GCEnv(tmp_path)


class TestPhase1StateSweepGuardsUnlandedWork:
    """Phase 1 (``_do_work`` state sweep) must not destroy unlanded work."""

    @pytest.mark.asyncio
    async def test_phase1_closed_issue_with_unpushed_commits_not_destroyed(
        self, env: _GCEnv
    ) -> None:
        """#11507: a closed issue whose worktree holds unpushed commits is
        destroyed by phase 1 with no landed check — the work is lost."""
        worktree = env.make_worktree(ISSUE, commits=1)
        env.state.set_workspace(ISSUE, str(worktree))
        env.isolate_phase1()

        # Pin the premise: this worktree really does hold work that is not on
        # the integration branch. Without this the assertion below could pass
        # for the wrong reason (e.g. a worktree that was never created).
        assert env.unpushed_commit_count(worktree) == 1

        result = await env.loop._do_work()

        env.workspaces.destroy.assert_not_awaited()
        assert result is not None
        assert result["collected"] == 0
        # The workspace must stay tracked — evicting the state entry while the
        # worktree survives on disk just relaunders it into a phase-2 orphan.
        assert ISSUE in env.state.get_active_workspaces()

    @pytest.mark.asyncio
    async def test_phase1_landed_worktree_still_collected(self, env: _GCEnv) -> None:
        """Liveness counter-pin: a closed issue whose worktree has nothing
        beyond ``origin/<base>`` must still be collected — the guard must not
        freeze GC."""
        worktree = env.make_worktree(ISSUE, commits=0)
        env.state.set_workspace(ISSUE, str(worktree))
        env.isolate_phase1()

        assert env.unpushed_commit_count(worktree) == 0

        result = await env.loop._do_work()

        env.workspaces.destroy.assert_awaited_once_with(ISSUE)
        assert result is not None
        assert result["collected"] == 1


class TestPhase2OrphanDirSweepGuardsUnlandedWork:
    """Phase 2 (``_collect_orphaned_dirs``) must not destroy unlanded work."""

    @pytest.mark.asyncio
    async def test_phase2_orphan_dir_with_unpushed_commits_not_destroyed(
        self, env: _GCEnv
    ) -> None:
        """#11507: an untracked ``issue-<N>`` dir holding unpushed commits is
        destroyed by the orphan-dir scan with no landed check."""
        worktree = env.make_worktree(ISSUE, commits=2)
        assert env.unpushed_commit_count(worktree) == 2
        # Untracked in state — this is what makes it a phase-2 orphan.
        assert ISSUE not in env.state.get_active_workspaces()

        collected = await env.loop._collect_orphaned_dirs({}, 20)

        env.workspaces.destroy.assert_not_awaited()
        assert collected == 0

    @pytest.mark.asyncio
    async def test_phase2_squash_merged_worktree_still_collected(
        self, env: _GCEnv
    ) -> None:
        """Liveness counter-pin: the *common* closed-issue shape — work landed
        via squash merge — must still be collected.

        ``rev-list origin/<base>..HEAD`` counts 1 here even though the content
        is already on the base branch, so a rev-list-only guard would leak
        every merged issue's worktree forever.
        """
        worktree = env.make_worktree(ISSUE, commits=1)
        # Land the same content on the base branch as a separate (squash) commit.
        content = (worktree / "work-0.txt").read_text()
        (env.repo_root / "work-0.txt").write_text(content)
        _git("add", "work-0.txt", cwd=env.repo_root)
        _git("commit", "-m", "squash merge of #11507", cwd=env.repo_root)
        _git("push", "origin", env.base, cwd=env.repo_root)
        _git("fetch", "origin", cwd=worktree)

        # Premise: unique commits exist, but the diff against base is empty.
        assert env.unpushed_commit_count(worktree) == 1
        assert _git("diff", f"origin/{env.base}", "HEAD", cwd=worktree).strip() == "", (
            "squash-landed worktree should have an empty diff against base"
        )

        collected = await env.loop._collect_orphaned_dirs({}, 20)

        env.workspaces.destroy.assert_awaited_once_with(ISSUE)
        assert collected == 1

    @pytest.mark.asyncio
    async def test_phase2_fails_closed_when_landed_check_errors(
        self, env: _GCEnv
    ) -> None:
        """#11507: the landed check must fail closed on any git error.

        Same worktree as the liveness pin above (zero unique commits, therefore
        collectable when the check succeeds) — only the ``origin/<base>`` ref is
        gone, so the comparison cannot be made. An undecidable worktree must be
        skipped, not destroyed.
        """
        worktree = env.make_worktree(ISSUE, commits=0)
        _git("update-ref", "-d", f"refs/remotes/origin/{env.base}", cwd=env.repo_root)

        # Premise: the comparison the guard needs now genuinely errors.
        probe = subprocess.run(
            ["git", "rev-list", "--count", f"origin/{env.base}..HEAD"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            check=False,
        )
        assert probe.returncode != 0, "expected the base-ref comparison to fail"

        collected = await env.loop._collect_orphaned_dirs({}, 20)

        env.workspaces.destroy.assert_not_awaited()
        assert collected == 0
