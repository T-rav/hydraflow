"""Unit tests for the #11391 fleet-vitals shadow engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fleet_vitals import (
    ChangeEvent,
    FleetBands,
    FleetReading,
    FleetVitalsState,
    evaluate,
    rank_suspects,
    shadow_proposal,
)

NOW = datetime(2026, 8, 16, 16, 0, 0, tzinfo=UTC)
BANDS = FleetBands()


def _reading(hitl: float, fp: float = 0.8, *, at: datetime = NOW) -> FleetReading:
    return FleetReading(ts=at, hitl_rate=hitl, first_pass_rate=fp)


class TestHysteresis:
    def test_single_breach_does_not_alarm(self) -> None:
        state = FleetVitalsState()
        assert evaluate(state, _reading(0.9), bands=BANDS) == []

    def test_confirmed_breach_alarms_once(self) -> None:
        state = FleetVitalsState()
        evaluate(state, _reading(0.9), bands=BANDS)
        alarms = evaluate(state, _reading(0.9), bands=BANDS)
        assert [a.band for a in alarms] == ["hitl_rate"]
        # Continued breach: episode already active — no re-alarm.
        assert evaluate(state, _reading(0.95), bands=BANDS) == []

    def test_rearm_requires_settle_below_lower_threshold(self) -> None:
        state = FleetVitalsState()
        evaluate(state, _reading(0.9), bands=BANDS)
        evaluate(state, _reading(0.9), bands=BANDS)  # alarm fires
        # 0.4 is below alarm (0.5) but above re-arm (0.3): still active.
        evaluate(state, _reading(0.4), bands=BANDS)
        evaluate(state, _reading(0.9), bands=BANDS)
        assert evaluate(state, _reading(0.9), bands=BANDS) == []
        # Settle below re-arm, then a fresh confirmed breach re-alarms.
        evaluate(state, _reading(0.1), bands=BANDS)
        evaluate(state, _reading(0.9), bands=BANDS)
        alarms = evaluate(state, _reading(0.9), bands=BANDS)
        assert [a.band for a in alarms] == ["hitl_rate"]

    def test_breach_streak_resets_on_recovery(self) -> None:
        state = FleetVitalsState()
        evaluate(state, _reading(0.9), bands=BANDS)
        evaluate(state, _reading(0.1), bands=BANDS)
        assert evaluate(state, _reading(0.9), bands=BANDS) == []

    def test_first_pass_floor_band(self) -> None:
        state = FleetVitalsState()
        evaluate(state, _reading(0.1, 0.0), bands=BANDS)
        alarms = evaluate(state, _reading(0.1, 0.0), bands=BANDS)
        assert [a.band for a in alarms] == ["first_pass_rate"]


class TestSuspects:
    def test_newest_first_with_lookback(self) -> None:
        changes = [
            ChangeEvent(NOW - timedelta(hours=30), "merge", "old", "too old"),
            ChangeEvent(NOW - timedelta(hours=2), "merge", "recent", "recent"),
            ChangeEvent(NOW - timedelta(minutes=10), "merge", "newest", "newest"),
        ]
        picks = rank_suspects(NOW, changes)
        assert [s.ref for s in picks] == ["newest", "recent"]

    def test_config_flip_outranks_merge_at_equal_time(self) -> None:
        ts = NOW - timedelta(hours=1)
        changes = [
            ChangeEvent(ts, "merge", "m1", "merge"),
            ChangeEvent(ts, "config-flip", "flag_x", "flip"),
        ]
        assert rank_suspects(NOW, changes)[0].ref == "flag_x"

    def test_future_changes_excluded(self) -> None:
        changes = [ChangeEvent(NOW + timedelta(hours=1), "merge", "f", "future")]
        assert rank_suspects(NOW, changes) == ()


class TestShadowProposals:
    def test_merge_suspect_proposes_kill_switch(self) -> None:
        suspects = (ChangeEvent(NOW, "merge", "abc123", "tiering"),)
        text = shadow_proposal("hitl_rate", suspects)
        assert "SHADOW" in text
        assert "abc123" in text
        assert "kill-switch" in text

    def test_config_flip_proposes_revert(self) -> None:
        suspects = (ChangeEvent(NOW, "config-flip", "flag_y", "flip"),)
        assert "revert config flip 'flag_y'" in shadow_proposal("hitl_rate", suspects)

    def test_no_suspects_defaults_to_diagnostician_then_pause(self) -> None:
        text = shadow_proposal("hitl_rate", ())
        assert "diagnostician" in text
        assert "pause" in text


class TestStateRoundTrip:
    def test_round_trip_and_corrupt_fail_open(self) -> None:
        state = FleetVitalsState()
        evaluate(state, _reading(0.9), bands=BANDS)
        restored = FleetVitalsState.from_dict(state.to_dict())
        alarms = evaluate(restored, _reading(0.9), bands=BANDS)
        assert [a.band for a in alarms] == ["hitl_rate"]
        assert FleetVitalsState.from_dict("garbage").bands == {}


class TestLoopWiring:
    """_run_fleet_vitals wiring: alarm -> SYSTEM_ALERT + persisted state."""

    def _loop(self, tmp_path, *, enabled: bool = True):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from health_monitor_loop import HealthMonitorLoop

        loop = object.__new__(HealthMonitorLoop)
        loop._config = SimpleNamespace(
            fleet_vitals_enabled=enabled,
            fleet_hitl_rate_alarm=0.5,
            fleet_hitl_rate_rearm=0.3,
            fleet_first_pass_floor=0.05,
            fleet_alarm_confirm_windows=1,
            data_root=tmp_path,
            repo_root=tmp_path,
        )
        loop._bus = SimpleNamespace(publish=AsyncMock())
        loop._fleet_change_ledger = AsyncMock(return_value=[])
        return loop

    async def _metrics(self):
        from types import SimpleNamespace

        return SimpleNamespace(hitl_escalation_rate=0.74, first_pass_rate=0.0)

    import pytest as _pytest

    @_pytest.mark.asyncio
    async def test_alarm_publishes_and_persists(self, tmp_path) -> None:
        loop = self._loop(tmp_path)
        await loop._run_fleet_vitals(await self._metrics())
        assert loop._bus.publish.await_count == 2  # both bands
        payload = loop._bus.publish.await_args_list[0].args[0].data
        assert payload["kind"] == "fleet_vitals_alarm"
        assert "SHADOW" in payload["shadow_proposal"]
        assert (tmp_path / "fleet_vitals_state.json").exists()

    @_pytest.mark.asyncio
    async def test_disabled_flag_is_noop(self, tmp_path) -> None:
        loop = self._loop(tmp_path, enabled=False)
        await loop._run_fleet_vitals(await self._metrics())
        loop._bus.publish.assert_not_awaited()
        assert not (tmp_path / "fleet_vitals_state.json").exists()

    @_pytest.mark.asyncio
    async def test_episode_survives_restart(self, tmp_path) -> None:
        """Persisted state: a restart must not re-alarm an active episode."""
        loop = self._loop(tmp_path)
        await loop._run_fleet_vitals(await self._metrics())
        fresh = self._loop(tmp_path)
        await fresh._run_fleet_vitals(await self._metrics())
        fresh._bus.publish.assert_not_awaited()
