"""MockWorld scenario for TrustFleetSanityLoop (spec §12.1).

Two existing scenarios (class TestTrustFleetSanityScenario):

* ``test_no_anomaly_no_file`` — all nine watched loops reporting fresh
  heartbeats with zero issue production and zero errors. The sanity loop
  should file nothing.
* ``test_staleness_breach_files_escalation`` — `flake_tracker` heartbeat
  is old enough that the staleness detector fires. The loop should file
  one ``hitl-escalation`` + ``trust-loop-anomaly`` issue with labels
  that include the breached detector kind.

New breach-path scenarios (class TestTrustFleetSanityBreachScenario):

* ``test_issues_per_hour_breach_files_escalation`` — rc_budget filing
  many issues within the hour window. Exercises the issues_per_hour
  breach path end-to-end through MockWorld without requiring
  BGWorkerManager (staleness skipped; metrics seeded via EventBus stub).
* ``test_repair_ratio_breach_files_escalation`` — rc_budget reports a high
  failed/repaired ratio. Exercises the repair_ratio breach path end-to-end.

The loop's external surface (``_collect_window_metrics`` via the
EventBus, ``_load_cost_reader``, ``_reconcile_closed_escalations``) is
stubbed via pre-seeded port keys.
"""

from __future__ import annotations

import datetime as _dt
from unittest.mock import MagicMock

import pytest

from events import EventBus, EventType, HydraFlowEvent
from models import Severity
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _fresh_heartbeat(now: _dt.datetime) -> dict[str, object]:
    return {"status": "ok", "last_run": now.isoformat(), "details": {}}


def _healthy_heartbeats(now: _dt.datetime) -> dict[str, dict[str, object]]:
    """All nine §4.1–§4.9 trust loops reporting fresh heartbeats."""
    return {
        name: _fresh_heartbeat(now)
        for name in (
            "corpus_learning",
            "contract_refresh",
            "staging_bisect",
            "principles_audit",
            "flake_tracker",
            "skill_prompt_eval",
            "fake_coverage_auditor",
            "rc_budget",
            "wiki_rot_detector",
        )
    }


class TestTrustFleetSanityScenario:
    """§12.1 — meta-observability MockWorld scenarios."""

    async def test_no_anomaly_no_file(self, tmp_path) -> None:
        """Healthy fleet → loop runs, finds nothing, files nothing."""
        world = MockWorld(tmp_path)

        now = _dt.datetime.now(_dt.UTC)
        state = MagicMock()
        state.get_worker_heartbeats.return_value = _healthy_heartbeats(now)
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}

        _seed_ports(
            world,
            trust_fleet_sanity_state=state,
            event_bus=EventBus(),
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=1)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) == 0, stats
        assert world.github._issues == {}

    async def test_staleness_breach_files_escalation(self, tmp_path) -> None:
        """One watched loop silent far beyond its interval → escalation filed."""
        world = MockWorld(tmp_path)

        now = _dt.datetime.now(_dt.UTC)
        heartbeats = _healthy_heartbeats(now)
        # flake_tracker silent for 30 days — far beyond any reasonable
        # `2 × flake_tracker_interval`, triggering the staleness detector.
        heartbeats["flake_tracker"] = {
            "status": "ok",
            "last_run": (now - _dt.timedelta(days=30)).isoformat(),
            "details": {},
        }

        state = MagicMock()
        state.get_worker_heartbeats.return_value = heartbeats
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}

        # Simulate an enabled BGWorkerManager reporting flake_tracker as
        # enabled (so the staleness detector does not suppress the breach).
        bg_workers = MagicMock()
        bg_workers.worker_enabled = dict.fromkeys(heartbeats, True)
        bg_workers.get_interval = MagicMock(return_value=14400)  # 4h default

        _seed_ports(
            world,
            trust_fleet_sanity_state=state,
            trust_fleet_sanity_bg_workers=bg_workers,
            # #11119: boot grace shields persisted heartbeats on a fresh
            # boot; backdate boot past the threshold so a REAL post-boot
            # stall is what's under test. Filing then needs the breach to
            # survive two consecutive ticks (confirm-before-escalate).
            trust_fleet_sanity_boot_time=now - _dt.timedelta(days=29),
            event_bus=EventBus(),
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=2)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) >= 1, stats

        issue = next(iter(world.github._issues.values()))
        labels = issue.labels
        assert "hitl-escalation" in labels
        assert "trust-loop-anomaly" in labels

    async def test_cold_boot_old_heartbeats_do_not_escalate(self, tmp_path) -> None:
        """#11119 idle-test regression: heartbeats aged by DOWNTIME (fresh
        boot, whole fleet 'stale' on persisted clocks) must file nothing."""
        world = MockWorld(tmp_path)

        now = _dt.datetime.now(_dt.UTC)
        heartbeats = _healthy_heartbeats(now)
        heartbeats["flake_tracker"] = {
            "status": "ok",
            "last_run": (now - _dt.timedelta(days=30)).isoformat(),
            "details": {},
        }

        state = MagicMock()
        state.get_worker_heartbeats.return_value = heartbeats
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}

        bg_workers = MagicMock()
        bg_workers.worker_enabled = dict.fromkeys(heartbeats, True)
        bg_workers.get_interval = MagicMock(return_value=14400)

        _seed_ports(
            world,
            trust_fleet_sanity_state=state,
            trust_fleet_sanity_bg_workers=bg_workers,
            # Default boot_time (None → construction time = now): the fleet
            # just booted, so the 30-day-old heartbeat is downtime, not stall.
            event_bus=EventBus(),
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=2)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) == 0, stats
        assert not world.github._issues


