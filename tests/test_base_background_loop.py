"""Tests for the BaseBackgroundLoop ABC."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_background_loop import BaseBackgroundLoop
from events import EventBus, EventType, HydraFlowEvent
from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.helpers import ConfigFactory


class _StubLoop(BaseBackgroundLoop):
    """Concrete subclass for testing the base class."""

    def __init__(
        self,
        *,
        work_fn: Any = None,
        default_interval: int = 60,
        signal_types: frozenset[EventType] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._work_fn = work_fn or (lambda: {"stub": True})
        self._default_interval = default_interval
        self._declared_signal_types = signal_types or frozenset()

    async def _do_work(self) -> dict[str, Any] | None:
        result = self._work_fn()
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _get_default_interval(self) -> int:
        return self._default_interval

    def _signal_types(self) -> frozenset[EventType]:
        return self._declared_signal_types


def _make_stub(
    tmp_path: Path,
    *,
    enabled: bool = True,
    work_fn: Any = None,
    default_interval: int = 60,
    interval_cb: Any = None,
    run_on_startup: bool = False,
    signal_types: frozenset[EventType] | None = None,
    min_cooldown: int = 30,
    bus: EventBus | None = None,
) -> tuple[_StubLoop, asyncio.Event]:
    """Build a _StubLoop with test-friendly defaults."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    if bus is None:
        bus = EventBus()
    stop_event = asyncio.Event()

    call_count = 0

    async def instant_sleep(_seconds: int | float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        await asyncio.sleep(0)

    loop = _StubLoop(
        work_fn=work_fn,
        default_interval=default_interval,
        signal_types=signal_types,
        worker_name="test_worker",
        config=config,
        bus=bus,
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _name: enabled,
        sleep_fn=instant_sleep,
        interval_cb=interval_cb,
        run_on_startup=run_on_startup,
        min_cooldown=min_cooldown,
    )
    return loop, stop_event


class TestBaseBackgroundLoopRun:
    """Tests for the base run loop mechanics."""

    @pytest.mark.asyncio
    async def test_run__calls_do_work_and_reports_success(self, tmp_path: Path) -> None:
        """The loop calls _do_work and reports success via status_cb and bus."""
        loop, _stop = _make_stub(tmp_path, work_fn=lambda: {"count": 5})

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "test_worker"
        assert args[1] == "ok"
        assert args[2] == {"count": 5}

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        assert events[0].data["worker"] == "test_worker"
        assert events[0].data["status"] == "ok"
        assert events[0].data["details"] == {"count": 5}

    @pytest.mark.asyncio
    async def test_run__handles_error_and_publishes_events(
        self, tmp_path: Path
    ) -> None:
        """The loop handles errors, calls status_cb with 'error', and publishes events."""
        loop, _stop = _make_stub(
            tmp_path, work_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        )

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "test_worker"
        assert args[1] == "error"

        history = loop._bus.get_history()
        worker_events = [
            e for e in history if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        error_events = [e for e in history if e.type == EventType.ERROR]

        assert len(worker_events) >= 1
        assert worker_events[0].data["status"] == "error"
        assert len(error_events) >= 1
        assert error_events[0].data["source"] == "test_worker"

    @pytest.mark.asyncio
    async def test_run__skips_when_disabled(self, tmp_path: Path) -> None:
        """The loop skips work when the enabled callback returns False."""
        loop, _stop = _make_stub(tmp_path, enabled=False)

        await loop.run()

        loop._status_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_run__continues_after_error(self, tmp_path: Path) -> None:
        """The loop survives exceptions and retries on the next cycle."""
        call_count = 0

        def fail_then_succeed() -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient")
            return {"ok": True}

        loop, _stop = _make_stub(tmp_path, work_fn=fail_then_succeed)

        await loop.run()

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_run__reraises_authentication_error(self, tmp_path: Path) -> None:
        """AuthenticationError is re-raised and not caught by the generic handler."""

        def raise_auth() -> None:
            raise AuthenticationError("bad token")

        loop, _stop = _make_stub(tmp_path, work_fn=raise_auth)

        with pytest.raises(AuthenticationError, match="bad token"):
            await loop.run()

    @pytest.mark.asyncio
    async def test_run__reraises_credit_exhausted_error(self, tmp_path: Path) -> None:
        """CreditExhaustedError is re-raised and not caught by the generic handler."""

        def raise_credit() -> None:
            raise CreditExhaustedError("no credits")

        loop, _stop = _make_stub(tmp_path, work_fn=raise_credit)

        with pytest.raises(CreditExhaustedError, match="no credits"):
            await loop.run()

    @pytest.mark.asyncio
    async def test_run__do_work_returning_none_uses_empty_details(
        self, tmp_path: Path
    ) -> None:
        """When _do_work returns None, the event details default to {}."""
        loop, _stop = _make_stub(tmp_path, work_fn=lambda: None)

        await loop.run()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert events[0].data["details"] == {}


class TestBaseBackgroundLoopInterval:
    """Tests for interval handling."""

    def test_get_interval__uses_default_interval(self, tmp_path: Path) -> None:
        """Without a callback, _get_interval returns _get_default_interval()."""
        loop, _ = _make_stub(tmp_path, default_interval=300)
        assert loop._get_interval() == 300

    def test_get_interval__prefers_callback(self, tmp_path: Path) -> None:
        """With a callback, _get_interval uses the callback result."""
        loop, _ = _make_stub(
            tmp_path, default_interval=300, interval_cb=lambda _name: 42
        )
        assert loop._get_interval() == 42


class TestBaseBackgroundLoopRunOnStartup:
    """Tests for the run_on_startup flag."""

    @pytest.mark.asyncio
    async def test_run__run_on_startup_executes_immediately(
        self, tmp_path: Path
    ) -> None:
        """With run_on_startup=True, _do_work is called before the first sleep."""
        loop, stop = _make_stub(tmp_path, run_on_startup=True)
        # Stop immediately so only the startup execution runs
        stop.set()

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "test_worker"
        assert args[1] == "ok"

    @pytest.mark.asyncio
    async def test_run__run_on_startup_skips_disabled_in_loop_body(
        self, tmp_path: Path
    ) -> None:
        """With run_on_startup=True and disabled, initial run still executes."""
        call_count = 0

        def counting_work() -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"n": call_count}

        loop, _stop = _make_stub(
            tmp_path, enabled=False, run_on_startup=True, work_fn=counting_work
        )

        await loop.run()

        # Initial startup execution always runs; loop body skipped when disabled
        assert call_count == 1


class TestSignalTypes:
    """Tests for _signal_types declaration."""

    def test_default_signal_types_is_empty(self, tmp_path: Path) -> None:
        """Without override, _signal_types returns empty frozenset."""
        loop, _ = _make_stub(tmp_path)
        assert loop._signal_types() == frozenset()

    def test_signal_types_returns_declared_types(self, tmp_path: Path) -> None:
        """Subclass-declared signal types are returned."""
        signals = frozenset({EventType.MERGE_UPDATE, EventType.SESSION_END})
        loop, _ = _make_stub(tmp_path, signal_types=signals)
        assert loop._signal_types() == signals


class TestTriggerAndCooldown:
    """Tests for the trigger mechanism and cooldown enforcement."""

    def test_trigger_sets_event(self, tmp_path: Path) -> None:
        """_trigger() sets the internal asyncio.Event."""
        loop, _ = _make_stub(tmp_path)
        assert not loop._trigger_event.is_set()
        loop._trigger()
        assert loop._trigger_event.is_set()

    def test_cooldown_after_fresh_init(self, tmp_path: Path) -> None:
        """After init, cooldown has already expired (last_run_mono is 0)."""
        loop, _ = _make_stub(tmp_path, min_cooldown=30)
        assert loop._seconds_until_cooldown_expires() == 0.0

    def test_cooldown_after_cycle(self, tmp_path: Path) -> None:
        """After setting _last_run_mono to now, cooldown is close to min_cooldown."""
        import time

        loop, _ = _make_stub(tmp_path, min_cooldown=60)
        loop._last_run_mono = time.monotonic()
        remaining = loop._seconds_until_cooldown_expires()
        assert 59 <= remaining <= 60

    @pytest.mark.asyncio
    async def test_interruptible_sleep_returns_false_on_timeout(
        self, tmp_path: Path
    ) -> None:
        """When no signal arrives, _interruptible_sleep returns False."""
        loop, _ = _make_stub(tmp_path)
        result = await loop._interruptible_sleep(0.01)
        assert result is False

    @pytest.mark.asyncio
    async def test_interruptible_sleep_returns_true_on_trigger(
        self, tmp_path: Path
    ) -> None:
        """When triggered, _interruptible_sleep returns True early."""
        loop, _ = _make_stub(tmp_path)

        async def trigger_soon() -> None:
            await asyncio.sleep(0.01)
            loop._trigger()

        asyncio.create_task(trigger_soon())
        result = await loop._interruptible_sleep(5.0)
        assert result is True


class TestSignalListenerIntegration:
    """Integration tests for the signal listener + main loop."""

    @pytest.mark.asyncio
    async def test_signal_triggers_early_execution(self, tmp_path: Path) -> None:
        """Publishing a matching event triggers a work cycle before the timer expires."""
        bus = EventBus()
        work_calls: list[int] = []

        def tracking_work() -> dict[str, Any]:
            work_calls.append(1)
            return {"n": len(work_calls)}

        loop, stop = _make_stub(
            tmp_path,
            work_fn=tracking_work,
            signal_types=frozenset({EventType.MERGE_UPDATE}),
            min_cooldown=0,
            default_interval=3600,  # very long timer
            bus=bus,
        )

        async def publish_and_stop() -> None:
            await asyncio.sleep(0.05)
            await bus.publish(
                HydraFlowEvent(type=EventType.MERGE_UPDATE, data={})
            )
            # Give the loop time to react, then stop
            await asyncio.sleep(0.1)
            stop.set()
            loop._trigger()  # Wake from any remaining sleep

        asyncio.create_task(publish_and_stop())
        await asyncio.wait_for(loop.run(), timeout=5.0)

        assert len(work_calls) >= 1

    @pytest.mark.asyncio
    async def test_non_matching_signal_does_not_trigger(
        self, tmp_path: Path
    ) -> None:
        """Publishing a non-matching event does not trigger early execution."""
        bus = EventBus()
        work_calls: list[int] = []

        def tracking_work() -> dict[str, Any]:
            work_calls.append(1)
            return {"n": len(work_calls)}

        loop, stop = _make_stub(
            tmp_path,
            work_fn=tracking_work,
            signal_types=frozenset({EventType.MERGE_UPDATE}),
            min_cooldown=0,
            default_interval=3600,
            bus=bus,
        )

        async def publish_wrong_and_stop() -> None:
            await asyncio.sleep(0.05)
            # Publish a non-matching event type
            await bus.publish(
                HydraFlowEvent(type=EventType.PHASE_CHANGE, data={})
            )
            await asyncio.sleep(0.1)
            stop.set()
            loop._trigger()  # Wake from sleep to allow exit

        asyncio.create_task(publish_wrong_and_stop())
        await asyncio.wait_for(loop.run(), timeout=5.0)

        # Work should not have been called since the timer is 3600s
        # and only a non-matching event was published
        assert len(work_calls) == 0

    @pytest.mark.asyncio
    async def test_listener_task_is_cleaned_up_on_stop(
        self, tmp_path: Path
    ) -> None:
        """The signal listener task is cancelled when run() exits."""
        bus = EventBus()
        loop, stop = _make_stub(
            tmp_path,
            signal_types=frozenset({EventType.MERGE_UPDATE}),
            min_cooldown=0,
            default_interval=3600,
            bus=bus,
        )

        stop.set()
        loop._trigger()  # Ensure immediate exit

        await asyncio.wait_for(loop.run(), timeout=2.0)
        # No hanging tasks — if we get here, cleanup succeeded

    @pytest.mark.asyncio
    async def test_execute_cycle_updates_last_run_mono(
        self, tmp_path: Path
    ) -> None:
        """_execute_cycle sets _last_run_mono for cooldown tracking."""
        loop, _ = _make_stub(tmp_path)
        assert loop._last_run_mono == 0.0

        await loop._execute_cycle()

        assert loop._last_run_mono > 0.0
