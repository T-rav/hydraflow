"""Regression test for issue #6360.

Bug: ``orchestrator._deferred_pipeline_start`` swallows all exceptions.
When deferred repo initialization fails, ``_pipeline_enabled`` stays ``True``
and ``_current_session`` stays ``None``, leaving the pipeline in a silently
broken state with no retry and no health signal.

This test calls ``_deferred_pipeline_start`` directly with a failing
``sanitize_repo`` and asserts that the orchestrator does NOT remain in the
inconsistent state (pipeline_enabled=True, current_session=None).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from events import EventBus
from orchestrator import HydraFlowOrchestrator

if TYPE_CHECKING:
    from config import HydraFlowConfig


class TestDeferredPipelineStartSwallowsErrors:
    """Issue #6360: _deferred_pipeline_start must not silently swallow errors."""

    @pytest.mark.asyncio
    async def test_pipeline_enabled_reverts_on_init_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """When _deferred_pipeline_start fails, pipeline_enabled must revert to False.

        Currently the bug causes _pipeline_enabled to stay True even though
        no session was started and the repo was never initialized.
        """
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus, pipeline_enabled=False)
        # Simulate the orchestrator being in a running state so the setter fires
        orch._running = True

        # Make sanitize_repo blow up — this is the first call in _deferred_pipeline_start
        orch._svc.workspaces.sanitize_repo = AsyncMock(
            side_effect=RuntimeError("repo init failed")
        )

        # Toggle pipeline on — this creates a background task for _deferred_pipeline_start
        orch.pipeline_enabled = True

        # Let the background task run
        await asyncio.sleep(0.05)

        # BUG: pipeline_enabled stays True even though init failed.
        # The fix should either revert it to False or retry.
        assert not orch.pipeline_enabled, (
            "pipeline_enabled must revert to False when _deferred_pipeline_start fails, "
            "but it stayed True — the pipeline is in a silently broken state (issue #6360)"
        )

    @pytest.mark.asyncio
    async def test_inconsistent_state_after_failed_deferred_start(
        self, config: HydraFlowConfig
    ) -> None:
        """After a failed _deferred_pipeline_start, pipeline is enabled but session is None.

        A correct implementation would either revert pipeline_enabled to False
        or successfully start a session. The bug leaves both in an inconsistent state.
        """
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus, pipeline_enabled=False)
        orch._running = True

        # Enable the pipeline so _pipeline_enabled becomes True
        orch._pipeline_enabled = True

        orch._svc.workspaces.sanitize_repo = AsyncMock(
            side_effect=RuntimeError("repo init failed")
        )

        # Call directly to avoid background-task timing issues
        await orch._deferred_pipeline_start()

        has_session = orch._current_session is not None
        is_enabled = orch._pipeline_enabled

        # At least one of these must hold for the pipeline to be in a consistent state:
        # 1) pipeline is disabled (failed init reverted the toggle), OR
        # 2) a session was successfully started
        assert has_session or not is_enabled, (
            f"Inconsistent state: pipeline_enabled={is_enabled}, "
            f"current_session={'set' if has_session else 'None'}. "
            "A failed _deferred_pipeline_start must not leave the pipeline "
            "enabled without a session (issue #6360)"
        )

    @pytest.mark.asyncio
    async def test_no_error_event_emitted_on_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """No SYSTEM_ALERT or error event is emitted when deferred start fails.

        The acceptance criteria require the failure to be surfaced in the
        dashboard. Currently it is only logged.
        """
        from events import EventType

        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus, pipeline_enabled=False)
        orch._running = True

        orch._svc.workspaces.sanitize_repo = AsyncMock(
            side_effect=RuntimeError("repo init failed")
        )

        await orch._deferred_pipeline_start()

        history = bus.get_history()
        alert_events = [
            e
            for e in history
            if e.type in (EventType.SYSTEM_ALERT, EventType.ERROR)
        ]

        # BUG: no alert event is published — the failure is silently logged.
        assert len(alert_events) > 0, (
            "Expected a SYSTEM_ALERT or ERROR event after _deferred_pipeline_start "
            "failure, but none was emitted — the dashboard has no way to show the "
            "error state (issue #6360)"
        )
