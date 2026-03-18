"""Tests for DORA metrics tracker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from dora_tracker import DORASnapshot, DORATracker, _median
from events import EventBus, EventType, HydraFlowEvent
from release_decision import ReleasePolicy


def _make_event(
    event_type: str,
    data: dict | None = None,
    timestamp: datetime | None = None,
) -> HydraFlowEvent:
    ts = timestamp or datetime.now(UTC)
    return HydraFlowEvent(
        type=EventType(event_type),
        timestamp=ts.isoformat(),
        data=data or {},
    )


class TestMedian:
    def test_empty(self) -> None:
        assert _median([]) == 0.0

    def test_single(self) -> None:
        assert _median([5.0]) == 5.0

    def test_odd(self) -> None:
        assert _median([1.0, 3.0, 2.0]) == 2.0

    def test_even(self) -> None:
        assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5


class TestDORASnapshot:
    def test_default_values(self) -> None:
        snap = DORASnapshot()
        assert snap.deployment_frequency == 0.0
        assert snap.rework_rate == 0.0


class TestDORATracker:
    def _make_tracker(
        self,
        events: list[HydraFlowEvent] | None = None,
    ) -> DORATracker:
        state = MagicMock()
        bus = EventBus()
        if events:
            bus._history = list(events)
        return DORATracker(state, bus)

    def test_empty_history(self) -> None:
        tracker = self._make_tracker()
        snap = tracker.snapshot()
        assert snap.deployment_frequency == 0.0
        assert snap.change_failure_rate == 0.0
        assert snap.rework_rate == 0.0

    def test_deployment_frequency(self) -> None:
        now = datetime.now(UTC)
        events = [
            _make_event(
                "merge_update",
                {"status": "merged"},
                now - timedelta(days=1),
            ),
            _make_event(
                "merge_update",
                {"status": "merged"},
                now - timedelta(days=2),
            ),
            _make_event(
                "merge_update",
                {"status": "merged"},
                now - timedelta(days=3),
            ),
        ]
        tracker = self._make_tracker(events)
        snap = tracker.snapshot()
        # 3 merges in 7-day window → 3/7 ≈ 0.429
        assert snap.deployment_frequency == pytest.approx(3 / 7, abs=0.01)

    def test_change_failure_rate(self) -> None:
        now = datetime.now(UTC)
        events = [
            _make_event(
                "merge_update",
                {"status": "merged"},
                now - timedelta(days=5),
            ),
            _make_event(
                "merge_update",
                {"status": "merged"},
                now - timedelta(days=10),
            ),
            _make_event(
                "hitl_escalation",
                {"issue": 1},
                now - timedelta(days=8),
            ),
        ]
        tracker = self._make_tracker(events)
        snap = tracker.snapshot()
        # 1 HITL / 2 merges = 0.5
        assert snap.change_failure_rate == pytest.approx(0.5, abs=0.01)

    def test_rework_events(self) -> None:
        now = datetime.now(UTC)
        events = [
            _make_event(
                "merge_update",
                {"status": "merged"},
                now - timedelta(days=5),
            ),
            _make_event(
                "merge_update",
                {"status": "merged"},
                now - timedelta(days=10),
            ),
            _make_event(
                "phase_change",
                {"rework": True},
                now - timedelta(days=7),
            ),
        ]
        tracker = self._make_tracker(events)
        snap = tracker.snapshot()
        # 1 rework / 2 merges = 0.5
        assert snap.rework_rate == pytest.approx(0.5, abs=0.01)

    def test_is_healthy_true(self) -> None:
        tracker = self._make_tracker()
        policy = ReleasePolicy(max_rework_rate=0.15, max_change_failure_rate=0.20)
        assert tracker.is_healthy(policy) is True

    def test_is_healthy_false(self) -> None:
        now = datetime.now(UTC)
        # Create many HITL events relative to merges
        events = [
            _make_event("merge_update", {"status": "merged"}, now - timedelta(days=5)),
            _make_event("hitl_escalation", {"issue": 1}, now - timedelta(days=4)),
            _make_event("hitl_escalation", {"issue": 2}, now - timedelta(days=3)),
        ]
        tracker = self._make_tracker(events)
        policy = ReleasePolicy(max_change_failure_rate=0.10)
        # 2 HITL / 1 merge = 2.0 > 0.10
        assert tracker.is_healthy(policy) is False

    def test_health_dict(self) -> None:
        tracker = self._make_tracker()
        d = tracker.health_dict()
        assert "deployment_frequency" in d
        assert "rework_rate" in d
        assert isinstance(d["rework_rate"], float)

    def test_old_events_excluded_from_short_window(self) -> None:
        now = datetime.now(UTC)
        events = [
            _make_event(
                "merge_update",
                {"status": "merged"},
                now - timedelta(days=10),
            ),
        ]
        tracker = self._make_tracker(events)
        snap = tracker.snapshot()
        # Event is outside 7-day window for deployment frequency
        assert snap.deployment_frequency == 0.0
