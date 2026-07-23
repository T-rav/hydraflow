"""Regression test for issue #10312.

``run_refilling_pool`` (``src/phase_utils.py``) grew an opt-in
``poll_interval`` kwarg in #10296/#10327: when set to a positive number of
seconds the pool wakes at least that often to re-run ``supply_fn`` into free
slots, so an item enqueued mid-run is dispatched into a free slot without
waiting for a long in-flight task to complete. That fix was wired ONLY at the
plan callsite (``src/plan_phase.py``).

The triage (``src/triage_phase.py``) and implement (``src/implement_phase.py``)
callsites shared the identical gap: they re-polled ``supply_fn`` only on task
completion, so an item enqueued mid-run while a long triage/implement worker
held a slot waited for completion even with free slots.

The behavioral guarantee — that a positive ``poll_interval`` dispatches a
mid-run enqueue into a free slot before the in-flight task completes — is
already proven directly against ``run_refilling_pool`` in
``tests/test_phase_utils.py`` and ``tests/regressions/regression_issue_10296.py``.
What remained unproven for #10312 is the *callsite wiring*: that triage and
implement now opt in by passing ``poll_interval`` bounded by their loop's
``poll_interval`` (mirroring the plan callsite).

These tests are RED before the wiring lands (the callsite passes no
``poll_interval``, so the captured kwarg is absent) and GREEN after.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import implement_phase
import triage_phase
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory, make_implement_phase, make_triage_phase

_ISSUE = TaskFactory.create(id=1, title="Implement feature X", body="A" * 100)


class TestMidRunRefillWiredAtTriageAndImplementCallsites:
    """Triage and implement pools must opt in to mid-run refill (#10312)."""

    @pytest.mark.asyncio
    async def test_triage_callsite_passes_poll_interval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``TriagePhase.triage_issues`` opts in to mid-run refill, bounded by
        the loop ``poll_interval`` (mirrors the plan callsite)."""
        config = ConfigFactory.create()
        phase, _state, _triage, _prs, _store, _stop = make_triage_phase(config)

        spy = AsyncMock(return_value=[])
        monkeypatch.setattr(triage_phase, "run_refilling_pool", spy)

        await phase.triage_issues()

        assert spy.await_args is not None, "run_refilling_pool was not called"
        kwargs = spy.await_args.kwargs
        assert "poll_interval" in kwargs, (
            "triage callsite did not opt in to mid-run refill — "
            "run_refilling_pool called without poll_interval"
        )
        assert kwargs["poll_interval"] == config.poll_interval

    @pytest.mark.asyncio
    async def test_implement_callsite_passes_poll_interval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ImplementPhase.run_batch`` opts in to mid-run refill, bounded by
        the loop ``poll_interval`` (mirrors the plan callsite)."""
        config = ConfigFactory.create()
        phase, _mock_wt, _mock_prs = make_implement_phase(config, [_ISSUE])

        spy = AsyncMock(return_value=[])
        monkeypatch.setattr(implement_phase, "run_refilling_pool", spy)

        await phase.run_batch([_ISSUE])

        assert spy.await_args is not None, "run_refilling_pool was not called"
        kwargs = spy.await_args.kwargs
        assert "poll_interval" in kwargs, (
            "implement callsite did not opt in to mid-run refill — "
            "run_refilling_pool called without poll_interval"
        )
        assert kwargs["poll_interval"] == config.poll_interval
