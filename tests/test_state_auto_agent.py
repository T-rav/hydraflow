"""Tests for AutoAgentStateMixin (spec §3.6)."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_attempts_default_zero(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_auto_agent_attempts(8501) == 0


def test_bump_is_monotonic(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.bump_auto_agent_attempts(8501) == 1
    assert st.bump_auto_agent_attempts(8501) == 2
    assert st.get_auto_agent_attempts(8501) == 2


def test_clear_resets_single_issue(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.bump_auto_agent_attempts(1)
    st.bump_auto_agent_attempts(2)
    st.clear_auto_agent_attempts(1)
    assert st.get_auto_agent_attempts(1) == 0
    assert st.get_auto_agent_attempts(2) == 1


def test_refund_decrements_to_floor_zero(tmp_path: Path) -> None:
    # A credit/session outage refunds the attempt it consumed so the budget
    # isn't burned by a transient (ADR-0084).
    st = _tracker(tmp_path)
    st.bump_auto_agent_attempts(7)
    st.bump_auto_agent_attempts(7)  # 2
    assert st.refund_auto_agent_attempt(7) == 1
    assert st.get_auto_agent_attempts(7) == 1
    assert st.refund_auto_agent_attempt(7) == 0
    # Floor at zero — refunding an already-zero counter is a no-op.
    assert st.refund_auto_agent_attempt(7) == 0
    assert st.get_auto_agent_attempts(7) == 0


def test_daily_spend_default_zero(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_auto_agent_daily_spend("2026-04-25") == 0.0


def test_add_daily_spend_accumulates(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.add_auto_agent_daily_spend("2026-04-25", 1.50) == 1.50
    assert st.add_auto_agent_daily_spend("2026-04-25", 0.75) == 2.25
    assert st.get_auto_agent_daily_spend("2026-04-25") == 2.25
    assert st.get_auto_agent_daily_spend("2026-04-26") == 0.0


def test_state_persists_across_load(tmp_path: Path) -> None:
    st1 = _tracker(tmp_path)
    st1.bump_auto_agent_attempts(8501)
    st1.add_auto_agent_daily_spend("2026-04-25", 5.0)

    st2 = _tracker(tmp_path)
    assert st2.get_auto_agent_attempts(8501) == 1
    assert st2.get_auto_agent_daily_spend("2026-04-25") == 5.0


def test_auto_agent_attempts_stored_in_ledger(tmp_path: Path) -> None:
    """After bump, the counter lives in the convergence ledger, not a bespoke field."""
    st = _tracker(tmp_path)
    st.bump_auto_agent_attempts(7)
    ledger = st.get_convergence_ledger(7)
    assert ledger is not None
    assert ledger.stage_state["auto_agent"].attempts == 1


def test_old_state_json_with_auto_agent_attempts_key_loads_clean(
    tmp_path: Path,
) -> None:
    """A state.json with the old 'auto_agent_attempts' key loads without error.

    StateData has extra='ignore', so the stale key is silently dropped. The
    accessor must then return 0 (not 2) — the old field is not read.
    """
    import json

    from models import StateData

    old_state: dict = {
        "auto_agent_attempts": {"7": 2},
        "convergence_ledgers": {},
    }
    # model_validate must not raise
    data = StateData.model_validate(old_state)
    assert not hasattr(data, "auto_agent_attempts")

    # Wire it into a tracker via disk so the full load path is exercised.
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(old_state))
    tracker = StateTracker(state_file=state_file)
    assert tracker.get_auto_agent_attempts(7) == 0
