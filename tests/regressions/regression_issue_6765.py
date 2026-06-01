"""Regression test for issue #6765.

Bug: ``_deferred_pipeline_start`` has a bare ``except Exception`` at line 212
that swallows ``AuthenticationError`` and ``CreditExhaustedError``.  These are
fatal signals the rest of the codebase explicitly re-raises; catching them here
means the orchestrator silently continues with an uninitialised pipeline when
deferred startup hits an auth or credit failure.

The test calls ``_deferred_pipeline_start`` directly with mocked services that
raise each fatal error and asserts that the error propagates instead of being
swallowed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from events import EventBus
from orchestrator import HydraFlowOrchestrator
from subprocess_util import AuthenticationError, CreditExhaustedError

if TYPE_CHECKING:
    from config import HydraFlowConfig


class TestDeferredPipelineStartSwallowsFatalErrors:
    """Issue #6765: AuthenticationError and CreditExhaustedError must not be swallowed."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6765 — fix not yet landed", strict=False)
    async def test_authentication_error_propagates(
        self, config: HydraFlowConfig
    ) -> None:
        """AuthenticationError raised during deferred start must not be caught.

        Currently the bare ``except Exception`` at line 212 swallows this,
        leaving the pipeline in a silently broken state.
        """
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus, pipeline_enabled=False)
        orch._running = True
        orch._pipeline_enabled = True

        orch._svc.workspaces.sanitize_repo = AsyncMock(
            side_effect=AuthenticationError("bad credentials")
        )

        with pytest.raises(AuthenticationError, match="bad credentials"):
            await orch._deferred_pipeline_start()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6765 — fix not yet landed", strict=False)
    async def test_credit_exhausted_error_propagates(
        self, config: HydraFlowConfig
    ) -> None:
        """CreditExhaustedError raised during deferred start must not be caught.

        Currently the bare ``except Exception`` at line 212 swallows this,
        leaving the pipeline in a silently broken state.
        """
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus, pipeline_enabled=False)
        orch._running = True
        orch._pipeline_enabled = True

        orch._svc.workspaces.sanitize_repo = AsyncMock(
            side_effect=CreditExhaustedError("credits exhausted")
        )

        with pytest.raises(CreditExhaustedError, match="credits exhausted"):
            await orch._deferred_pipeline_start()

    @pytest.mark.asyncio
    async def test_non_fatal_error_still_suppressed(
        self, config: HydraFlowConfig
    ) -> None:
        """Non-fatal errors (e.g. network hiccups) should still be logged and suppressed.

        This verifies we don't over-correct: only fatal errors should propagate.
        """
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus, pipeline_enabled=False)
        orch._running = True
        orch._pipeline_enabled = True

        orch._svc.workspaces.sanitize_repo = AsyncMock(
            side_effect=RuntimeError("transient network error")
        )

        # Should NOT raise — non-fatal errors are still caught and logged
        await orch._deferred_pipeline_start()
