"""MockWorld scenario — WorkspaceGCLoop all-root worktree coverage (#10698).

Proves the enumerate-and-reap phase reaps a CLOSED-issue ``fix/*`` worktree on
a NON-standard root (not the factory ``issue-<N>`` path), while fail-closed
KEEPING same-root worktrees that are dirty, belong to an open issue with
unmerged commits, or belong to a CLOSED issue whose commits never landed on
the integration branch (#11503 — a closed issue is not proof of a merge).
GitHub state is served by the real ``FakeGitHub`` PRPort so the safe-to-gc
policy runs unchanged; local git is simulated via command-aware
``run_subprocess``/``run_subprocess_result`` fakes that record reap
operations.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from execution import SimpleResult
from state import StateTracker
from tests.helpers import make_bg_loop_deps
from tests.scenarios.builders import IssueBuilder
from tests.scenarios.fakes.mock_world import MockWorld
from workspace_gc_loop import WorkspaceGCLoop

pytestmark = pytest.mark.scenario_loops

# Issue numbers seeded into FakeGitHub for this scenario.
_CLOSED = 10801  # closed + clean fix/* worktree → REAPED
_DIRTY = 10802  # closed but uncommitted changes → KEPT (dirty guard)
_OPEN = 10803  # open + unmerged unique commits → KEPT (unmerged guard)
_CLOSED_UNLANDED = 10804  # closed but unlanded unique commits → KEPT (#11503)


class TestWorkspaceGCAllRootsScenario:
    async def test_reaps_closed_fix_worktree_keeps_dirty_and_unmerged(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)

        # Seed GitHub truth: one closed, one closed, one open (no PR/labels).
        IssueBuilder().numbered(_CLOSED).at(world)
        IssueBuilder().numbered(_DIRTY).at(world)
        IssueBuilder().numbered(_OPEN).at(world)
        IssueBuilder().numbered(_CLOSED_UNLANDED).at(world)
        world.github.issue(_CLOSED).state = "closed"
        world.github.issue(_DIRTY).state = "closed"
        world.github.issue(_OPEN).state = "open"
        world.github.issue(_CLOSED_UNLANDED).state = "closed"

        # A non-standard root (sub-agent style) holding four worktrees.
        root = tmp_path / "sub-agent-worktrees"
        wt_reap = root / "agent-reap"
        wt_dirty = root / "agent-dirty"
        wt_open = root / "agent-open"
        wt_unlanded = root / "agent-unlanded"
        for wt in (wt_reap, wt_dirty, wt_open, wt_unlanded):
            wt.mkdir(parents=True)

        deps = make_bg_loop_deps(
            tmp_path,
            worktree_gc_roots=[str(root)],
            worktree_gc_min_age_seconds=0,
        )
        loop = WorkspaceGCLoop(
            config=deps.config,
            workspaces=MagicMock(),
            prs=world.github,
            state=StateTracker(deps.config.state_file),
            deps=deps.loop_deps,
            is_in_pipeline_cb=lambda _n: False,
        )

        repo_root = deps.config.repo_root.expanduser().resolve()
        porcelain = (
            f"worktree {repo_root}\nHEAD aaa\nbranch refs/heads/staging\n\n"
            f"worktree {wt_reap.resolve()}\nHEAD bbb\n"
            f"branch refs/heads/fix/broaden-gc-{_CLOSED}\n\n"
            f"worktree {wt_dirty.resolve()}\nHEAD ccc\n"
            f"branch refs/heads/feat/wip-{_DIRTY}\n\n"
            f"worktree {wt_open.resolve()}\nHEAD ddd\n"
            f"branch refs/heads/fix/inflight-{_OPEN}\n\n"
            f"worktree {wt_unlanded.resolve()}\nHEAD eee\n"
            f"branch refs/heads/fix/unlanded-{_CLOSED_UNLANDED}\n"
        )
        # Per-worktree local-git state, keyed by cwd.
        dirty_map = {str(wt_dirty.resolve()): " M code.py\n"}
        revlist_map = {
            str(wt_open.resolve()): "3",  # open issue has unmerged work
            str(wt_unlanded.resolve()): "2",  # closed issue, unpushed commits
        }
        # Only the closed-unlanded worktree has content that still diverges
        # from origin/<base> — everything else either has zero unique commits
        # (diff never consulted, short-circuited) or is reaped outright.
        diff_rc_map = {str(wt_unlanded.resolve()): 1}
        removed: list[str] = []
        deleted_branches: list[str] = []

        async def fake_run(*cmd: str, cwd: object = None, **_kw: object) -> str:
            head3 = cmd[:3]
            if head3 == ("git", "worktree", "list"):
                return porcelain
            if head3 == ("git", "branch", "--list"):
                return ""  # Phase 3: no local branches to reap
            if head3 == ("git", "status", "--porcelain"):
                return dirty_map.get(str(cwd), "")
            if cmd[:2] == ("git", "rev-list"):
                return revlist_map.get(str(cwd), "0")
            if head3 == ("git", "worktree", "remove"):
                removed.append(cmd[-1])
            elif head3 == ("git", "branch", "-D"):
                deleted_branches.append(cmd[-1])
            return ""

        async def fake_run_result(
            *cmd: str, cwd: object = None, **_kw: object
        ) -> SimpleResult:
            if cmd[:2] == ("git", "diff"):
                return SimpleResult(returncode=diff_rc_map.get(str(cwd), 0))
            return SimpleResult()

        with (
            patch("workspace_gc_loop.run_subprocess", side_effect=fake_run),
            patch(
                "workspace_gc_loop.run_subprocess_result", side_effect=fake_run_result
            ),
        ):
            result = await loop._do_work()

        # REAP: the closed-issue fix/* worktree on the non-standard root.
        assert removed == [str(wt_reap.resolve())], (
            "closed-issue fix/* worktree on a non-standard root must be reaped"
        )
        assert deleted_branches == [f"fix/broaden-gc-{_CLOSED}"]
        # KEEP: dirty worktree, open-issue-with-unmerged-commits worktree,
        # closed-issue-with-unlanded-commits worktree (#11503), and the
        # primary worktree are never touched.
        assert str(wt_dirty.resolve()) not in removed
        assert str(wt_open.resolve()) not in removed
        assert str(wt_unlanded.resolve()) not in removed
        assert str(repo_root) not in removed
        assert result is not None
        assert result["collected"] == 1
