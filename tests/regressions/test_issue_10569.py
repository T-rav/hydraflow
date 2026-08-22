"""Regression tests for issue #10569 — orchestrator wedges in "stopping".

During the #10558 incident the orchestrator ended up permanently in
``status: "stopping"`` after loops crash-restarted repeatedly against an
exhausted weekly limit while a ``stop()`` was in flight.

Root cause: the loop-restart paths (`_restart_loop`, `restart_loop_task`, and
`_resume_loops_after_credit_pause`) call ``asyncio.create_task`` with **no
``_stop_event`` guard**. A restart that lands after ``stop()``'s one-shot
cancel sweep spawns a fresh, live loop task that outlives
``_supervise_loops``'s cancel/gather drain. That orphan keeps running (holding
a subprocess), so ``_has_active_processes()`` stays ``True`` and — with
``_stop_event`` set — ``run_status`` is pinned at ``"stopping"`` forever.

The "refused credit pause" path is the exact trigger from the incident: a
prose-scanned (non-authoritative) ``CreditExhaustedError`` is refuted by the
live probe (``_pause_for_credits`` returns ``False``), so
``_handle_credit_exhaustion`` restarts the crashed loop via ``_restart_loop``
— and if ``stop()`` has already been requested, that restart leaks a rogue
loop.

The fix gates every restart path on ``_stop_event``: once shutdown has begun,
no new loop task is created. The #10558 authoritative-vs-prose pause decision
in ``_pause_for_credits`` is untouched — the gate only concerns whether a loop
is *recreated after stop*, never whether a genuine credit signal pauses.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from orchestrator import HydraFlowOrchestrator
from subprocess_util import CreditExhaustedError

if TYPE_CHECKING:
    from config import HydraFlowConfig


@pytest.mark.asyncio
async def test_refused_credit_pause_after_stop_does_not_wedge_stopping(
    config: HydraFlowConfig,
) -> None:
    """A refused credit pause that lands after stop must not pin "stopping".

    Reproduces the #10558 interleaving: a non-authoritative credit signal is
    refuted by the probe (refused pause) while ``stop()`` is already in flight.
    Before the fix, ``_handle_credit_exhaustion`` recreated the crashed loop via
    ``_restart_loop``; the orphan held a "subprocess" so ``run_status`` stayed
    ``"stopping"``. After the fix, no loop is recreated once stop is requested
    and the status converges to a terminal, non-``"stopping"`` value.
    """
    # cooldown=0 so the refused-path restart (which the fix must suppress) would
    # run its factory body immediately rather than after a backoff delay —
    # making the wedge observable within the test without waiting. model_copy
    # bypasses the ``ge=10`` validator, matching the established test pattern.
    cfg = config.model_copy(update={"credit_fp_suppress_cooldown_seconds": 0})
    orch = HydraFlowOrchestrator(cfg)

    # Model an orphaned crash-loop that holds a live agent subprocess: while it
    # runs, the fleet reports active processes, which is what pins run_status at
    # "stopping" (stop requested + _has_active_processes() True).
    holding = {"live": False}
    orch._has_active_processes = lambda: holding["live"]  # type: ignore[method-assign]

    async def crash_loop() -> None:
        holding["live"] = True
        try:
            await asyncio.sleep(3600)  # orphan keeps running, holding the proc
        finally:
            holding["live"] = False

    tasks: dict[str, asyncio.Task[None]] = {}
    loop_factories = [("plan", crash_loop)]
    orch._loop_factories = dict(loop_factories)
    orch._loop_tasks = tasks

    # Probe returns True → the (weekly-limit-style) signal is refuted as a false
    # positive → _pause_for_credits returns False → refused pause path.
    with patch(
        "orchestrator_credits.probe_credit_availability",
        AsyncMock(return_value=True),
    ):
        # Operator stop has already been requested (and run() is not active, so
        # _running is False — the wedge must therefore come from a leaked task).
        orch._stop_event.set()
        await orch._handle_credit_exhaustion(
            CreditExhaustedError("usage limit reached"),
            "plan",
            tasks,
            loop_factories,
        )
        # Let any (buggy) orphan task start and set the holding flag.
        for _ in range(10):
            await asyncio.sleep(0)

        try:
            assert orch.run_status != "stopping", (
                "orchestrator wedged in 'stopping': the refused credit pause "
                "recreated a loop after stop was requested (#10569)"
            )
            assert "plan" not in tasks, (
                "a rogue loop task was recreated after stop (#10569)"
            )
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_restart_loop_is_gated_once_stop_requested(
    config: HydraFlowConfig,
) -> None:
    """`_restart_loop` creates no new task once `_stop_event` is set."""
    orch = HydraFlowOrchestrator(config)

    async def factory() -> None:
        await asyncio.sleep(3600)

    tasks: dict[str, asyncio.Task[None]] = {}
    loop_factories = [("plan", factory)]
    orch._stop_event.set()

    await orch._restart_loop("plan", RuntimeError("boom"), tasks, loop_factories)

    assert "plan" not in tasks, "restart after stop must not spawn a loop task"


@pytest.mark.asyncio
async def test_restart_loop_still_restarts_before_stop(
    config: HydraFlowConfig,
) -> None:
    """Control: before stop, `_restart_loop` still recreates the crashed loop.

    Guards against over-tightening the gate — the legitimate crash-restart path
    (#9924) must keep working when no shutdown is in progress.
    """
    orch = HydraFlowOrchestrator(config)
    started = asyncio.Event()

    async def factory() -> None:
        started.set()
        await asyncio.sleep(3600)

    tasks: dict[str, asyncio.Task[None]] = {}
    loop_factories = [("plan", factory)]

    await orch._restart_loop("plan", RuntimeError("boom"), tasks, loop_factories)

    assert "plan" in tasks
    task = tasks["plan"]
    try:
        await asyncio.wait_for(started.wait(), timeout=2.0)
        assert not task.done()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_restart_loop_task_is_gated_after_stop(
    config: HydraFlowConfig,
) -> None:
    """`restart_loop_task` returns False and replaces nothing once stop is set."""
    orch = HydraFlowOrchestrator(config)

    async def factory() -> None:
        await asyncio.sleep(3600)

    old = asyncio.create_task(factory(), name="hydraflow-plan")
    orch._loop_tasks = {"plan": old}
    orch._loop_factories = {"plan": factory}
    orch._stop_event.set()

    try:
        assert await orch.restart_loop_task("plan") is False
        assert orch._loop_tasks["plan"] is old, "task must not be replaced"
        assert not old.cancelled(), "gate returns before cancelling the old task"
    finally:
        old.cancel()
        await asyncio.gather(old, return_exceptions=True)


@pytest.mark.asyncio
async def test_resume_after_credit_pause_is_gated_after_stop(
    config: HydraFlowConfig,
) -> None:
    """`_resume_loops_after_credit_pause` recreates no loops once stop is set.

    A credit pause that ends after stop was requested must clear its pause
    state but never spawn fresh loop tasks.
    """
    orch = HydraFlowOrchestrator(config)

    async def factory() -> None:
        await asyncio.sleep(3600)

    tasks: dict[str, asyncio.Task[None]] = {}
    loop_factories = [("plan", factory)]
    orch._credits_paused_until = datetime.now(UTC) + timedelta(hours=1)
    orch._credit_paused_provider = "anthropic"
    orch._stop_event.set()

    try:
        await orch._resume_loops_after_credit_pause(
            tasks, loop_factories, "plan", None
        )
        assert tasks == {}, "no loops may be recreated after stop"
        assert orch._credits_paused_until is None, "pause state must be cleared"
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
