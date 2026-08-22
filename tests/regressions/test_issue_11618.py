"""Regression test for issue #11618.

Bug: the concurrent worker pools classified "fatal" with a hand-rolled tuple —
``(AuthenticationError, CreditExhaustedError, MemoryError)`` — that omitted
``LIKELY_BUG_EXCEPTIONS``.  A ``TypeError``/``KeyError`` raised inside a pooled
worker was therefore logged at WARNING and dropped, while the identical
exception escalates off-pool through ``reraise_on_credit_or_bug``.  A malformed
tuple unpack or a ``KeyError`` parsing a ``gh`` payload was indistinguishable
from a transient failure and the cycle reported success.

Two sites carried the same shape:

* ``phase_utils._process_done_tasks`` — the shared refilling-pool helper.
* ``orchestrator._do_review_work`` — a hand-rolled inline copy of the policy.

After the fix both route through ``phase_utils.handle_pool_worker_exception``,
whose fatal predicate is ``exception_classify.is_fatal`` — the same set
``reraise_on_credit_or_bug`` enforces, plus ``MemoryError``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.conftest import TaskFactory

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from models import Task


async def _never() -> int:
    """A worker that never finishes — stands in for a live sibling task."""
    await asyncio.sleep(100)
    return 1


async def _failed_task(exc: BaseException) -> asyncio.Task[int]:
    """Return an already-completed task that raised *exc*."""

    async def _raise() -> int:
        raise exc

    task: asyncio.Task[int] = asyncio.create_task(_raise())
    await asyncio.sleep(0)  # let it run to failure
    return task


class TestRefillingPoolPropagatesLikelyBugs:
    """``phase_utils._process_done_tasks`` must not swallow a code bug."""

    @pytest.mark.asyncio
    async def test_type_error_in_pooled_worker_propagates(self) -> None:
        from phase_utils import _process_done_tasks

        failed = await _failed_task(TypeError("unpack of non-sequence"))
        pending: dict[asyncio.Task[int], int] = {failed: 0}

        with pytest.raises(TypeError):
            await _process_done_tasks({failed}, pending, [])

    @pytest.mark.asyncio
    async def test_key_error_in_pooled_worker_propagates(self) -> None:
        from phase_utils import _process_done_tasks

        failed = await _failed_task(KeyError("headRefName"))
        pending: dict[asyncio.Task[int], int] = {failed: 0}

        with pytest.raises(KeyError):
            await _process_done_tasks({failed}, pending, [])

    @pytest.mark.asyncio
    async def test_likely_bug_cancels_sibling_workers(self) -> None:
        """The widened set must take the same cancel path as the old one."""
        from phase_utils import _process_done_tasks

        failed = await _failed_task(TypeError("unpack of non-sequence"))
        sibling: asyncio.Task[int] = asyncio.create_task(_never())
        pending: dict[asyncio.Task[int], int] = {failed: 0, sibling: 1}

        with pytest.raises(TypeError):
            await _process_done_tasks({failed}, pending, [])

        assert sibling.cancelled()

    @pytest.mark.asyncio
    async def test_transient_failure_still_lets_the_batch_finish(self) -> None:
        """A non-fatal exception is absorbed; sibling results still collect."""
        from phase_utils import _process_done_tasks

        async def ok() -> int:
            return 7

        failed = await _failed_task(RuntimeError("gh timed out"))
        succeeded: asyncio.Task[int] = asyncio.create_task(ok())
        await asyncio.sleep(0)
        pending: dict[asyncio.Task[int], int] = {failed: 0, succeeded: 1}
        results: list[int] = []

        await _process_done_tasks({failed, succeeded}, pending, results)

        assert results == [7]

    @pytest.mark.asyncio
    async def test_transient_failure_is_recorded_at_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The absorbed failure leaves an audit trail rather than vanishing."""
        from phase_utils import _process_done_tasks

        failed = await _failed_task(RuntimeError("gh timed out"))
        pending: dict[asyncio.Task[int], int] = {failed: 0}

        with caplog.at_level(logging.WARNING, logger="hydraflow.phase_utils"):
            await _process_done_tasks({failed}, pending, [])

        assert "gh timed out" in caplog.text

    @pytest.mark.asyncio
    async def test_credit_exhausted_error_still_propagates(self) -> None:
        """Pre-existing fatal behaviour is unchanged by the widening."""
        from phase_utils import _process_done_tasks
        from subprocess_util import CreditExhaustedError

        failed = await _failed_task(CreditExhaustedError("no credits"))
        pending: dict[asyncio.Task[int], int] = {failed: 0}

        with pytest.raises(CreditExhaustedError):
            await _process_done_tasks({failed}, pending, [])

    @pytest.mark.asyncio
    async def test_authentication_error_still_propagates(self) -> None:
        """Pre-existing fatal behaviour is unchanged by the widening."""
        from phase_utils import _process_done_tasks
        from subprocess_util import AuthenticationError

        failed = await _failed_task(AuthenticationError("bad token"))
        pending: dict[asyncio.Task[int], int] = {failed: 0}

        with pytest.raises(AuthenticationError):
            await _process_done_tasks({failed}, pending, [])


