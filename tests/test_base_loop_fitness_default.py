from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from base_background_loop import BaseBackgroundLoop, LoopDeps
from loop_fitness import Confidence, FitnessContext, FitnessKind


class _Dummy(BaseBackgroundLoop):
    def _get_default_interval(self) -> int:
        return 60

    async def _do_work(self):
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        return {"ok": True}


def _deps() -> LoopDeps:
    from unittest.mock import AsyncMock, MagicMock

    return LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=AsyncMock(),
    )


def test_default_loop_fitness_is_housekeeping() -> None:
    from unittest.mock import MagicMock

    loop = _Dummy(worker_name="dummy", config=MagicMock(), deps=_deps())
    ctx = FitnessContext(
        window_start=datetime(2026, 6, 1, tzinfo=UTC),
        window_end=datetime(2026, 6, 30, tzinfo=UTC),
    )
    fit = loop.loop_fitness(ctx)
    assert fit.kind is FitnessKind.HOUSEKEEPING
    assert fit.score is None
    assert fit.confidence is Confidence.INSUFFICIENT_DATA
    assert fit.worker_name == "dummy"
    assert fit.timestamp == ctx.window_end
