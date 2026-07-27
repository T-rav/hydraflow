"""Unit tests for the formal give-up window (#10735).

Covers the pure policy (GiveUpWindow / resolve_window), the N-in-T tracker,
and the StateTracker give-up mixin (persistence + snapshot + GC close-to-clear).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import HydraFlowConfig
from giveup_window import (
    GiveUpClass,
    GiveUpTracker,
    GiveUpWindow,
    SelfSolveOutcome,
    resolve_window,
)
from state import StateTracker


class _Clock:
    """A hand-cranked monotonic clock for deterministic window tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# GiveUpWindow / resolve_window
# ---------------------------------------------------------------------------


class TestResolveWindow:
    def test_per_class_defaults_are_distinct(self) -> None:
        cfg = HydraFlowConfig()
        build = resolve_window(cfg, GiveUpClass.BUILD)
        review = resolve_window(cfg, GiveUpClass.REVIEW)
        loop = resolve_window(cfg, GiveUpClass.LOOP)
        plan = resolve_window(cfg, GiveUpClass.PLAN_RETRY)

        assert (build.max_restarts, build.window_seconds) == (3, 3600)
        assert (review.max_restarts, review.window_seconds) == (3, 3600)
        assert (loop.max_restarts, loop.window_seconds) == (5, 3600)
        # plan_retry defaults to the legacy max_route_backs (2).
        assert (plan.max_restarts, plan.window_seconds) == (2, 3600)
        assert plan.child_class is GiveUpClass.PLAN_RETRY

    def test_resolve_reads_config_overrides(self) -> None:
        cfg = HydraFlowConfig(giveup_plan_retry_max_restarts=7)
        assert resolve_window(cfg, GiveUpClass.PLAN_RETRY).max_restarts == 7

    def test_is_exhausted_threshold(self) -> None:
        w = GiveUpWindow(GiveUpClass.PLAN_RETRY, max_restarts=2, window_seconds=60)
        assert not w.is_exhausted(1)
        assert w.is_exhausted(2)
        assert w.is_exhausted(3)


# ---------------------------------------------------------------------------
# GiveUpTracker — N-in-T semantics
# ---------------------------------------------------------------------------


class TestGiveUpTracker:
    def _setup(self, tmp_path: Path, *, start: float = 1000.0):
        state = StateTracker(tmp_path / "state.json")
        clock = _Clock(start)
        tracker = GiveUpTracker(state, clock=clock)
        return state, clock, tracker

    def test_counts_events_within_window(self, tmp_path: Path) -> None:
        _state, clock, tracker = self._setup(tmp_path)
        w = GiveUpWindow(GiveUpClass.PLAN_RETRY, max_restarts=3, window_seconds=100)

        assert tracker.record_and_count(42, w) == 1
        clock.advance(10)
        assert tracker.record_and_count(42, w) == 2
        clock.advance(10)
        assert tracker.record_and_count(42, w) == 3

    def test_events_outside_window_are_pruned(self, tmp_path: Path) -> None:
        _state, clock, tracker = self._setup(tmp_path)
        w = GiveUpWindow(GiveUpClass.PLAN_RETRY, max_restarts=3, window_seconds=100)

        assert tracker.record_and_count(42, w) == 1
        clock.advance(50)
        assert tracker.record_and_count(42, w) == 2
        # Jump past the window: the first two events (>100s old) are pruned,
        # leaving only the just-recorded one. N-in-T is a SLIDING window.
        clock.advance(200)
        assert tracker.record_and_count(42, w) == 1

    def test_per_issue_and_per_class_isolation(self, tmp_path: Path) -> None:
        _state, _clock, tracker = self._setup(tmp_path)
        plan = GiveUpWindow(GiveUpClass.PLAN_RETRY, max_restarts=3, window_seconds=100)
        build = GiveUpWindow(GiveUpClass.BUILD, max_restarts=3, window_seconds=100)

        tracker.record_and_count(1, plan)
        tracker.record_and_count(1, plan)
        # Different issue and different class both start fresh.
        assert tracker.record_and_count(2, plan) == 1
        assert tracker.record_and_count(1, build) == 1
        assert tracker.count_in_window(1, plan) == 2

    def test_reset_clears_window(self, tmp_path: Path) -> None:
        _state, _clock, tracker = self._setup(tmp_path)
        w = GiveUpWindow(GiveUpClass.PLAN_RETRY, max_restarts=3, window_seconds=100)
        tracker.record_and_count(42, w)
        tracker.record_and_count(42, w)
        assert tracker.count_in_window(42, w) == 2

        tracker.reset(42, w)
        assert tracker.count_in_window(42, w) == 0

    def test_record_action_persists_for_api(self, tmp_path: Path) -> None:
        state, _clock, tracker = self._setup(tmp_path)
        w = GiveUpWindow(GiveUpClass.PLAN_RETRY, max_restarts=2, window_seconds=100)
        tracker.record_and_count(42, w)
        tracker.record_action(42, w, SelfSolveOutcome.DECOMPOSED)

        snap = state.get_give_up_snapshot(42)
        assert snap["plan_retry"]["last_action"] == "decompose"
        assert snap["plan_retry"]["action_count"] == 1

    def test_timestamps_survive_restart(self, tmp_path: Path) -> None:
        state, clock, tracker = self._setup(tmp_path)
        w = GiveUpWindow(GiveUpClass.PLAN_RETRY, max_restarts=3, window_seconds=10_000)
        tracker.record_and_count(42, w)
        tracker.record_and_count(42, w)

        reloaded = StateTracker(tmp_path / "state.json")
        reloaded_tracker = GiveUpTracker(reloaded, clock=clock)
        # The persisted events count toward the window after a restart.
        assert reloaded_tracker.count_in_window(42, w) == 2


