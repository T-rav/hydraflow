"""Tests for confidence calibration background loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from confidence_calibration import CalibrationStore
from confidence_loop import ConfidenceCalibrationLoop
from dora_tracker import DORATracker
from events import EventBus, EventType
from tests.helpers import make_bg_loop_deps


class TestConfidenceCalibrationLoop:
    def _make_loop(
        self,
        tmp_path: Path,
        *,
        calibration_enabled: bool = True,
        bus: EventBus | None = None,
    ) -> tuple[ConfidenceCalibrationLoop, EventBus]:
        bg = make_bg_loop_deps(
            tmp_path,
            enabled=True,
            confidence_calibration_enabled=calibration_enabled,
            confidence_calibration_interval=60,
            confidence_calibration_min_samples=5,
            release_confidence_mode="observe",
        )
        event_bus = bus or bg.bus
        state = MagicMock()
        dora = DORATracker(state, event_bus)
        store = CalibrationStore(tmp_path / "outcomes.jsonl")

        loop = ConfidenceCalibrationLoop(
            config=bg.config,
            deps=bg.loop_deps,
            calibration_store=store,
            dora_tracker=dora,
        )
        return loop, event_bus

    @pytest.mark.asyncio
    async def test_do_work_publishes_dora_health(self, tmp_path: Path) -> None:
        loop, bus = self._make_loop(tmp_path)
        result = await loop._do_work()

        assert result is not None
        assert "dora_healthy" in result

        health_events = [
            e for e in bus.get_history() if e.type == EventType.DORA_HEALTH
        ]
        assert len(health_events) == 1
        assert "deployment_frequency" in health_events[0].data

    @pytest.mark.asyncio
    async def test_do_work_publishes_calibration_event(self, tmp_path: Path) -> None:
        loop, bus = self._make_loop(tmp_path)
        await loop._do_work()

        cal_events = [
            e for e in bus.get_history() if e.type == EventType.CONFIDENCE_CALIBRATION
        ]
        assert len(cal_events) == 1

    @pytest.mark.asyncio
    async def test_disabled_skips(self, tmp_path: Path) -> None:
        loop, bus = self._make_loop(tmp_path, calibration_enabled=False)
        result = await loop._do_work()

        assert result is not None
        assert result.get("skipped") is True

    @pytest.mark.asyncio
    async def test_default_interval(self, tmp_path: Path) -> None:
        loop, _ = self._make_loop(tmp_path)
        assert loop._get_default_interval() == 60
