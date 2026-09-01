"""MockWorld scenario — a dead registration reaches the loop's own result (#11908).

Unit tests prove `WorkspaceManager.prune_dead_registrations` clears a locked
phantom against real git. They cannot show that the count survives the trip out
of the adapter, through the loop's Phase 6, and into the dict an operator
reads — which is precisely where #11890's `patterns_filed: 0` lived for the
life of that loop.

So this drives the real `WorkspaceGCLoop` over a `FakeWorkspace` that reports
one dead registration, and asserts the number arrives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mockworld.fakes.fake_workspace import FakeWorkspace
from state import StateTracker
from tests.helpers import make_bg_loop_deps
from workspace_gc_loop import WorkspaceGCLoop

pytestmark = pytest.mark.scenario_loops


def _loop(tmp_path: Path, workspaces: FakeWorkspace) -> WorkspaceGCLoop:
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    deps = make_bg_loop_deps(tmp_path, enabled=True, workspace_gc_interval=600)
    from unittest.mock import AsyncMock, MagicMock

    prs = MagicMock()
    prs.get_branch_pr_state = AsyncMock(return_value=None)
    return WorkspaceGCLoop(
        config=deps.config,
        workspaces=workspaces,
        prs=prs,
        state=StateTracker(deps.config.state_file),
        deps=deps.loop_deps,
        is_in_pipeline_cb=lambda _n: False,
    )


class TestDeadRegistrationsReachTheLoopResult:
    async def test_the_count_is_reported_not_swallowed(self, tmp_path: Path) -> None:
        workspaces = FakeWorkspace(tmp_path / "wt")
        workspaces.set_dead_registrations([Path("/gone/phantom")])

        result = await _loop(tmp_path, workspaces)._do_work()

        assert result["pruned_registrations"] == 1, (
            "the adapter pruned a dead registration and the loop reported "
            f"nothing — the #11890 shape. Result: {result}"
        )

    async def test_a_quiet_cycle_reports_zero_rather_than_omitting_the_key(
        self, tmp_path: Path
    ) -> None:
        """A key that appears only when non-zero cannot be read as a series."""
        result = await _loop(tmp_path, FakeWorkspace(tmp_path / "wt"))._do_work()

        assert result["pruned_registrations"] == 0