# ---------------------------------------------------------------------------
# State mixin — snapshot + GC close-to-clear
# ---------------------------------------------------------------------------


class TestGiveUpStateMixin:
    def test_snapshot_shape(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.record_give_up_event(42, "plan_retry", 1000.0)
        state.record_give_up_event(42, "plan_retry", 1001.0)
        state.record_give_up_action(42, "plan_retry", "decompose", 1002.0)

        snap = state.get_give_up_snapshot(42)
        assert snap["plan_retry"]["cycle_count"] == 2
        assert snap["plan_retry"]["last_action"] == "decompose"
        assert snap["plan_retry"]["last_exhausted_ts"] == 1002.0

    def test_all_snapshots_keyed_by_int(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.record_give_up_event(1, "plan_retry", 1.0)
        state.record_give_up_event(2, "build", 2.0)

        allsnaps = state.all_give_up_snapshots()
        assert set(allsnaps) == {1, 2}
        assert "plan_retry" in allsnaps[1]
        assert "build" in allsnaps[2]

    def test_closed_issue_give_up_state_is_gc_cleared(self, tmp_path: Path) -> None:
        """A closed issue's give-up window must not leak into a re-filed issue."""
        state = StateTracker(tmp_path / "state.json")
        state.record_give_up_event(100, "plan_retry", 1.0)
        state.record_give_up_event(999, "plan_retry", 1.0)

        removed = state.prune_issue_scoped_state({100})

        assert removed["give_up_events"] == 1
        assert state.get_give_up_snapshot(100) != {}
        assert state.get_give_up_snapshot(999) == {}

    def test_open_issue_give_up_state_survives_sweep(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.record_give_up_event(100, "plan_retry", 1.0)
        state.record_give_up_event(999, "plan_retry", 1.0)

        removed = state.prune_issue_scoped_state({100, 999})

        assert "give_up_events" not in removed
        assert state.get_give_up_snapshot(100) != {}
        assert state.get_give_up_snapshot(999) != {}

    def test_reset_preserves_action_audit(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.record_give_up_event(42, "plan_retry", 1.0)
        state.record_give_up_action(42, "plan_retry", "decompose", 2.0)

        state.reset_give_up(42, "plan_retry")

        snap = state.get_give_up_snapshot(42)
        # Timestamps cleared (fresh window) but the historical action is kept.
        assert snap["plan_retry"]["cycle_count"] == 0
        assert snap["plan_retry"]["last_action"] == "decompose"


@pytest.mark.parametrize(
    ("cls", "field_stem"),
    [
        (GiveUpClass.BUILD, "build"),
        (GiveUpClass.REVIEW, "review"),
        (GiveUpClass.LOOP, "loop"),
        (GiveUpClass.PLAN_RETRY, "plan_retry"),
    ],
)
def test_every_class_has_config_fields(cls: GiveUpClass, field_stem: str) -> None:
    """resolve_window must find both config fields for every child-class."""
    cfg = HydraFlowConfig()
    assert hasattr(cfg, f"giveup_{field_stem}_max_restarts")
    assert hasattr(cfg, f"giveup_{field_stem}_window_secs")
    w = resolve_window(cfg, cls)
    assert w.max_restarts >= 1
    assert w.window_seconds >= 1
