"""Regression test for issue #6536.

Bug: ``PipelineEscalator.__call__()`` calls ``enqueue_transition(issue,
"diagnose")`` unconditionally after both the primary (``escalate_to_diagnostic``)
and fallback (``swap_pipeline_labels``) escalation paths.  When **both** paths
raise, the transition is still enqueued, creating a phantom "diagnose" queue
entry for an issue that was never actually escalated.

Expected behaviour after fix:
  - ``enqueue_transition`` is only called when at least one escalation path
    succeeded.
  - ``record_harness_failure`` may remain unconditional (it records the
    pipeline failure, not the escalation outcome).

These tests assert the *correct* behaviour, so they are RED against the
current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from harness_insights import FailureCategory  # noqa: E402
from models import PipelineStage  # noqa: E402
from phase_utils import PipelineEscalator  # noqa: E402


def _make_escalator(
    *,
    state: MagicMock | None = None,
    prs: AsyncMock | None = None,
    store: MagicMock | None = None,
    harness_insights: MagicMock | None = None,
) -> PipelineEscalator:
    """Create a PipelineEscalator with mocked dependencies."""
    return PipelineEscalator(
        state=state or MagicMock(),
        prs=prs or AsyncMock(),
        store=store or MagicMock(),
        harness_insights=harness_insights,
        origin_label="hydraflow-plan",
        hitl_label="hydraflow-hitl",
        diagnose_label="hydraflow-diagnose",
        stage=PipelineStage.PLAN,
    )


class TestPhantomDiagnoseTransition:
    """Issue #6536 — enqueue_transition must not be called when both
    escalation paths fail.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6536 — fix not yet landed", strict=False)
    async def test_no_enqueue_when_both_escalation_paths_fail(self) -> None:
        """When ``escalate_to_diagnostic`` raises AND the fallback
        ``swap_pipeline_labels`` also raises, ``enqueue_transition``
        must NOT be called — there is nothing to transition.

        Currently FAILS (RED) because ``enqueue_transition`` is called
        unconditionally after both try/except blocks.
        """
        # Arrange
        store = MagicMock()
        prs = AsyncMock()
        prs.swap_pipeline_labels.side_effect = RuntimeError("label swap failed")
        escalator = _make_escalator(store=store, prs=prs)
        issue = MagicMock(id=42)

        # Make escalate_to_diagnostic raise so we fall into the except branch,
        # where swap_pipeline_labels (already configured to raise) is the fallback.
        with patch(
            "phase_utils.escalate_to_diagnostic",
            new_callable=AsyncMock,
            side_effect=RuntimeError("diagnostic escalation failed"),
        ):
            await escalator(
                issue,
                cause="plan failed",
                details="validation errors",
                category=FailureCategory.PLAN_VALIDATION,
            )

        # Assert — phantom transition must not be enqueued
        store.enqueue_transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_enqueue_called_when_primary_escalation_succeeds(self) -> None:
        """When ``escalate_to_diagnostic`` succeeds, ``enqueue_transition``
        should still be called.

        This test is GREEN on the current code and should remain GREEN
        after the fix — it documents the happy path.
        """
        # Arrange
        store = MagicMock()
        escalator = _make_escalator(store=store)
        issue = MagicMock(id=10)

        await escalator(
            issue,
            cause="plan failed",
            details="details",
            category=FailureCategory.PLAN_VALIDATION,
        )

        # Assert
        store.enqueue_transition.assert_called_once_with(issue, "diagnose")

    @pytest.mark.asyncio
    async def test_enqueue_called_when_fallback_swap_succeeds(self) -> None:
        """When ``escalate_to_diagnostic`` fails but the fallback
        ``swap_pipeline_labels`` succeeds, ``enqueue_transition`` should
        still be called.

        This test is GREEN on the current code and should remain GREEN
        after the fix.
        """
        # Arrange
        store = MagicMock()
        prs = AsyncMock()
        escalator = _make_escalator(store=store, prs=prs)
        issue = MagicMock(id=20)

        with patch(
            "phase_utils.escalate_to_diagnostic",
            new_callable=AsyncMock,
            side_effect=RuntimeError("diagnostic escalation failed"),
        ):
            await escalator(
                issue,
                cause="plan failed",
                details="details",
                category=FailureCategory.PLAN_VALIDATION,
            )

        # Assert — fallback succeeded, so transition should be enqueued
        store.enqueue_transition.assert_called_once_with(issue, "diagnose")

    @pytest.mark.asyncio
    async def test_record_harness_failure_called_even_when_both_fail(self) -> None:
        """``record_harness_failure`` should always be called — it records
        the pipeline failure event, not the escalation outcome.

        This test is GREEN on the current code and should remain GREEN
        after the fix.
        """
        # Arrange
        harness = MagicMock()
        prs = AsyncMock()
        prs.swap_pipeline_labels.side_effect = RuntimeError("swap failed")
        escalator = _make_escalator(harness_insights=harness, prs=prs)
        issue = MagicMock(id=42)

        with patch(
            "phase_utils.escalate_to_diagnostic",
            new_callable=AsyncMock,
            side_effect=RuntimeError("escalation failed"),
        ):
            await escalator(
                issue,
                cause="plan failed",
                details="validation errors",
                category=FailureCategory.PLAN_VALIDATION,
            )

        # Assert — failure is always recorded regardless of escalation outcome
        harness.append_failure.assert_called_once()
