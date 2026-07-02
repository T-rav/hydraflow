"""Tests for ConvergenceOscillationLoop (Phase 2d caretaker).

Coverage:
* (a) Oscillating, not-yet-escalated ledger → _do_work escalates:
      create_issue called once, oscillation_escalated flag set, escalated==1.
* (b) Already-escalated ledger (oscillation_escalated=True) → skipped.
* (c) Converged ledger → skipped.
* (d) Non-oscillating ledger → skipped (no create_issue).
* (e) Kill-switch off (enabled_cb=False) → {"status": "disabled"}, no create_issue.
* (f) Config gate off (convergence_oscillation_loop_enabled=False) → {"status": "config_disabled"}.
* (g) dry_run=True → None returned, no create_issue.
* (h) Dedup: two consecutive _do_work() cycles → same issue escalated only ONCE.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from convergence_oscillation_loop import ConvergenceOscillationLoop
from helpers import make_bg_loop_deps
from state import StateTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pr_manager() -> MagicMock:
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=9999)
    return pr


def _make_loop(
    tmp_path: Path,
    state: StateTracker,
    pr: MagicMock,
    *,
    enabled: bool = True,
    convergence_oscillation_loop_enabled: bool = True,
    dry_run: bool = False,
) -> ConvergenceOscillationLoop:
    bg = make_bg_loop_deps(
        tmp_path,
        enabled=enabled,
        dry_run=dry_run,
        state_file=tmp_path / "state.json",
    )
    # Override config flags that ConfigFactory doesn't expose as kwargs yet;
    # mirrors the pattern in test_triage_retry_loop (object.__setattr__ on
    # the frozen/validated Pydantic model).
    if not convergence_oscillation_loop_enabled:
        object.__setattr__(bg.config, "convergence_oscillation_loop_enabled", False)
    return ConvergenceOscillationLoop(
        config=bg.config,
        state=state,
        pr_manager=pr,
        deps=bg.loop_deps,
    )


def _seed_oscillating_ledger(state: StateTracker, issue_number: int) -> None:
    """Seed a ledger where triage + plan are LOOP_BACK (triggers snapshot oscillation)."""
    ledger = state.ensure_convergence_ledger(issue_number)
    ledger.record_gate_result("triage", "LOOP_BACK", ["finding-a"])
    ledger.record_gate_result("plan", "LOOP_BACK", ["finding-b"])
    state.save_convergence_ledger(issue_number, ledger)


def _seed_converged_ledger(state: StateTracker, issue_number: int) -> None:
    ledger = state.ensure_convergence_ledger(issue_number)
    ledger.converged = True
    state.save_convergence_ledger(issue_number, ledger)


def _seed_escalated_ledger(state: StateTracker, issue_number: int) -> None:
    _seed_oscillating_ledger(state, issue_number)
    state.mark_oscillation_escalated(issue_number)


def _seed_non_oscillating_ledger(state: StateTracker, issue_number: int) -> None:
    """Seed a ledger with one LOOP_BACK stage (below the min_loopback_stages=2 threshold)."""
    ledger = state.ensure_convergence_ledger(issue_number)
    ledger.record_gate_result("triage", "LOOP_BACK", ["finding-a"])
    ledger.record_gate_result("plan", "ADVANCE", [])
    state.save_convergence_ledger(issue_number, ledger)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oscillating_ledger_escalates(tmp_path: Path) -> None:
    """(a) A not-yet-escalated oscillating ledger is escalated on _do_work."""
    state = StateTracker(tmp_path / "state.json")
    _seed_oscillating_ledger(state, 42)

    pr = _make_pr_manager()
    loop = _make_loop(tmp_path, state, pr)

    result = await loop._do_work()

    assert result == {"status": "ok", "scanned": 1, "escalated": 1}
    assert pr.create_issue.await_count == 1
    # The escalation issue must carry the HITL escalation label + the
    # convergence marker; a wrong-label regression would otherwise pass silently.
    _title, _body, labels = pr.create_issue.call_args.args
    assert loop._config.hitl_escalation_label[0] in labels
    assert "convergence-oscillation" in labels
    # The flag must be persisted in the live state tracker.
    updated = state.get_convergence_ledger(42)
    assert updated is not None
    assert updated.oscillation_escalated is True


@pytest.mark.asyncio
async def test_already_escalated_ledger_skipped(tmp_path: Path) -> None:
    """(b) A ledger with oscillation_escalated=True is skipped."""
    state = StateTracker(tmp_path / "state.json")
    _seed_escalated_ledger(state, 42)

    pr = _make_pr_manager()
    loop = _make_loop(tmp_path, state, pr)

    result = await loop._do_work()

    assert result == {"status": "ok", "scanned": 1, "escalated": 0}
    pr.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_converged_ledger_skipped(tmp_path: Path) -> None:
    """(c) A converged ledger is skipped even if stages would otherwise oscillate."""
    state = StateTracker(tmp_path / "state.json")
    _seed_converged_ledger(state, 7)

    pr = _make_pr_manager()
    loop = _make_loop(tmp_path, state, pr)

    result = await loop._do_work()

    assert result == {"status": "ok", "scanned": 1, "escalated": 0}
    pr.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_non_oscillating_ledger_skipped(tmp_path: Path) -> None:
    """(d) A ledger below the oscillation threshold is skipped."""
    state = StateTracker(tmp_path / "state.json")
    _seed_non_oscillating_ledger(state, 99)

    pr = _make_pr_manager()
    loop = _make_loop(tmp_path, state, pr)

    result = await loop._do_work()

    assert result == {"status": "ok", "scanned": 1, "escalated": 0}
    pr.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_kill_switch_returns_disabled(tmp_path: Path) -> None:
    """(e) ADR-0049 in-body gate: enabled_cb=False → disabled, no create_issue."""
    state = StateTracker(tmp_path / "state.json")
    _seed_oscillating_ledger(state, 42)

    pr = _make_pr_manager()
    loop = _make_loop(tmp_path, state, pr, enabled=False)

    result = await loop._do_work()

    assert result == {"status": "disabled"}
    pr.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_config_gate_returns_config_disabled(tmp_path: Path) -> None:
    """(f) Static config gate → config_disabled, no create_issue."""
    state = StateTracker(tmp_path / "state.json")
    _seed_oscillating_ledger(state, 42)

    pr = _make_pr_manager()
    loop = _make_loop(tmp_path, state, pr, convergence_oscillation_loop_enabled=False)

    result = await loop._do_work()

    assert result == {"status": "config_disabled"}
    pr.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_dry_run_returns_none(tmp_path: Path) -> None:
    """(g) dry_run=True → returns None, no create_issue."""
    state = StateTracker(tmp_path / "state.json")
    _seed_oscillating_ledger(state, 42)

    pr = _make_pr_manager()
    loop = _make_loop(tmp_path, state, pr, dry_run=True)

    result = await loop._do_work()

    assert result is None
    pr.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_dedup_two_cycles_escalate_once(tmp_path: Path) -> None:
    """(h) Two consecutive _do_work() cycles escalate the same issue only ONCE."""
    state = StateTracker(tmp_path / "state.json")
    _seed_oscillating_ledger(state, 42)

    pr = _make_pr_manager()
    loop = _make_loop(tmp_path, state, pr)

    result1 = await loop._do_work()
    result2 = await loop._do_work()

    # First cycle escalates.
    assert result1 == {"status": "ok", "scanned": 1, "escalated": 1}
    # Second cycle scans again but skips the already-escalated issue.
    assert result2 == {"status": "ok", "scanned": 1, "escalated": 0}
    # create_issue must be called exactly once across both cycles.
    assert pr.create_issue.await_count == 1


@pytest.mark.asyncio
async def test_temporal_oscillation_deferred_while_laps_below_cap(
    tmp_path: Path,
) -> None:
    """(i) Temporal arm deferred: laps=2, cap=3 -> NOT escalated.

    The caretaker must not fire temporal oscillation while the review loop still
    owns the retry budget (0 < laps < max_convergence_laps).
    """
    state = StateTracker(tmp_path / "state.json")

    # Seed a ledger that would trigger temporal oscillation (identical lap sigs)
    # but is only at lap 2 of 3 budget.
    ledger = state.ensure_convergence_ledger(55)
    ledger.record_gate_result("review", "LOOP_BACK", ["finding-x"])
    ledger.mark_lap()
    ledger.record_gate_result("review", "LOOP_BACK", ["finding-x"])
    ledger.mark_lap()
    # 2 identical laps -> detect_outer_oscillation would be True...
    assert ledger.detect_outer_oscillation() is True
    # ...but laps=2 < cap=3, so temporal arm should defer.
    state.save_convergence_ledger(55, ledger)

    pr = _make_pr_manager()
    loop = _make_loop(tmp_path, state, pr)
    # Ensure cap=3 on config.
    object.__setattr__(loop._config, "max_convergence_laps", 3)

    result = await loop._do_work()

    # Should NOT escalate because laps < cap.
    assert result == {"status": "ok", "scanned": 1, "escalated": 0}
    pr.create_issue.assert_not_called()


@pytest.mark.asyncio
async def test_temporal_oscillation_fires_at_cap(tmp_path: Path) -> None:
    """(j) Temporal arm fires when laps >= max_convergence_laps."""
    state = StateTracker(tmp_path / "state.json")

    ledger = state.ensure_convergence_ledger(56)
    ledger.record_gate_result("review", "LOOP_BACK", ["finding-y"])
    ledger.mark_lap()
    ledger.record_gate_result("review", "LOOP_BACK", ["finding-y"])
    ledger.mark_lap()
    ledger.record_gate_result("review", "LOOP_BACK", ["finding-y"])
    ledger.mark_lap()
    # 3 identical laps at cap=3 -> should fire.
    assert ledger.detect_outer_oscillation() is True
    state.save_convergence_ledger(56, ledger)

    pr = _make_pr_manager()
    loop = _make_loop(tmp_path, state, pr)
    object.__setattr__(loop._config, "max_convergence_laps", 3)

    result = await loop._do_work()

    assert result == {"status": "ok", "scanned": 1, "escalated": 1}
    pr.create_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_snapshot_arm_unaffected_by_temporal_deferral(tmp_path: Path) -> None:
    """(k) Snapshot arm still fires when 2 boundary stages are LOOP_BACK (laps=0)."""
    state = StateTracker(tmp_path / "state.json")
    # Seed snapshot oscillation: 2 boundary stages LOOP_BACK, no laps yet.
    ledger = state.ensure_convergence_ledger(57)
    ledger.record_gate_result("triage", "LOOP_BACK", ["finding-a"])
    ledger.record_gate_result("plan", "LOOP_BACK", ["finding-b"])
    # laps=0 -> temporal_ok=True (laps==0) -> full detect_cross_boundary_oscillation.
    # The snapshot arm (min 2 boundary LOOP_BACKs) should fire.
    state.save_convergence_ledger(57, ledger)

    pr = _make_pr_manager()
    loop = _make_loop(tmp_path, state, pr)
    object.__setattr__(loop._config, "max_convergence_laps", 3)

    result = await loop._do_work()

    assert result == {"status": "ok", "scanned": 1, "escalated": 1}
    pr.create_issue.assert_awaited_once()
