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
from tests.sandbox_scenarios.scenarios import (
    s77_stale_issue_gc_skips_fresh_issue as s77,
)
from tests.sandbox_scenarios.scenarios import (
    s78_trust_fleet_sanity_tick_error_ratio_breach as s78,
)
from tests.sandbox_scenarios.scenarios import (
    s79_wiki_rot_detector_broken_cite_fires as s79,
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


@pytest.mark.asyncio
async def test_s77_stale_issue_gc_closes_stale_skips_fresh(mock_world) -> None:
    """#9544 — a seeded per-issue ``updated_at`` lets stale_issue_gc genuinely
    discriminate: close the far-past-threshold HITL issue, skip the fresh one.

    Before the seeded ``updated_at`` seam, every ``FakeIssue`` shared the same
    hard-coded ``2026-01-01T00:00:00Z`` default, so the "fresh issue is
    skipped" branch of ``StaleIssueGCLoop._do_work`` was unreachable from a
    scenario seed.
    """
    _seed, stats = await _run(mock_world, s77)

    assert stats["stale_issue_gc"]["closed"] >= 1
    assert stats["stale_issue_gc"]["skipped"] >= 1
    # The world shows the side effects, not just the counters.
    stale_issue = mock_world._github._issues[s77._STALE_ISSUE]
    fresh_issue = mock_world._github._issues[s77._FRESH_ISSUE]
    assert stale_issue.state == "closed"
    assert fresh_issue.state == "open"


@pytest.mark.asyncio
async def test_s78_trust_fleet_sanity_files_tick_error_ratio_escalation(
    mock_world,
) -> None:
    """#10133 — seeded ~24h worker-status HISTORY drives a genuine breach,
    not just an idle heartbeat poll (the read-side counterpart of the
    #9643/#10086 heartbeat/registered-worker materializers).

    Before ``worker_status_history``, ``TrustFleetSanityLoop._collect_
    window_metrics`` could never see anything a scenario seeded — its read
    goes through ``EventBus.load_events_since`` (a disk-backed read), and
    the harness's default unseeded ``event_bus`` port is a bare
    ``MagicMock`` whose ``load_events_since`` isn't awaitable, so every
    breach detector silently saw zero ticks regardless of the seed.
    """
    _seed, stats = await _run(mock_world, s78)

    assert stats["trust_fleet_sanity"]["status"] == "ok", stats
    assert stats["trust_fleet_sanity"].get("filed", 0) >= 1, stats

    titles = [issue.title for issue in mock_world._github._issues.values()]
    assert any(s78._WORKER in t and "tick_error_ratio" in t for t in titles), (
        f"expected a tick_error_ratio escalation for {s78._WORKER!r}; "
        f"titles: {titles!r}"
    )
    issue = next(
        i
        for i in mock_world._github._issues.values()
        if s78._WORKER in i.title and "tick_error_ratio" in i.title
    )
    assert "hitl-escalation" in issue.labels
    assert "trust-loop-anomaly" in issue.labels


@pytest.mark.asyncio
async def test_s79_wiki_rot_detector_files_broken_cite_finding(mock_world) -> None:
    """#10133 PIECE 2 — a seeded repo-wiki fixture (structured ``WikiEntry``
    shape, issue #9936) with a broken code-symbol cite drives
    ``WikiRotDetectorLoop``'s genuine per-cite finding, not just an idle
    scan.

    Before ``repo_wiki_fixtures``, ``MockWorldSeed`` had no way to express a
    repo-wiki entry at all — every wiki_rot_detector coverage had to
    hand-mock the ``wiki_store`` port directly (see
    ``tests/scenarios/test_wiki_rot_detector_scenario.py``), leaving the
    seed-driven active-trigger path (both loaders) unproven end-to-end.

    Unlike the sandbox tier (``config.repo`` is EMPTY there — see
    ``MockWorldSeed.repo_wiki_fixtures``), this harness's default
    ``config.repo`` (``"test-org/test-repo"``) is non-empty, so
    ``WikiRotDetectorLoop`` ALSO scans the self-repo slug — and, because the
    self-repo's ``RepoWikiStore.repo_dir`` is the flat ``wiki_root`` itself,
    its ``rglob`` picks up the seeded fixture's nested managed-repo file too,
    additionally firing the self-only shipped-claim pass
    (``fixed_in_pr``/``code_refs``, issue #9598) for the SAME entry. Both
    passes are genuine — assert on the per-cite finding specifically (it
    fires in every environment, including the sandbox) rather than assuming
    a fixed issue count or list order.
    """
    _seed, stats = await _run(mock_world, s79)

    assert stats["wiki_rot_detector"]["status"] == "fired", stats
    assert stats["wiki_rot_detector"]["issues_filed"] >= 1, stats

    issues = await mock_world.github.list_issues_by_label("wiki-rot")
    assert issues, "expected a wiki-rot finding for the seeded broken cite"
    cite_findings = [
        i
        for i in issues
        if s79._BROKEN_CITE in mock_world.github.issue(i["number"]).title
    ]
    assert cite_findings, (
        f"expected a finding naming the broken cite {s79._BROKEN_CITE!r}; "
        f"filed: {issues!r}"
    )
    for i in issues:
        issue = mock_world.github.issue(i["number"])
        assert "hydraflow-find" in issue.labels
        assert "wiki-rot" in issue.labels
