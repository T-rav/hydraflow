"""MockWorld scenario — WorkspaceGCLoop all-root worktree coverage (#10698).

Proves the enumerate-and-reap phase reaps a CLOSED-issue ``fix/*`` worktree on
a NON-standard root (not the factory ``issue-<N>`` path), while fail-closed
KEEPING same-root worktrees that are dirty or carry unlanded work regardless
of issue state. The reaped branch models a squash merge after ``staging`` has
advanced: local ancestry and content checks both differ, so only FakeGitHub's
exact branch + historical HEAD match can authorize the reap (#11502/#11503).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
_CLOSED_UNLANDED = 10804  # closed but exact HEAD never merged → KEPT


class TestWorkspaceGCAllRootsScenario:
    async def test_reaps_closed_fix_worktree_keeps_dirty_and_unmerged(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)

        # Seed GitHub truth, including the exact historical squash-merge HEAD.
        IssueBuilder().numbered(_CLOSED).at(world)
        IssueBuilder().numbered(_DIRTY).at(world)
        IssueBuilder().numbered(_OPEN).at(world)
        IssueBuilder().numbered(_CLOSED_UNLANDED).at(world)
        world.github.issue(_CLOSED).state = "closed"
        world.github.issue(_DIRTY).state = "closed"
        world.github.issue(_OPEN).state = "open"
        world.github.issue(_CLOSED_UNLANDED).state = "closed"
        merged_branch = f"fix/broaden-gc-{_CLOSED}"
        world.github.add_pr(
            number=901,
            issue_number=_CLOSED,
            branch=merged_branch,
            head_sha="b" * 40,
            base_branch="staging",
            merged=True,
        )

        # A non-standard root (sub-agent style) holding four worktrees.
        root = tmp_path / "sub-agent-worktrees"
        wt_reap = root / "agent-reap"
        wt_dirty = root / "agent-dirty"
        wt_open = root / "agent-open"
        wt_closed_unlanded = root / "agent-closed-unlanded"
        for wt in (wt_reap, wt_dirty, wt_open, wt_closed_unlanded):
            wt.mkdir(parents=True)
            (wt / ".git").write_text("gitdir: simulated\n")

        deps = make_bg_loop_deps(
            tmp_path,
            staging_enabled=True,
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
            f"worktree {repo_root}\nHEAD {'a' * 40}\nbranch refs/heads/staging\n\n"
            f"worktree {wt_reap.resolve()}\nHEAD {'b' * 40}\n"
            f"branch refs/heads/{merged_branch}\n\n"
            f"worktree {wt_dirty.resolve()}\nHEAD {'c' * 40}\n"
            f"branch refs/heads/feat/wip-{_DIRTY}\n\n"
            f"worktree {wt_open.resolve()}\nHEAD {'d' * 40}\n"
            f"branch refs/heads/fix/inflight-{_OPEN}\n\n"
            f"worktree {wt_closed_unlanded.resolve()}\nHEAD {'e' * 40}\n"
            f"branch refs/heads/fix/unlanded-{_CLOSED_UNLANDED}\n"
        )
        identity_map = {
            str(wt_reap.resolve()): ("b" * 40, merged_branch),
            str(wt_dirty.resolve()): ("c" * 40, f"feat/wip-{_DIRTY}"),
            str(wt_open.resolve()): ("d" * 40, f"fix/inflight-{_OPEN}"),
            str(wt_closed_unlanded.resolve()): (
                "e" * 40,
                f"fix/unlanded-{_CLOSED_UNLANDED}",
            ),
        }
        dirty_map = {str(wt_dirty.resolve()): " M code.py\n"}
        revlist_map = {
            str(wt_reap.resolve()): "3",
            str(wt_open.resolve()): "3",
            str(wt_closed_unlanded.resolve()): "2",
        }
        removed: list[str] = []
        deleted_branches: list[str] = []

        async def fake_run(  # noqa: PLR0911 - command-aware local-git seam
            *cmd: str, cwd: object = None, **_kw: object
        ) -> str:
            head3 = cmd[:3]
            if head3 == ("git", "worktree", "list"):
                return porcelain
            if head3 == ("git", "branch", "--list"):
                return ""  # Phase 3: no local branches to reap
            if head3 == ("git", "rev-parse", "--show-toplevel"):
                return str(Path(str(cwd)).resolve())
            if head3 == ("git", "status", "--porcelain"):
                return dirty_map.get(str(cwd), "")
            if head3 == ("git", "status", "--porcelain=v2"):
                head_sha, branch = identity_map[str(cwd)]
                return (
                    f"# branch.oid {head_sha}\n"
                    f"# branch.head {branch}\n"
                    f"{dirty_map.get(str(cwd), '')}"
                )
            if cmd[:2] == ("git", "rev-list"):
                return revlist_map.get(str(cwd), "0")
            if cmd[:2] == ("git", "diff"):
                return "staging-advanced.py\n"
            if head3 == ("git", "worktree", "remove"):
                removed.append(cmd[-1])
            elif head3 == ("git", "branch", "-D"):
                deleted_branches.append(cmd[-1])
            return ""

        with patch("workspace_gc_loop.run_subprocess", side_effect=fake_run):
            result = await loop._do_work()

        # REAP: the closed-issue fix/* worktree on the non-standard root.
        assert removed == [str(wt_reap.resolve())], (
            "closed-issue fix/* worktree on a non-standard root must be reaped"
        )
        assert deleted_branches == [merged_branch]
        # KEEP: dirty, open-unlanded, closed-unlanded, and primary worktrees.
        assert str(wt_dirty.resolve()) not in removed
        assert str(wt_open.resolve()) not in removed
        assert str(wt_closed_unlanded.resolve()) not in removed
        assert str(repo_root) not in removed
        assert result is not None
        assert result["collected"] == 1
