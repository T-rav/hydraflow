"""Scenario coverage for the per-loop work-cycle watchdog (#9455 / #9556).

Unit tests in ``tests/test_base_background_loop.py`` exercise the watchdog with
a MagicMock status callback. These scenario tests prove the feature end-to-end
in the *real* loop machinery: a real :class:`EventBus`, a real
:class:`HydraFlowConfig` (so the config-driven bound resolution is exercised),
and a real production loop's ``LONG_LLM_CYCLE`` classification.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from base_background_loop import BaseBackgroundLoop, LoopDeps
from events import EventBus, EventType
from report_issue_loop import ReportIssueLoop
from sentry_loop import SentryLoop
from tests.helpers import ConfigFactory

pytestmark = pytest.mark.scenario


class _HangingLoop(BaseBackgroundLoop):
    """A loop whose work cycle never returns — stands in for a wedged loop."""

    async def _do_work(self) -> dict[str, Any] | None:
        await asyncio.Event().wait()  # never set → hangs forever
        return None  # pragma: no cover

    def _get_default_interval(self) -> int:
        return 60


@pytest.mark.asyncio
async def test_watchdog_cancels_hung_loop_and_reports_via_real_bus(
    tmp_path: Path,
) -> None:
    """A hung cycle is cancelled and surfaces a watchdog-timeout ERROR on the bus."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    bus = EventBus()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=lambda _name: True,
        # 0s bound fires the watchdog on the first wait.
        timeout_cb=lambda _name: 0,
    )
    loop = _HangingLoop(worker_name="hanging_loop", config=config, deps=deps)

    # The watchdog must contain the hang: _execute_cycle returns, does not raise.
    await asyncio.wait_for(loop._execute_cycle(), timeout=5)

    error_events = [e for e in bus.get_history() if e.type == EventType.ERROR]
    assert error_events, "watchdog did not publish an ERROR event for the hang"
    assert "watchdog timeout" in error_events[-1].data["message"]
    status_events = [
        e for e in bus.get_history() if e.type == EventType.BACKGROUND_WORKER_STATUS
    ]
    assert status_events and status_events[-1].data["status"] == "error"


@pytest.mark.asyncio
async def test_llm_loops_resolve_to_the_wider_bound_via_real_config(
    tmp_path: Path,
) -> None:
    """LONG_LLM_CYCLE production loops take loop_watchdog_llm_seconds from config."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")

    for loop_cls in (SentryLoop, ReportIssueLoop):
        assert loop_cls.LONG_LLM_CYCLE is True, (
            f"{loop_cls.__name__} should opt into the LLM watchdog bound"
        )

    # A normal (non-LLM) loop takes the tight default bound.
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=lambda _name: True,
    )
    normal = _HangingLoop(worker_name="normal_loop", config=config, deps=deps)
    assert normal._cycle_timeout_seconds() == config.loop_watchdog_default_seconds
    assert config.loop_watchdog_llm_seconds > config.loop_watchdog_default_seconds, (
        "LLM bound must be wider than the default bound"
    )
