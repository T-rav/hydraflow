"""Sandbox seam completeness guard (#10012) — the s51/s56/s57 wedge class.

A loop/runner path that spawns a real ``claude`` or a raw subprocess inside
the air-gapped sandbox hangs it: s51 (#9919, DiscoverRunner/ShapeRunner),
s55 (#9925 family), s56 (SkillPromptEvalLoop refine path, seams added by
hand in #10006). Each recurrence was a wedged-sandbox incident discovered
at scenario time.

This guard turns the next one into a red unit test at PR time: it AST-scans
every loop + runner module for spawn-primitive call sites and asserts each
module either declares its air-gap seam in
``mockworld.sandbox_main.SANDBOX_SEAMS`` or sits in the grandfathered
baseline below. The baseline only shrinks (ratchet, mirroring
``tests/test_disturbance_ratchet.py``): a NEW spawn path without a seam
declaration reddens, and covering a grandfathered path requires pruning its
entry in the same change so the baseline stays honest.
"""

from __future__ import annotations

from pathlib import Path

from mockworld.sandbox_main import SANDBOX_SEAMS, SEAM_KINDS
from tests.architecture.sandbox_seam_scan import (
    ratchet_diff,
    scan_spawn_signatures,
    signature_module,
    undeclared_signatures,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Grandfathered spawn paths with no declared sandbox seam yet, keyed
# ``{signature: count}`` (see sandbox_seam_scan.scan_spawn_signatures).
# These predate the guard; under the air-gapped sandbox they fail fast on
# their subprocess timeout tiers rather than air-gapping cleanly. DO NOT ADD
# ENTRIES: a new spawn path must declare a seam in SANDBOX_SEAMS (seed seam,
# sentinel, injected fake, or config-disable) instead. Remove entries as
# seams are added — the ratchet only shrinks.
#
# #9554/#10028: the sites below that used to key off ``create_subprocess_exec``
# migrated onto the shared bounded helper (``subprocess_util.run_subprocess``/
# ``run_subprocess_result``) for circuit-breaker/rate-limit/process-group-registry
# hardening — a DIFFERENT concern than this guard's air-gap seam. They are
# still real, undeclared subprocess spawns from the sandbox's point of view,
# so they stay grandfathered here, just re-keyed to the new primitive name
# (``run_subprocess_result``, or ``run_subprocess`` for the one raising-variant
# call site, ``staging_bisect_loop._run_gh``). ``staging_bisect_loop._run_git``
# is unchanged (excluded from that migration — cooperative kill-switch
# cancellation) and keeps its original ``create_subprocess_exec`` key.
GRANDFATHERED_SPAWN_BASELINE: dict[str, int] = {
    "src/adr_touchpoint_auditor_loop.py::AdrTouchpointAuditorLoop._fetch_pr_changed_files::run_subprocess_result": 1,
    "src/adr_touchpoint_auditor_loop.py::AdrTouchpointAuditorLoop._list_recent_merged_prs::run_subprocess_result": 1,
    "src/fake_coverage_auditor_loop.py::FakeCoverageAuditorLoop._grep_scenario_for_helper::run_subprocess_result": 1,
    "src/fake_coverage_auditor_loop.py::FakeCoverageAuditorLoop._list_open_rollup_titles::run_subprocess_result": 1,
    "src/memory_backlog_loop.py::MemoryBacklogLoop._commit_mirror_updates::run_subprocess_result": 2,
    "src/principles_audit_loop.py::PrinciplesAuditLoop._run_audit::run_subprocess_result": 1,
    "src/principles_audit_loop.py::PrinciplesAuditLoop._run_git::run_subprocess_result": 1,
    "src/rc_budget_loop.py::RCBudgetLoop._fetch_junit_tests::run_subprocess_result": 1,
    "src/repo_wiki_loop.py::RepoWikiLoop._adopt_open_maintenance_pr::run_subprocess": 1,
    "src/repo_wiki_loop.py::RepoWikiLoop._maintenance_batch_forced_by_age::run_subprocess": 1,
    "src/repo_wiki_loop.py::RepoWikiLoop._poll_and_merge_open_pr::run_subprocess": 3,
    "src/staging_bisect_loop.py::StagingBisectLoop._run_bisect_probe::run_subprocess_result": 1,
    "src/staging_bisect_loop.py::StagingBisectLoop._run_gh::run_subprocess": 1,
    # #9577: _run_git swapped its raw create_subprocess_exec for a direct
    # get_default_runner().run_simple(cancel_check=...) — semaphore-free so a
    # 45-min bisect never holds the fleet gh/git gate. Still a tolerated raw
    # host spawn (same grandfathered status as the sibling _run_gh/_run_bisect
    # entries — staging_bisect is not exercised by any sandbox scenario), so
    # the baseline entry is RENAMED to the new token, not grown.
    "src/staging_bisect_loop.py::StagingBisectLoop._run_git::get_default_runner": 1,
    # staging_promotion_loop's raw-gh reads (_list_merged_promotion_prs +
    # _staging_ci_is_green, #10353) are now covered by the module's
    # ``config_disable`` seam in SANDBOX_SEAMS — its baseline entry is pruned
    # per the shrink-only rule (the module is seam-declared, not grandfathered).
    "src/trust_fleet_sanity_loop.py::TrustFleetSanityLoop._find_open_escalation::run_subprocess_result": 1,
    "src/trust_fleet_sanity_loop.py::TrustFleetSanityLoop._reconcile_closed_escalations::run_subprocess_result": 1,
    "src/workspace_gc_loop.py::WorkspaceGCLoop._collect_orphaned_branches::run_subprocess": 2,
    # _get_issue_state's raw ``gh api`` spawn was routed through
    # PRPort.get_issue_state in #9543 — entry pruned per the shrink-only rule.
    # #10698 all-root enumerate-and-reap phase: LOCAL-git worktree operations
    # (`git worktree list/status/rev-list/worktree remove/branch -D`) — the
    # same tolerated local-git class as the sibling _collect_orphaned_branches
    # entry above (no network reach → never wedges the air-gapped sandbox), and
    # additionally pinned OFF in the sandbox via worktree_gc_all_roots_enabled
    # (see mockworld.sandbox_main._apply_sandbox_config_overrides), so no spawn
    # is reachable there. Cannot be a module-level SANDBOX_SEAMS config_disable
    # because Phases 1-4 of the same module still run in the sandbox (s46/s65).
    "src/workspace_gc_loop.py::WorkspaceGCLoop._list_git_worktrees::run_subprocess": 1,
    "src/workspace_gc_loop.py::WorkspaceGCLoop._worktree_is_dirty::run_subprocess": 1,
    "src/workspace_gc_loop.py::WorkspaceGCLoop._worktree_has_unmerged_commits::run_subprocess": 1,
    # #11503: content-based landed check (git diff --quiet), added alongside
    # _worktree_has_unmerged_commits above — same tolerated local-git class
    # (no network reach), same Phase 5 config-disable in the sandbox.
    "src/workspace_gc_loop.py::WorkspaceGCLoop._worktree_work_has_landed::run_subprocess_result": 1,
    "src/workspace_gc_loop.py::WorkspaceGCLoop._reap_worktree::run_subprocess": 2,
}


def test_scan_finds_known_spawn_sites() -> None:
    """Anti-vacuity canary.

    If the scan scope or the primitive set regresses (rename, glob typo),
    every other assertion here would pass vacuously on an empty scan. Pin
    two load-bearing sites that exist as long as HydraFlow shells out to
    ``claude`` at all.
    """
    current = scan_spawn_signatures(REPO_ROOT)
    assert "src/base_runner.py::BaseRunner._execute::stream_claude_process" in current
    assert any(
        signature_module(signature) == "base_subprocess_runner" for signature in current
    )


def test_new_spawn_paths_require_seam_declaration() -> None:
    current = scan_spawn_signatures(REPO_ROOT)
    undeclared = undeclared_signatures(current, SANDBOX_SEAMS)
    new, _resolved = ratchet_diff(undeclared, GRANDFATHERED_SPAWN_BASELINE)
    assert not new, (
        f"Spawn paths with no declared sandbox seam (beyond baseline): {new}. "
        "This is the s51/s56 wedge class — a real claude/subprocess spawn "
        "inside the air-gapped sandbox hangs it. Declare how the path is "
        "air-gapped in mockworld.sandbox_main.SANDBOX_SEAMS (and wire the "
        "seam: seed seam, _mockworld_fake_llm sentinel, injected Fake, or "
        "config-disable in _apply_sandbox_config_overrides). Do NOT grow "
        "GRANDFATHERED_SPAWN_BASELINE — the ratchet only shrinks."
    )


def test_grandfathered_baseline_only_shrinks() -> None:
    current = scan_spawn_signatures(REPO_ROOT)
    undeclared = undeclared_signatures(current, SANDBOX_SEAMS)
    _new, resolved = ratchet_diff(undeclared, GRANDFATHERED_SPAWN_BASELINE)
    assert not resolved, (
        f"Baseline lists spawn paths no longer present or now seam-declared: "
        f"{resolved}. Prune them from GRANDFATHERED_SPAWN_BASELINE in this "
        "change so the baseline stays honest."
    )


def test_declared_seams_map_to_scanned_spawn_modules() -> None:
    """SANDBOX_SEAMS may only name modules the scan actually sees spawning.

    Keeps the registry prunable in both directions: a stale or typo'd key
    (module renamed, spawn removed) fails here instead of silently
    green-lighting an uncovered path under a near-miss name.
    """
    current = scan_spawn_signatures(REPO_ROOT)
    scanned_modules = {signature_module(signature) for signature in current}
    stale = set(SANDBOX_SEAMS) - scanned_modules
    assert not stale, (
        f"SANDBOX_SEAMS declares seams for modules with no scanned spawn "
        f"sites: {sorted(stale)}. Rename or prune the declaration."
    )


def test_declared_seam_kinds_are_valid() -> None:
    invalid = {
        module: kind for module, kind in SANDBOX_SEAMS.items() if kind not in SEAM_KINDS
    }
    assert not invalid, (
        f"SANDBOX_SEAMS entries with unknown seam kind: {invalid}. "
        f"Valid kinds: {sorted(SEAM_KINDS)}."
    )


def test_baseline_entries_are_not_seam_declared() -> None:
    """A module cannot be both grandfathered and seam-declared.

    Adding a SANDBOX_SEAMS entry for a baselined module without pruning the
    baseline would already fail the shrink test; this makes the conflict
    explicit and self-describing.
    """
    conflicted = sorted(
        {
            signature_module(signature)
            for signature in GRANDFATHERED_SPAWN_BASELINE
            if signature_module(signature) in SANDBOX_SEAMS
        }
    )
    assert not conflicted, (
        f"Modules present in both SANDBOX_SEAMS and the grandfathered "
        f"baseline: {conflicted}. Prune their baseline entries."
    )
