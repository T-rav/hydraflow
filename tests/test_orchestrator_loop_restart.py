"""Tests for Orchestrator.restart_loop_task — the stalled-loop restart verb.

A silently-stalled loop task never completes, so ``_supervise_loops`` never
sees it (its ``asyncio.wait`` only wakes on task completion). The restart
verb cancels the stalled task and replaces it from the retained factory;
the supervisor must tolerate the externally-cancelled old task draining
through its done-set without raising ``CancelledError``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

if TYPE_CHECKING:
    from config import HydraFlowConfig
from orchestrator import HydraFlowOrchestrator
from tests.helpers import mock_fetcher_noop


class TestRestartLoopTask:
    @pytest.mark.asyncio
    async def test_unknown_name_returns_false(self, config: HydraFlowConfig) -> None:
        """Unknown loop names (or pre-supervision calls) are a no-op False."""
        orch = HydraFlowOrchestrator(config)
        assert await orch.restart_loop_task("no-such-loop") is False

    @pytest.mark.asyncio
    async def test_cancels_stalled_task_and_replaces_it(
        self, config: HydraFlowConfig
    ) -> None:
        """The old task is cancelled and a fresh one from the factory
        takes its slot in _loop_tasks."""
        orch = HydraFlowOrchestrator(config)
        started = asyncio.Event()

        async def stuck_loop() -> None:
            started.set()
            await asyncio.Event().wait()  # silent stall — never returns

        orch._loop_factories = {"stuck": stuck_loop}
        old = asyncio.create_task(stuck_loop(), name="hydraflow-stuck")
        orch._loop_tasks = {"stuck": old}
        await started.wait()

        try:
            assert await orch.restart_loop_task("stuck") is True
            await asyncio.gather(old, return_exceptions=True)
            assert old.cancelled()
            replacement = orch._loop_tasks["stuck"]
            assert replacement is not old
            assert not replacement.done()
        finally:
            for task in orch._loop_tasks.values():
                task.cancel()
            await asyncio.gather(*orch._loop_tasks.values(), return_exceptions=True)

    @pytest.mark.asyncio
    async def test_missing_factory_returns_false(self, config: HydraFlowConfig) -> None:
        """A task without a retained factory cannot be restarted."""
        orch = HydraFlowOrchestrator(config)

        async def stuck_loop() -> None:
            await asyncio.Event().wait()

        old = asyncio.create_task(stuck_loop(), name="hydraflow-stuck")
        orch._loop_tasks = {"stuck": old}
        orch._loop_factories = {}
        try:
            assert await orch.restart_loop_task("stuck") is False
            assert not old.cancelled()
        finally:
            old.cancel()
            await asyncio.gather(old, return_exceptions=True)


class TestRestartDoesNotDrainOldTask:
    @pytest.mark.asyncio
    async def test_restart_returns_without_awaiting_slow_cancellation(
        self, config: HydraFlowConfig
    ) -> None:
        """restart_loop_task must NOT await the old task: that await would
        deliver (and suppress) the CALLER's own cancellation during a
        credit-pause shutdown, letting the staleness sweep escape its one
        cancel and spawn rogue loop tasks against an exhausted billing
        signal. The supervisor's identity check drains the old task."""
        orch = HydraFlowOrchestrator(config)
        release = asyncio.Event()

        async def stubborn_loop() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                await release.wait()  # slow cancellation drain

        orch._loop_factories = {"stubborn": stubborn_loop}
        old = asyncio.create_task(stubborn_loop(), name="hydraflow-stubborn")
        orch._loop_tasks = {"stubborn": old}
        await asyncio.sleep(0)
        try:
            result = await asyncio.wait_for(
                orch.restart_loop_task("stubborn"), timeout=1
            )
            assert result is True
            assert not old.done()  # still draining — restart didn't block
        finally:
            release.set()
            orch._loop_tasks["stubborn"].cancel()
            await asyncio.gather(
                old, orch._loop_tasks["stubborn"], return_exceptions=True
            )


class TestSupervisorExternalRestartHardening:
    @pytest.mark.asyncio
    async def test_supervisor_survives_external_restart(
        self, config: HydraFlowConfig
    ) -> None:
        """Restarting a stalled loop mid-supervision must not blow up
        _supervise_loops when the cancelled old task drains through its
        asyncio.wait done-set (Task.exception() raises CancelledError)."""
        orch = HydraFlowOrchestrator(config)
        orch._svc.prs.ensure_labels_exist = AsyncMock()  # type: ignore[method-assign]
        mock_fetcher_noop(orch)

        implement_calls = 0

        async def stalling_then_stopping() -> None:
            nonlocal implement_calls
            implement_calls += 1
            if implement_calls == 1:
                await asyncio.Event().wait()  # silent stall
                return
            # Post-restart invocation: wind the orchestrator down.
            orch._stop_event.set()

        orch._implement_loop = stalling_then_stopping  # type: ignore[method-assign]

        orch._svc.triager.triage_issues = AsyncMock(return_value=0)  # type: ignore[method-assign]
        orch._svc.planner_phase.plan_issues = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._svc.store.get_reviewable = lambda _max_count: []  # type: ignore[method-assign]
        orch._svc.store.start = AsyncMock()  # type: ignore[method-assign]

        async def instant_sleep(seconds: int) -> None:  # noqa: ARG001
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        run_task = asyncio.create_task(orch.run())
        try:
            # Wait for the implement loop to enter its stall.
            for _ in range(200):
                if implement_calls >= 1:
                    break
                await asyncio.sleep(0.01)
            assert implement_calls == 1

            assert await orch.restart_loop_task("implement") is True

            # The supervisor must keep running and supervise the
            # replacement task, whose second invocation stops the run.
            await asyncio.wait_for(run_task, timeout=10)
        finally:
            if not run_task.done():
                run_task.cancel()
                await asyncio.gather(run_task, return_exceptions=True)

        assert implement_calls == 2
