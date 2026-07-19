"""Regression: events.jsonl grew unbounded to 660 MB; state.json to 7 MB (#9905).

Two independent leaks:

1. ``EventLog.rotate`` ran only at boot AND filtered only by age, so a
   flood written within the retention window (the #9895 credit-flood wrote
   hundreds of MB in minutes) was 100% retained even when rotation ran,
   and a long-lived instance never rotated at all.

2. Per-issue ``state.json`` entries (``adversarial_states`` was 6.03 MB of
   a 7.1 MB file) are only cleared on happy-path exits — issues terminated
   by manual close / HITL close / supersede strand their entries forever.

Pins:
- Rotation enforces the byte budget: post-rotation file <= max_size_bytes,
  newest events survive, age filtering still applies.
- RunsGCLoop rotates the event log every cycle behind its kill-switch.
- StateTracker.prune_issue_scoped_state drops only stale integer-keyed
  entries and is a no-op on an empty keep-set (fail-closed: an API fault
  returning zero open issues must never wipe in-flight state).
- StaleIssueGCLoop drives the prune from GitHub truth via
  PRPort.list_open_issue_numbers, skipping on port failure.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from events import EventLog, EventType, HydraFlowEvent
from models import ConvergenceLedger
from pending_concerns import AdversarialState
from run_recorder import RunRecorder
from runs_gc_loop import RunsGCLoop
from stale_issue_gc_loop import StaleIssueGCLoop
from state import StateTracker
from tests.helpers import make_bg_loop_deps


def _write_events(path: Path, *, count: int, age_days: float = 0.0) -> None:
    ts = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
    with open(path, "a") as f:
        for i in range(count):
            event = HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                timestamp=ts,
                data={"seq": i, "pad": "x" * 200},
            )
            f.write(event.model_dump_json() + "\n")


class TestRotationSizeBound:
    def test_flood_within_retention_window_is_trimmed_to_byte_budget(
        self, tmp_path: Path
    ) -> None:
        """A recent flood must not survive rotation just because it is recent."""
        log_path = tmp_path / "events.jsonl"
        log = EventLog(log_path)
        _write_events(log_path, count=200, age_days=0.0)
        max_size = 4096

        stats = log._rotate_sync(max_size_bytes=max_size, max_age_days=7)

        assert log_path.stat().st_size <= max_size
        assert stats["dropped_size"] > 0
        assert stats["dropped_age"] == 0
        # Newest events survive: the highest sequence number is retained.
        lines = log_path.read_text().splitlines()
        assert lines, "size bound must not empty the log entirely"
        last = json.loads(lines[-1])
        assert last["data"]["seq"] == 199

    def test_age_filter_still_drops_expired_events(self, tmp_path: Path) -> None:
        log_path = tmp_path / "events.jsonl"
        log = EventLog(log_path)
        _write_events(log_path, count=50, age_days=30.0)
        _write_events(log_path, count=5, age_days=0.0)

        # Byte budget generous enough that only the age filter bites.
        stats = log._rotate_sync(max_size_bytes=5000, max_age_days=7)

        assert stats["dropped_age"] == 50
        assert stats["dropped_size"] == 0
        assert stats["kept"] == 5

    def test_below_threshold_is_untouched(self, tmp_path: Path) -> None:
        log_path = tmp_path / "events.jsonl"
        log = EventLog(log_path)
        _write_events(log_path, count=3)
        before = log_path.read_text()

        stats = log._rotate_sync(max_size_bytes=10 * 1024 * 1024, max_age_days=7)

        assert stats == {}
        assert log_path.read_text() == before


class TestRunsGCRotatesEventLog:
    def _make_loop(self, tmp_path: Path, **overrides) -> RunsGCLoop:
        deps = make_bg_loop_deps(tmp_path, **overrides)
        loop = RunsGCLoop(
            config=deps.config,
            run_recorder=RunRecorder(deps.config),
            deps=deps.loop_deps,
        )
        loop._bus = MagicMock()
        loop._bus.rotate_log = AsyncMock(return_value={"kept": 1})
        loop._bus.publish = AsyncMock()
        return loop

    @pytest.mark.asyncio
    async def test_cycle_rotates_with_configured_bounds(self, tmp_path: Path) -> None:
        loop = self._make_loop(tmp_path)

        result = await loop._do_work()

        loop._bus.rotate_log.assert_awaited_once_with(
            loop._config.event_log_max_size_mb * 1024 * 1024,
            loop._config.event_log_retention_days,
        )
        assert result["event_log_rotation"] == {"kept": 1}

    @pytest.mark.asyncio
    async def test_kill_switch_skips_rotation(self, tmp_path: Path) -> None:
        loop = self._make_loop(tmp_path)
        object.__setattr__(loop._config, "event_log_periodic_rotate_enabled", False)

        result = await loop._do_work()

        loop._bus.rotate_log.assert_not_awaited()
        assert result["event_log_rotation"] == {}


class TestStatePrune:
    def _tracker(self, tmp_path: Path) -> StateTracker:
        tracker = StateTracker(tmp_path / "state.json")
        tracker._data.issue_attempts = {"100": 2, "200": 1}
        tracker._data.convergence_ledgers = {
            "100": ConvergenceLedger(issue_number=100),
            "200": ConvergenceLedger(issue_number=200),
        }
        tracker._data.adversarial_states = {
            "100": AdversarialState(phase="plan"),
            "999": AdversarialState(phase="plan"),
        }
        tracker.set_hitl_summary(100, "live")
        tracker.set_hitl_summary(998, "stale")
        return tracker

    def test_prunes_only_entries_for_issues_no_longer_open(
        self, tmp_path: Path
    ) -> None:
        tracker = self._tracker(tmp_path)

        removed = tracker.prune_issue_scoped_state({100})

        assert removed == {
            "adversarial_states": 1,
            "convergence_ledgers": 1,
            "hitl_summaries": 1,
            "issue_attempts": 1,
        }
        assert set(tracker._data.issue_attempts) == {"100"}
        assert set(tracker._data.convergence_ledgers) == {"100"}
        assert set(tracker._data.adversarial_states) == {"100"}
        assert set(tracker._data.hitl_summaries) == {"100"}

    def test_empty_keep_set_is_a_noop(self, tmp_path: Path) -> None:
        """Fail-closed: empty listing is indistinguishable from an API fault."""
        tracker = self._tracker(tmp_path)

        removed = tracker.prune_issue_scoped_state(set())

        assert removed == {}
        assert set(tracker._data.adversarial_states) == {"100", "999"}

    def test_non_integer_keys_are_never_pruned(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)
        tracker._data.issue_attempts["not-an-issue"] = 1

        tracker.prune_issue_scoped_state({100})

        assert "not-an-issue" in tracker._data.issue_attempts

    def test_prune_persists_to_disk(self, tmp_path: Path) -> None:
        tracker = self._tracker(tmp_path)
        tracker.save()

        tracker.prune_issue_scoped_state({100})

        reloaded = StateTracker(tmp_path / "state.json")
        assert set(reloaded._data.adversarial_states) == {"100"}


class TestStaleIssueGCDrivesPrune:
    def _make_loop(
        self, tmp_path: Path, **overrides
    ) -> tuple[StaleIssueGCLoop, MagicMock, MagicMock]:
        deps = make_bg_loop_deps(tmp_path, **overrides)
        pr = MagicMock()
        pr.list_issues_by_label = AsyncMock(return_value=[])
        pr.list_open_issue_numbers = AsyncMock(return_value=[10, 11])
        state = MagicMock()
        state.prune_issue_scoped_state.return_value = {"issue_attempts": 3}
        loop = StaleIssueGCLoop(
            config=deps.config, pr_manager=pr, state=state, deps=deps.loop_deps
        )
        return loop, pr, state

    @pytest.mark.asyncio
    async def test_prunes_against_open_issue_numbers(self, tmp_path: Path) -> None:
        loop, _pr, state = self._make_loop(tmp_path)

        result = await loop._do_work()

        state.prune_issue_scoped_state.assert_called_once_with({10, 11})
        assert result["state_pruned"] == {"issue_attempts": 3}

    @pytest.mark.asyncio
    async def test_port_failure_skips_prune(self, tmp_path: Path) -> None:
        loop, pr, state = self._make_loop(tmp_path)
        pr.list_open_issue_numbers.side_effect = RuntimeError("gh down")

        result = await loop._do_work()

        state.prune_issue_scoped_state.assert_not_called()
        assert result["state_pruned"] == {}

    @pytest.mark.asyncio
    async def test_empty_listing_skips_prune(self, tmp_path: Path) -> None:
        loop, pr, state = self._make_loop(tmp_path)
        pr.list_open_issue_numbers.return_value = []

        await loop._do_work()

        state.prune_issue_scoped_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_kill_switch_skips_prune(self, tmp_path: Path) -> None:
        loop, pr, state = self._make_loop(tmp_path)
        object.__setattr__(loop._config, "state_prune_enabled", False)

        await loop._do_work()

        pr.list_open_issue_numbers.assert_not_awaited()
        state.prune_issue_scoped_state.assert_not_called()


# Guard against event-loop policy leakage between async test modules.
asyncio.set_event_loop_policy(None)