# ---------------------------------------------------------------------------
# Breach-path scenario — issues_per_hour (advisor-t27j)
# ---------------------------------------------------------------------------


class TestTrustFleetSanityBreachScenario:
    """§12.1 — breach-path MockWorld scenarios (advisor-t27j).

    These tests do NOT seed a BGWorkerManager, so staleness detection is
    disabled (non-trust workers skip the staleness check). Breach signals
    come from event-bus events seeded into the loop's EventBus.
    """

    async def test_issues_per_hour_breach_files_escalation(self, tmp_path) -> None:
        """rc_budget files 20 issues in the last hour -> issues_per_hour escalation.

        Default threshold is 10. This exercises the full breach path through
        MockWorld: event collection, threshold evaluation, issue creation, and
        dedup set update.
        """
        world = MockWorld(tmp_path)

        now = _dt.datetime.now(_dt.UTC)

        # Build an EventBus pre-loaded with a status event reporting 20 filed
        # issues in the last hour for rc_budget. The loop reads from this bus
        # via _collect_window_metrics -> load_events_since.
        seeded_bus = EventBus()
        ts_recent = (now - _dt.timedelta(seconds=300)).isoformat()
        breach_event = HydraFlowEvent(
            type=EventType.BACKGROUND_WORKER_STATUS,
            timestamp=ts_recent,
            data={
                "worker": "rc_budget",
                "status": "ok",
                "details": {"filed": 20, "repaired": 0, "failed": 0},
            },
        )

        async def _preloaded_load(since: _dt.datetime) -> list[HydraFlowEvent]:
            return [breach_event] if breach_event.timestamp >= since.isoformat() else []

        seeded_bus.load_events_since = _preloaded_load  # type: ignore[method-assign]

        state = MagicMock()
        state.get_worker_heartbeats.return_value = {}
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}

        _seed_ports(
            world,
            trust_fleet_sanity_state=state,
            event_bus=seeded_bus,
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=1)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) >= 1, stats

        issue = next(iter(world.github._issues.values()))
        assert "rc_budget" in issue.title
        assert "issues_per_hour" in issue.title

        labels = issue.labels
        assert "hitl-escalation" in labels
        assert "trust-loop-anomaly" in labels

    async def test_tick_error_ratio_breach_files_escalation(self, tmp_path) -> None:
        """corpus_learning with 80% errored ticks -> tick_error_ratio escalation.

        4 errored / 5 total = 0.8, which exceeds the default threshold of 0.2.
        Verifies a second distinct breach kind reaches the issue-filing path.
        """
        world = MockWorld(tmp_path)

        now = _dt.datetime.now(_dt.UTC)
        seeded_bus = EventBus()

        def _make_ev(status: str, ago_s: int) -> HydraFlowEvent:
            ts = (now - _dt.timedelta(seconds=ago_s)).isoformat()
            return HydraFlowEvent(
                type=EventType.BACKGROUND_WORKER_STATUS,
                timestamp=ts,
                data={"worker": "corpus_learning", "status": status, "details": {}},
            )

        all_events = [
            _make_ev("ok", 3601),
            _make_ev("error", 3602),
            _make_ev("error", 3603),
            _make_ev("error", 3604),
            _make_ev("error", 3605),
        ]

        async def _preloaded_load(since: _dt.datetime) -> list[HydraFlowEvent]:
            return [e for e in all_events if e.timestamp >= since.isoformat()]

        seeded_bus.load_events_since = _preloaded_load  # type: ignore[method-assign]

        state = MagicMock()
        state.get_worker_heartbeats.return_value = {}
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}

        _seed_ports(
            world,
            trust_fleet_sanity_state=state,
            event_bus=seeded_bus,
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=1)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) >= 1, stats

        titles = [issue.title for issue in world.github._issues.values()]
        assert any("tick_error_ratio" in t and "corpus_learning" in t for t in titles)

    async def test_repair_ratio_breach_files_escalation(self, tmp_path) -> None:
        """rc_budget with failed repairs dominating successes -> escalation."""
        world = MockWorld(tmp_path)

        now = _dt.datetime.now(_dt.UTC)
        seeded_bus = EventBus()
        ts_recent = (now - _dt.timedelta(seconds=900)).isoformat()
        breach_event = HydraFlowEvent(
            type=EventType.BACKGROUND_WORKER_STATUS,
            timestamp=ts_recent,
            data={
                "worker": "rc_budget",
                "status": "ok",
                "details": {"filed": 0, "repaired": 1, "failed": 10},
            },
        )

        async def _preloaded_load(since: _dt.datetime) -> list[HydraFlowEvent]:
            return [breach_event] if breach_event.timestamp >= since.isoformat() else []

        seeded_bus.load_events_since = _preloaded_load  # type: ignore[method-assign]

        state = MagicMock()
        state.get_worker_heartbeats.return_value = {}
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}

        _seed_ports(
            world,
            trust_fleet_sanity_state=state,
            event_bus=seeded_bus,
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=1)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) >= 1, stats

        issue = next(iter(world.github._issues.values()))
        assert "rc_budget" in issue.title
        assert "repair_ratio" in issue.title
        assert "hitl-escalation" in issue.labels
        assert "trust-loop-anomaly" in issue.labels

    async def test_hitl_composition_breach_files_escalation(self, tmp_path) -> None:
        """HITL queue full of memory-backlog housekeeping items -> fleet alert.

        Three open ``hitl-escalation`` issues that also carry the
        ``hydraflow-memory-backlog`` housekeeping label meet the default
        threshold of 3, so the loop files exactly one ``hitl_composition``
        escalation flagging the pipeline as over-escalating low-severity work
        into HITL (#10310). Exercises the full loop -> PRPort path end-to-end
        through MockWorld, including the ``list_issues_by_label`` queries.
        """
        world = MockWorld(tmp_path)

        for number in (5101, 5102, 5103):
            world.github.add_issue(
                number=number,
                title=f"HITL: mis-scoped housekeeping item {number}",
                body="A P4 memory-backlog item that should not sit in HITL.",
                labels=["hitl-escalation", "hydraflow-memory-backlog"],
            )

        state = MagicMock()
        state.get_worker_heartbeats.return_value = {}
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}
        state.get_diagnosis_severity.return_value = None  # driven by the label

        _seed_ports(
            world,
            trust_fleet_sanity_state=state,
            event_bus=EventBus(),
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=1)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) == 1, stats

        titles = [issue.title for issue in world.github._issues.values()]
        assert any("hitl_composition" in t and "fleet" in t for t in titles), titles

    async def test_no_hitl_composition_when_queue_is_real_work(self, tmp_path) -> None:
        """HITL queue holding genuine (non-housekeeping) work -> no fleet alert."""
        world = MockWorld(tmp_path)

        for number in (5201, 5202, 5203):
            world.github.add_issue(
                number=number,
                title=f"HITL: genuine blocking bug {number}",
                body="Real P1 work legitimately escalated to a human.",
                labels=["hitl-escalation"],
            )

        state = MagicMock()
        state.get_worker_heartbeats.return_value = {}
        state.get_trust_fleet_sanity_attempts.return_value = 0
        state.inc_trust_fleet_sanity_attempts.return_value = 1
        state.get_trust_fleet_sanity_last_seen_counts.return_value = {}
        state.get_diagnosis_severity.return_value = Severity.P1_BLOCKING

        _seed_ports(
            world,
            trust_fleet_sanity_state=state,
            event_bus=EventBus(),
        )

        stats = await world.run_with_loops(["trust_fleet_sanity"], cycles=1)

        assert stats["trust_fleet_sanity"]["status"] == "ok", stats
        assert stats["trust_fleet_sanity"].get("filed", 0) == 0, stats
        titles = [issue.title for issue in world.github._issues.values()]
        assert not any("hitl_composition" in t for t in titles), titles
