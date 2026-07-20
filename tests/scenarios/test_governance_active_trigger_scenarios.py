"""#9543 — governance active-trigger scenarios prove their outcome in Tier 1.

``test_sandbox_parity`` only asserts each sandbox scenario produces *some*
loop stats in-process; for the s59–s64 active-trigger family that would pass
even if the seeded trigger never fired (the exact failure mode the family
exists to catch). These tests run each scenario's real seed through the
MockWorld loaders and assert the ACTIVE outcome — the worktree collected, the
issue filed, the epic closed, the artifact purged, the PR rebased — so a
regression in either loader's seam wiring reddens here, without docker.
"""

from __future__ import annotations

import pytest

from tests.sandbox_scenarios.scenarios import (
    s65_workspace_gc_collects_stale as s65,
)
from tests.sandbox_scenarios.scenarios import (
    s66_gate_activator_files_proposal as s66,
)
from tests.sandbox_scenarios.scenarios import (
    s67_branch_protection_auditor_files_drift as s67,
)
from tests.sandbox_scenarios.scenarios import (
    s68_epic_sweeper_closes_completed_epic as s68,
)
from tests.sandbox_scenarios.scenarios import (
    s69_runs_gc_purges_expired_run as s69,
)
from tests.sandbox_scenarios.scenarios import (
    s70_merge_state_watcher_rebases_conflict as s70,
)


async def _run(mock_world, scenario):
    seed = scenario.seed()
    mock_world.apply_seed(seed)
    stats = await mock_world.run_with_loops(seed.loops_enabled, cycles=1)
    return seed, stats


@pytest.mark.asyncio
async def test_s65_workspace_gc_collects_seeded_stale_worktree(mock_world) -> None:
    _seed, stats = await _run(mock_world, s65)

    assert stats["workspace_gc"]["collected"] >= 1
    # The world shows the side effect, not just the counter.
    assert s65._ISSUE in mock_world._workspace.destroyed
    assert s65._ISSUE not in mock_world._harness.state.get_active_workspaces()


@pytest.mark.asyncio
async def test_s66_gate_activator_files_activation_issue(mock_world) -> None:
    _seed, stats = await _run(mock_world, s66)

    assert stats["gate_activator"]["status"] == "proposals"
    filed = stats["gate_activator"]["issue_created"]
    issue = mock_world._github._issues[filed]
    assert issue.title.startswith("[gate-activation]")
    assert s66._GATE in issue.body


@pytest.mark.asyncio
async def test_s67_branch_protection_auditor_files_drift_issue(mock_world) -> None:
    _seed, stats = await _run(mock_world, s67)

    assert stats["branch_protection_auditor"]["status"] == "drift"
    filed = stats["branch_protection_auditor"]["issue_created"]
    issue = mock_world._github._issues[filed]
    assert issue.title.startswith("[branch-protection] ruleset drift")


@pytest.mark.asyncio
async def test_s68_epic_sweeper_closes_completed_epic(mock_world) -> None:
    _seed, stats = await _run(mock_world, s68)

    assert stats["epic_sweeper"]["swept"] >= 1
    epic = mock_world._github._issues[s68._EPIC]
    assert epic.state == "closed"
    assert f"- [x] #{s68._CHILD}" in epic.body


@pytest.mark.asyncio
async def test_s69_runs_gc_purges_expired_run(mock_world) -> None:
    _seed, stats = await _run(mock_world, s69)

    assert stats["runs_gc"]["expired_purged"] >= 1
    runs_dir = mock_world._loop_ports["run_recorder"].runs_dir
    assert not (runs_dir / str(s69._ISSUE)).exists()


@pytest.mark.asyncio
async def test_s70_merge_state_watcher_rebases_conflicting_pr(mock_world) -> None:
    _seed, stats = await _run(mock_world, s70)

    assert stats["merge_state_watcher"]["checked"] >= 1
    assert stats["merge_state_watcher"]["rebased"] >= 1
    assert mock_world._github._prs[s70._PR].mergeable is True
