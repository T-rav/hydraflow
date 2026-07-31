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
from bg_worker_manager import BGWorkerManager
from events import EventBus, EventType
from report_issue_loop import ReportIssueLoop
from state import StateTracker
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

    for loop_cls in (ReportIssueLoop,):
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


@pytest.mark.asyncio
async def test_operator_watchdog_override_takes_effect_on_the_loop(
    tmp_path: Path,
) -> None:
    """The System-tab watchdog-timeout override (#9503) actually reaches the
    watchdog — not just BGWorkerManager's in-memory table.

    Wires a real BGWorkerManager.get_timeout as the loop's timeout_cb, exactly
    as service_registry.py wires WorkerRegistryCallbacks.get_watchdog_timeout
    into the shared LoopDeps. Before any override the loop takes the wide
    config default; after the operator sets a 0s override the SAME loop's
    watchdog fires on its very next cycle — proving the read path, not just
    the write path (an unread override would be a silent no-op).
    """
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    state = StateTracker(tmp_path / "state.json")
    bus = EventBus()

    # Mirrors the real bootstrap order (service_registry.py): the loop
    # registry dict is populated after the loop is constructed, but
    # BGWorkerManager holds a reference to the SAME dict, so it sees the
    # loop once registered below.
    bg_loop_registry: dict[str, BaseBackgroundLoop] = {}
    bg_workers = BGWorkerManager(config, state, bg_loop_registry)
    deps = LoopDeps(
        event_bus=bus,
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=lambda _name: True,
        timeout_cb=bg_workers.get_timeout,
    )
    loop = _HangingLoop(worker_name="hanging_loop", config=config, deps=deps)
    bg_loop_registry["hanging_loop"] = loop

    # No override yet: the loop reads the wide config default through
    # BGWorkerManager.get_timeout -> loop._default_cycle_timeout_seconds().
    assert loop._cycle_timeout_seconds() == config.loop_watchdog_default_seconds

    # Operator sets a tight override via the same path the System tab route
    # calls (orchestrator.set_bg_worker_timeout -> BGWorkerManager.set_timeout).
    bg_workers.set_timeout("hanging_loop", 0)

    # The SAME loop instance now reads the override on its very next cycle —
    # no redeploy, no reconstruction.
    assert loop._cycle_timeout_seconds() == 0

    # And the watchdog actually fires at the new bound: the hung cycle is
    # cancelled and reported, instead of hanging until the wide default.
    await asyncio.wait_for(loop._execute_cycle(), timeout=5)

    error_events = [e for e in bus.get_history() if e.type == EventType.ERROR]
    assert error_events, "operator override did not reach the watchdog"
    assert "watchdog timeout" in error_events[-1].data["message"]

    # The override survives a restart — the whole point of #9503 ("no
    # redeploy" means the operator doesn't have to re-set it after one).
    state2 = StateTracker(tmp_path / "state.json")
    assert state2.get_watchdog_timeouts() == {"hanging_loop": 0}
