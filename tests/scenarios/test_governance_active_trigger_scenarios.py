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

from events import EventType
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
from tests.sandbox_scenarios.scenarios import (
    s71_epic_monitor_stale_alert as s71,
)
from tests.sandbox_scenarios.scenarios import (
    s72_health_monitor_adjusts_attempts as s72,
)
from tests.sandbox_scenarios.scenarios import (
    s75_worker_stall_escalation as s75,
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


@pytest.mark.asyncio
async def test_s71_epic_monitor_flags_seeded_stale_epic(mock_world) -> None:
    _seed, stats = await _run(mock_world, s71)

    assert stats["epic_monitor"]["stale_count"] >= 1
    # The world shows the side effects, not just the counter: the stale
    # warning landed on the epic issue and the alert reached the bus.
    warning_comments = [
        body
        for number, body in mock_world._github._comments
        if number == s71._EPIC and "Stale epic warning" in body
    ]
    assert warning_comments, "expected the stale-warning comment on the epic"
    alerts = [
        e
        for e in mock_world._harness.bus.get_history()
        if e.type == EventType.SYSTEM_ALERT and e.data.get("source") == "epic_monitor"
    ]
    assert any(a.data.get("epic_number") == s71._EPIC for a in alerts)


@pytest.mark.asyncio
async def test_s72_health_monitor_adjusts_on_seeded_low_first_pass(
    mock_world,
) -> None:
    _seed, stats = await _run(mock_world, s72)

    assert stats["health_monitor"]["first_pass_rate"] < 0.2
    assert stats["health_monitor"]["total_outcomes"] == 10
    assert stats["health_monitor"]["adjustments_made"] >= 1
    # Both flat-memory_dir artifacts were read from the seeded files.
    assert stats["health_monitor"]["avg_memory_score"] == 0.8
    # The auto-adjust decision reached the hash-chained trail on disk.
    decisions = mock_world._harness.config.memory_dir / "decisions.jsonl"
    assert decisions.exists()
    assert "max_quality_fix_attempts" in decisions.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_s75_health_monitor_escalates_stalled_registered_worker(
    mock_world,
) -> None:
    """#10086 — a seeded registered worker + a stale heartbeat together
    reach the generic dead-man-switch escalation, not just a heartbeat read.

    Before ``registered_workers``, a seeded ``worker_heartbeats`` entry alone
    could never traverse ``_check_worker_staleness``'s ``name not in
    registered`` filter (no ``BGWorkerManager`` reaches
    ``HealthMonitorLoop`` from a seed at all) — the restart/escalate branch
    was unreachable end-to-end. (``run_with_loops`` builds a throwaway
    per-call ``EventBus`` for loop deps — see its docstring — so the
    ``worker_stall`` ``SYSTEM_ALERT`` this scenario also publishes isn't
    observable here; the sandbox Tier-2 run asserts that side via
    ``/api/events``, where ``sandbox_main`` shares one real bus everywhere.)
    """
    _seed, _stats = await _run(mock_world, s75)

    # The world shows the side effect, not just the loop's own stats: a
    # loop-stalled issue was actually filed for the seeded stalled worker.
    filed = await mock_world.github.list_issues_by_label("loop-stalled")
    assert filed, "expected a loop-stalled issue for the seeded stalled worker"
    stall_issues = [i for i in filed if s75._STALLED_WORKER in i["title"]]
    assert stall_issues, (
        f"expected a loop-stalled issue mentioning {s75._STALLED_WORKER!r}; "
        f"filed: {filed!r}"
    )
    issue = mock_world._github._issues[stall_issues[0]["number"]]
    assert "Auto-restart attempted: `False`" in issue.body