def _review_orchestrator(config: HydraFlowConfig, task: Task):
    """Orchestrator whose review pool serves *task* once, then drains."""
    from orchestrator import HydraFlowOrchestrator

    orch = HydraFlowOrchestrator(config)
    served = False

    def get_reviewable_once(_max_count: int) -> list[Task]:
        nonlocal served
        if served:
            return []
        served = True
        return [task]

    orch._svc.store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]
    orch._svc.store.get_active_issues = lambda: {}  # type: ignore[method-assign]
    orch._svc.store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
    return orch


class TestReviewPoolPropagatesLikelyBugs:
    """``orchestrator._do_review_work`` must apply the same policy."""

    @pytest.mark.asyncio
    async def test_type_error_in_review_worker_propagates(
        self, config: HydraFlowConfig
    ) -> None:
        orch = _review_orchestrator(config, TaskFactory.create(id=42))
        orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            side_effect=TypeError("cannot unpack non-sequence")
        )

        with pytest.raises(TypeError):
            await orch._do_review_work()

    @pytest.mark.asyncio
    async def test_key_error_in_review_worker_propagates(
        self, config: HydraFlowConfig
    ) -> None:
        orch = _review_orchestrator(config, TaskFactory.create(id=43))
        orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            side_effect=KeyError("headRefName")
        )

        with pytest.raises(KeyError):
            await orch._do_review_work()

    @pytest.mark.asyncio
    async def test_transient_review_failure_is_still_absorbed(
        self, config: HydraFlowConfig
    ) -> None:
        """A non-fatal failure leaves the pool running and reports no work."""
        orch = _review_orchestrator(config, TaskFactory.create(id=44))
        orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("gh timed out")
        )

        assert await orch._do_review_work() is False

    @pytest.mark.asyncio
    async def test_credit_exhausted_error_still_propagates(
        self, config: HydraFlowConfig
    ) -> None:
        """Pre-existing fatal behaviour is unchanged by the widening."""
        from subprocess_util import CreditExhaustedError

        orch = _review_orchestrator(config, TaskFactory.create(id=45))
        orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            side_effect=CreditExhaustedError("no credits")
        )

        with pytest.raises(CreditExhaustedError):
            await orch._do_review_work()

    @pytest.mark.asyncio
    async def test_authentication_error_still_propagates(
        self, config: HydraFlowConfig
    ) -> None:
        """Pre-existing fatal behaviour is unchanged by the widening."""
        from subprocess_util import AuthenticationError

        orch = _review_orchestrator(config, TaskFactory.create(id=46))
        orch._svc.fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            side_effect=AuthenticationError("bad token")
        )

        with pytest.raises(AuthenticationError):
            await orch._do_review_work()
