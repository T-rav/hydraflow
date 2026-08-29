"""MockWorld scenario — the GC's DEFAULT root derivation, not an injected list (#11729).

``test_workspace_gc_all_roots_scenario`` passes ``worktree_gc_roots=[...]``
explicitly, which short-circuits ``HydraFlowConfig.worktree_gc_root_paths()``
entirely — so the derivation that decides where the collector may look was
never exercised at the scenario layer, only in unit tests.

That gap is the #11729 defect in miniature. The collector reached 53 of this
repo's 100 registered worktrees because its default roots did not name the
places ``scripts/hf_worktree.sh`` actually writes to: the checkout, its
parent, and a sibling ``<repo>-worktrees/`` directory. A scenario that injects
the root it wants cannot notice that the defaults are wrong.

So this one injects nothing. It places a worktree in a SIBLING directory of
the checkout — a location the pre-#11729 defaults could not reach — and proves
the loop reaps it through the derivation alone.

Note the loop-level MockWorld ratchet cannot catch this class:
``WorkspaceGCLoop`` already had scenarios, so it counts as covered. Covered at
the loop level is not the same as covered on the path that changed.
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

_CLOSED = 11729  # closed + clean, in a sibling directory -> REAPED via defaults


class TestWorkspaceGCDefaultRootsScenario:
    async def test_a_sibling_worktree_is_reaped_through_the_default_derivation(
        self, tmp_path: Path
    ) -> None:
        world = MockWorld(tmp_path)

        IssueBuilder().numbered(_CLOSED).at(world)
        world.github.issue(_CLOSED).state = "closed"
        merged_branch = f"fix/default-roots-{_CLOSED}"
        world.github.add_pr(
            number=917,
            issue_number=_CLOSED,
            branch=merged_branch,
            head_sha="b" * 40,
            base_branch="staging",
            merged=True,
        )

        # NO worktree_gc_roots override -- the derivation must supply the root.
        deps = make_bg_loop_deps(
            tmp_path,
            staging_enabled=True,
            worktree_gc_min_age_seconds=0,
        )
        repo_root = deps.config.repo_root.expanduser().resolve()

        # A sibling of the checkout, which is where `hf_worktree.sh <name>`
        # used to land before #11729 and where 25 of this repo's orphans sat.
        sibling_root = repo_root.parent / f"{repo_root.name}-worktrees"
        wt_reap = sibling_root / "agent-reap"
        wt_reap.mkdir(parents=True)
        (wt_reap / ".git").write_text("gitdir: simulated\n")

        # Anti-vacuity: this scenario is only meaningful while nothing has
        # injected an explicit root list, and while the sibling is reachable
        # by the DERIVED set. If either stops holding, the test below could
        # pass for a reason that has nothing to do with the derivation.
        assert deps.config.worktree_gc_roots == [], (
            "this scenario must exercise the DEFAULT derivation; an explicit "
            "worktree_gc_roots override would short-circuit the very code "
            "path it exists to cover"
        )
        derived = [
            r.expanduser().resolve() for r in deps.config.worktree_gc_root_paths()
        ]
        assert any(wt_reap.is_relative_to(r) for r in derived), (
            f"the sibling worktree {wt_reap} is not under any derived root "
            f"{derived} — the #11729 regression"
        )

        loop = WorkspaceGCLoop(
            config=deps.config,
            workspaces=MagicMock(),
            prs=world.github,
            state=StateTracker(deps.config.state_file),
            deps=deps.loop_deps,
            is_in_pipeline_cb=lambda _n: False,
        )

        porcelain = (
            f"worktree {repo_root}\nHEAD {'a' * 40}\nbranch refs/heads/staging\n\n"
            f"worktree {wt_reap.resolve()}\nHEAD {'b' * 40}\n"
            f"branch refs/heads/{merged_branch}\n"
        )
        removed: list[str] = []
        deleted_branches: list[str] = []

        async def fake_run(  # noqa: PLR0911 - command-aware local-git seam
            *cmd: str, cwd: object = None, **_kw: object
        ) -> str:
            head3 = cmd[:3]
            if head3 == ("git", "worktree", "list"):
                return porcelain
            if head3 == ("git", "branch", "--list"):
                return ""
            if head3 == ("git", "rev-parse", "--show-toplevel"):
                return str(Path(str(cwd)).resolve())
            if head3 == ("git", "status", "--porcelain"):
                return ""
            if head3 == ("git", "status", "--porcelain=v2"):
                return f"# branch.oid {'b' * 40}\n# branch.head {merged_branch}\n"
            if cmd[:2] == ("git", "rev-list"):
                return "3"
            if cmd[:2] == ("git", "diff"):
                return "staging-advanced.py\n"
            if head3 == ("git", "worktree", "remove"):
                removed.append(cmd[-1])
            elif head3 == ("git", "branch", "-D"):
                deleted_branches.append(cmd[-1])
            return ""

        with patch("workspace_gc_loop.run_subprocess", side_effect=fake_run):
            await loop._do_work()

        assert removed == [str(wt_reap.resolve())], (
            "a closed-issue worktree in a SIBLING directory must be reaped "
            "through the default root derivation; before #11729 the derived "
            "roots did not include the checkout's parent, so it was invisible"
        )
        assert deleted_branches == [merged_branch]
