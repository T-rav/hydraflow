"""Tests for PrinciplesAuditStateMixin fields + accessors."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def test_state_data_has_principles_audit_fields(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    data = tracker._data  # type: ignore[attr-defined]
    assert data.managed_repos_onboarding_status == {}
    assert data.last_green_audit == {}
    assert data.principles_drift_attempts == {}
