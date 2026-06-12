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
