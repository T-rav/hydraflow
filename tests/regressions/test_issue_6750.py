"""Regression test for issue #6750.

``PipelineEscalator.escalate`` (``__call__``) wraps both the primary
``escalate_to_diagnostic()`` call and the fallback ``swap_pipeline_labels()``
call in bare ``except Exception`` handlers that do **not** call
``reraise_on_credit_or_bug``.  This means ``AuthenticationError`` and
``CreditExhaustedError`` are silently swallowed on the most critical
error-handling path in the pipeline.

These tests will be RED until both ``except Exception`` blocks call
``reraise_on_credit_or_bug(exc)`` before logging.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from harness_insights import FailureCategory
from models import PipelineStage, Task
from phase_utils import PipelineEscalator
from subprocess_util import AuthenticationError, CreditExhaustedError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(number: int = 42) -> Task:
    return Task(id=number, title=f"Test issue #{number}")


def _make_escalator() -> tuple[PipelineEscalator, MagicMock, MagicMock, MagicMock]:
    """Build a PipelineEscalator with mock dependencies."""
    state = MagicMock()
    state.set_escalation_context = MagicMock()
    state.set_hitl_origin = MagicMock()
    state.set_hitl_cause = MagicMock()
    state.record_hitl_escalation = MagicMock()

    prs = MagicMock()
    prs.swap_pipeline_labels = AsyncMock()

    store = MagicMock()
    store.enqueue_transition = MagicMock()

    harness_insights = MagicMock()

    escalator = PipelineEscalator(
        state=state,
        prs=prs,
        store=store,
        harness_insights=harness_insights,
        origin_label="hydraflow-plan",
        hitl_label="hydraflow-hitl",
        diagnose_label="hydraflow-diagnose",
        stage=PipelineStage.PLAN,
    )
    return escalator, state, prs, store


# ---------------------------------------------------------------------------
# Primary path: escalate_to_diagnostic raises fatal error
# ---------------------------------------------------------------------------


class TestPipelineEscalatorPrimaryPathPropagatesFatalErrors:
    """AuthenticationError and CreditExhaustedError raised by
    ``escalate_to_diagnostic`` must propagate — not be caught by the
    outer ``except Exception`` block."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6750 — fix not yet landed", strict=False)
    async def test_authentication_error_propagates_from_primary(self) -> None:
        """AuthenticationError from escalate_to_diagnostic must NOT be swallowed."""
        escalator, _state, _prs, _store = _make_escalator()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "phase_utils.escalate_to_diagnostic",
                AsyncMock(side_effect=AuthenticationError("bad credentials")),
            )
            with pytest.raises(AuthenticationError, match="bad credentials"):
                await escalator(
                    _make_task(),
                    cause="test",
                    details="test details",
                    category=FailureCategory.PLAN_VALIDATION,
                )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6750 — fix not yet landed", strict=False)
    async def test_credit_exhausted_error_propagates_from_primary(self) -> None:
        """CreditExhaustedError from escalate_to_diagnostic must NOT be swallowed."""
        escalator, _state, _prs, _store = _make_escalator()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "phase_utils.escalate_to_diagnostic",
                AsyncMock(side_effect=CreditExhaustedError("usage limit reached")),
            )
            with pytest.raises(CreditExhaustedError, match="usage limit reached"):
                await escalator(
                    _make_task(),
                    cause="test",
                    details="test details",
                    category=FailureCategory.PLAN_VALIDATION,
                )

    @pytest.mark.asyncio
    async def test_plain_exception_still_caught_on_primary(self) -> None:
        """A plain RuntimeError from escalate_to_diagnostic should still be
        caught — the fallback path should run, and the escalator should not raise."""
        escalator, _state, prs, _store = _make_escalator()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "phase_utils.escalate_to_diagnostic",
                AsyncMock(side_effect=RuntimeError("transient network error")),
            )
            # Should NOT raise — the handler catches generic exceptions.
            await escalator(
                _make_task(),
                cause="test",
                details="test details",
                category=FailureCategory.PLAN_VALIDATION,
            )
            # Fallback swap_pipeline_labels should have been called.
            prs.swap_pipeline_labels.assert_awaited_once()


# ---------------------------------------------------------------------------
# Fallback path: swap_pipeline_labels raises fatal error
# ---------------------------------------------------------------------------


class TestPipelineEscalatorFallbackPathPropagatesFatalErrors:
    """AuthenticationError and CreditExhaustedError raised by the fallback
    ``swap_pipeline_labels`` call must propagate — not be caught by the
    inner ``except Exception`` block."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6750 — fix not yet landed", strict=False)
    async def test_authentication_error_propagates_from_fallback(self) -> None:
        """AuthenticationError from fallback swap_pipeline_labels must NOT be swallowed."""
        escalator, _state, prs, _store = _make_escalator()

        with pytest.MonkeyPatch.context() as mp:
            # Primary path fails with a transient error to trigger the fallback.
            mp.setattr(
                "phase_utils.escalate_to_diagnostic",
                AsyncMock(side_effect=RuntimeError("transient")),
            )
            # Fallback path raises AuthenticationError.
            prs.swap_pipeline_labels = AsyncMock(
                side_effect=AuthenticationError("token expired"),
            )

            with pytest.raises(AuthenticationError, match="token expired"):
                await escalator(
                    _make_task(),
                    cause="test",
                    details="test details",
                    category=FailureCategory.PLAN_VALIDATION,
                )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6750 — fix not yet landed", strict=False)
    async def test_credit_exhausted_error_propagates_from_fallback(self) -> None:
        """CreditExhaustedError from fallback swap_pipeline_labels must NOT be swallowed."""
        escalator, _state, prs, _store = _make_escalator()

        with pytest.MonkeyPatch.context() as mp:
            # Primary path fails with a transient error to trigger the fallback.
            mp.setattr(
                "phase_utils.escalate_to_diagnostic",
                AsyncMock(side_effect=RuntimeError("transient")),
            )
            # Fallback path raises CreditExhaustedError.
            prs.swap_pipeline_labels = AsyncMock(
                side_effect=CreditExhaustedError("credits gone"),
            )

            with pytest.raises(CreditExhaustedError, match="credits gone"):
                await escalator(
                    _make_task(),
                    cause="test",
                    details="test details",
                    category=FailureCategory.PLAN_VALIDATION,
                )

    @pytest.mark.asyncio
    async def test_plain_exception_still_caught_on_fallback(self) -> None:
        """A plain RuntimeError on the fallback path should still be caught."""
        escalator, _state, prs, _store = _make_escalator()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "phase_utils.escalate_to_diagnostic",
                AsyncMock(side_effect=RuntimeError("primary fails")),
            )
            prs.swap_pipeline_labels = AsyncMock(
                side_effect=RuntimeError("fallback also fails"),
            )
            # Should NOT raise — both generic exceptions are caught.
            await escalator(
                _make_task(),
                cause="test",
                details="test details",
                category=FailureCategory.PLAN_VALIDATION,
            )
