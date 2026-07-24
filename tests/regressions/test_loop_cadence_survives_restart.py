"""Regression: interval loops must respect their durable ``last_run`` marker on
restart, not fire a cycle on every reboot.

Symptom (entry-evidence UL PR pile-up): the factory server restarts often, and
``BaseBackgroundLoop.run()`` ran a cycle as the FIRST action of its while loop
— before any sleep — for every non-``run_on_startup`` loop. So each reboot
immediately re-ran ``EntryEvidenceLoop`` (24h interval) and opened a fresh
``feat(ul): entry-evidence`` PR, producing ~6 PRs/day instead of the intended
one. The ``.{worker}_last_run`` history existed but the startup path never
checked it against the interval.

Fix: on startup, if the persisted marker shows the loop ran less than an
interval ago, sleep the remaining time before the first cycle.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from base_background_loop import BaseBackgroundLoop, LoopDeps
from events import EventBus
from tests.helpers import ConfigFactory


class _RecordingLoop(BaseBackgroundLoop):
    def __init__(self, *, events: list, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._events = events

    async def _do_work(self) -> dict[str, Any] | None:
        self._events.append("work")
        return {"ok": True}

    def _get_default_interval(self) -> int:
        return 3600


def _build(tmp_path: Path, events: list) -> tuple[_RecordingLoop, asyncio.Event]:
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    stop_event = asyncio.Event()

    async def recording_sleep(_seconds: int | float) -> None:
        events.append("sleep")
        # End the loop after its first sleep so run() returns deterministically.
        stop_event.set()
        await asyncio.sleep(0)

    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _name: True,
        sleep_fn=recording_sleep,
    )
    loop = _RecordingLoop(
        events=events,
        worker_name="test_worker",
        config=config,
        deps=deps,
        run_on_startup=False,
    )
    return loop, stop_event


def _write_marker(loop: _RecordingLoop, when: datetime) -> None:
    marker = loop._config.data_root / "memory" / f".{loop._worker_name}_last_run"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(when.isoformat())


@pytest.mark.asyncio
async def test_recent_last_run_defers_first_cycle_on_restart(tmp_path: Path) -> None:
    """Marker shows a run <interval ago → the first action is a deferral sleep,
    NOT an immediate cycle."""
    events: list = []
    loop, _stop = _build(tmp_path, events)
    _write_marker(loop, datetime.now(UTC))  # just ran → ~full interval remaining

    await loop.run()

    assert events, "loop took no action"
    assert events[0] == "sleep", (
        f"expected the loop to sleep out the remaining interval before its "
        f"first cycle on restart, but it ran a cycle immediately: {events}"
    )


@pytest.mark.asyncio
async def test_stale_last_run_runs_immediately(tmp_path: Path) -> None:
    """Marker older than the interval → a cycle WAS missed, so run immediately
    (catch-up). This guards against the fix over-correcting into never running."""
    events: list = []
    loop, _stop = _build(tmp_path, events)
    _write_marker(loop, datetime.now(UTC) - timedelta(hours=2))  # >1h interval

    await loop.run()

    assert events and events[0] == "work", (
        f"a loop overdue past its interval must catch up immediately, got {events}"
    )


@pytest.mark.asyncio
async def test_no_marker_runs_immediately(tmp_path: Path) -> None:
    """First-ever boot (no marker) → run immediately; nothing to defer to."""
    events: list = []
    loop, _stop = _build(tmp_path, events)

    await loop.run()

    assert events and events[0] == "work", (
        f"first boot with no history must run immediately, got {events}"
    )
