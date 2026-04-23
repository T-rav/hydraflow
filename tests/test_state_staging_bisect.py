"""Tests for the StagingBisectStateMixin fields and accessors."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def test_state_data_has_six_new_staging_bisect_fields(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    data = tracker._data  # type: ignore[attr-defined]
    assert data.last_green_rc_sha == ""
    assert data.last_rc_red_sha == ""
    assert data.rc_cycle_id == 0
    assert data.auto_reverts_in_cycle == 0
    assert data.auto_reverts_successful == 0
    assert data.flake_reruns_total == 0


def test_mixin_getters_return_defaults(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    assert tracker.get_last_green_rc_sha() == ""
    assert tracker.get_last_rc_red_sha() == ""
    assert tracker.get_rc_cycle_id() == 0
    assert tracker.get_auto_reverts_in_cycle() == 0
    assert tracker.get_auto_reverts_successful() == 0
    assert tracker.get_flake_reruns_total() == 0


def test_set_last_green_rc_sha_persists(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    tracker = StateTracker(state_file=path)
    tracker.set_last_green_rc_sha("abc123")
    reloaded = StateTracker(state_file=path)
    assert reloaded.get_last_green_rc_sha() == "abc123"


def test_set_last_rc_red_sha_bumps_cycle(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    tracker = StateTracker(state_file=path)
    tracker.set_last_rc_red_sha_and_bump_cycle("deadbeef")
    assert tracker.get_last_rc_red_sha() == "deadbeef"
    assert tracker.get_rc_cycle_id() == 1
    tracker.set_last_rc_red_sha_and_bump_cycle("cafef00d")
    assert tracker.get_rc_cycle_id() == 2


def test_increment_auto_reverts_in_cycle(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    assert tracker.increment_auto_reverts_in_cycle() == 1
    assert tracker.increment_auto_reverts_in_cycle() == 2
    tracker.reset_auto_reverts_in_cycle()
    assert tracker.get_auto_reverts_in_cycle() == 0


def test_increment_auto_reverts_successful(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    tracker.increment_auto_reverts_successful()
    tracker.increment_auto_reverts_successful()
    assert tracker.get_auto_reverts_successful() == 2


def test_increment_flake_reruns_total(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    tracker.increment_flake_reruns_total()
    assert tracker.get_flake_reruns_total() == 1
