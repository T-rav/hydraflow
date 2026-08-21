"""MockWorld scenario for the shared WorkspaceGC landed guard (#11502/#11507)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_workspace import FakeWorkspace
from state import StateTracker
from tests.helpers import make_bg_loop_deps
from workspace_gc_loop import WorkspaceGCLoop

pytestmark = pytest.mark.scenario_loops

_TRACKED_MERGED = 115021
_TRACKED_UNLANDED = 115022
_ORPHAN_MERGED = 115071
_ORPHAN_UNLANDED = 115072


class TestWorkspaceGCLandedGuardScenario:
    async def test_one_cycle_gates_tracked_and_orphan_destroys_on_exact_head(
        self, tmp_path: Path
    ) -> None:
        deps = make_bg_loop_deps(
            tmp_path,
            worktree_gc_all_roots_enabled=False,
        )
        state = StateTracker(deps.config.state_file)
        github = FakeGitHub()
        workspaces = FakeWorkspace(tmp_path / "fake-workspaces")

        issue_branches = {
            _TRACKED_MERGED: "agent/issue-115021",
            _TRACKED_UNLANDED: "agent/issue-115022",
            _ORPHAN_MERGED: "agent/issue-115071",
            _ORPHAN_UNLANDED: "agent/issue-115072",
        }
        head_by_issue = {
            _TRACKED_MERGED: "a" * 40,
            _TRACKED_UNLANDED: "b" * 40,
            _ORPHAN_MERGED: "c" * 40,
            _ORPHAN_UNLANDED: "d" * 40,
        }
        for issue_number, branch in issue_branches.items():
            github.add_issue(issue_number, f"Issue {issue_number}", "", state="closed")
            path = deps.config.workspace_path_for_issue(issue_number)
            path.mkdir(parents=True)
            (path / ".git").write_text("gitdir: simulated\n")
            if issue_number in {_TRACKED_MERGED, _TRACKED_UNLANDED}:
                state.set_workspace(issue_number, str(path))
                state.set_branch(issue_number, branch)

        for issue_number in (_TRACKED_MERGED, _ORPHAN_MERGED):
            github.add_pr(
                number=issue_number,
                issue_number=issue_number,
                branch=issue_branches[issue_number],
                head_sha=head_by_issue[issue_number],
                merged=True,
            )

        loop = WorkspaceGCLoop(
            config=deps.config,
            workspaces=workspaces,
            prs=github,
            state=state,
            deps=deps.loop_deps,
            is_in_pipeline_cb=lambda _issue: False,
        )
        identities = {
            str(deps.config.workspace_path_for_issue(issue).resolve()): (
                head_by_issue[issue],
                branch,
            )
            for issue, branch in issue_branches.items()
        }

        async def fake_git(*cmd: str, cwd: object = None, **_kw: object) -> str:
            if cmd[:3] == ("git", "branch", "--list"):
                return ""
            if cmd[:3] == ("git", "rev-parse", "--show-toplevel"):
                return str(Path(str(cwd)).resolve())
            if cmd[:3] == ("git", "status", "--porcelain=v2"):
                head_sha, branch = identities[str(Path(str(cwd)).resolve())]
                return f"# branch.oid {head_sha}\n# branch.head {branch}\n"
            if cmd[:2] == ("git", "rev-list"):
                return "2"
            if cmd[:2] == ("git", "diff"):
                return "staging-advanced.py\n"
            return ""

        with patch("workspace_gc_loop.run_subprocess", side_effect=fake_git):
            result = await loop._do_work()

        assert (
            result,
            workspaces.destroyed,
            set(state.get_active_workspaces()),
        ) == (
            {"collected": 2, "skipped": 1, "errors": 0},
            [_TRACKED_MERGED, _ORPHAN_MERGED],
            {_TRACKED_UNLANDED},
        )

    async def test_one_cycle_prunes_gone_entry_and_gates_branch_deletes_on_tip_proof(
        self, tmp_path: Path
    ) -> None:
        """#11570 + #11571 in one cycle.

        Phase 1 prunes (state only) the tracked entry whose directory is gone
        and keeps the present-but-unlanded one; phase 3 deletes only the
        branches whose tip is ancestral or an exact-HEAD merged PR through
        FakeGitHub, keeps the gone entry's unpushed branch, and leaves a
        checked-out branch to the worktree sweep; phase 4 drops the gone
        entry's branch-state entry. Nothing is destroyed.
        """
        gone, ancestral, merged, checked_out = 115701, 115711, 115712, 115713
        deps = make_bg_loop_deps(tmp_path, worktree_gc_all_roots_enabled=False)
        state = StateTracker(deps.config.state_file)
        github = FakeGitHub()
        workspaces = FakeWorkspace(tmp_path / "fake-workspaces")

        gone_path = deps.config.workspace_path_for_issue(gone)
        unlanded_path = deps.config.workspace_path_for_issue(_TRACKED_UNLANDED)
        unlanded_path.mkdir(parents=True)  # also materializes the workspace root
        (unlanded_path / ".git").write_text("gitdir: simulated\n")
        for issue_number, path in (
            (gone, gone_path),
            (_TRACKED_UNLANDED, unlanded_path),
        ):
            state.set_workspace(issue_number, str(path))
            state.set_branch(issue_number, f"agent/issue-{issue_number}")
        for issue_number in (gone, _TRACKED_UNLANDED, ancestral, merged, checked_out):
            github.add_issue(issue_number, f"Issue {issue_number}", "", state="closed")
        tips = {
            f"agent/issue-{gone}": "c" * 40,  # unpushed: unique, real diff, no PR
            f"agent/issue-{ancestral}": "d" * 40,
            f"agent/issue-{merged}": "e" * 40,
        }
        unique_commits = {"c" * 40: "1", "d" * 40: "0", "e" * 40: "2"}
        github.add_pr(
            number=merged,
            issue_number=merged,
            branch=f"agent/issue-{merged}",
            head_sha=tips[f"agent/issue-{merged}"],
            merged=True,
        )
        listing = (
            f"+ agent/issue-{checked_out}\n"
            f"  agent/issue-{gone}\n"
            f"  agent/issue-{ancestral}\n"
            f"  agent/issue-{merged}\n"
        )
        deleted: list[str] = []

        async def fake_git(*cmd: str, cwd: object = None, **_kw: object) -> str:
            response = ""
            if cmd[:3] == ("git", "branch", "--list"):
                response = listing
            elif cmd[:3] == ("git", "branch", "-D"):
                deleted.append(cmd[3])
            elif cmd[:3] == ("git", "rev-parse", "--verify"):
                ref = cmd[3].removeprefix("refs/heads/").removesuffix("^{commit}")
                response = tips[ref]
            elif cmd[:3] == ("git", "rev-parse", "--show-toplevel"):
                response = str(Path(str(cwd)).resolve())
            elif cmd[:3] == ("git", "status", "--porcelain=v2"):
                response = (
                    f"# branch.oid {'b' * 40}\n"
                    f"# branch.head agent/issue-{_TRACKED_UNLANDED}\n"
                )
            elif cmd[:2] == ("git", "rev-list"):
                response = unique_commits.get(cmd[3].split("..")[1], "2")
            elif cmd[:2] == ("git", "diff"):
                response = "staging-advanced.py\n"
            return response

        loop = WorkspaceGCLoop(
            config=deps.config,
            workspaces=workspaces,
            prs=github,
            state=state,
            deps=deps.loop_deps,
            is_in_pipeline_cb=lambda _issue: False,
        )

        with patch("workspace_gc_loop.run_subprocess", side_effect=fake_git):
            result = await loop._do_work()

        # collected = phase-1 prune + two landed branches + phase-4 entry prune
        assert (result, workspaces.destroyed, deleted) == (
            {"collected": 4, "skipped": 1, "errors": 0},
            [],
            [f"agent/issue-{ancestral}", f"agent/issue-{merged}"],
        )
        assert (set(state.get_active_workspaces()), state.get_branch(gone)) == (
            {_TRACKED_UNLANDED},
            None,
        )
