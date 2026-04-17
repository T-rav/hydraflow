"""Regression test for issue #6715.

``RetrospectiveLoop._do_work`` uses a broad ``except Exception`` in its
per-item processing loop (line 72).  This catches ``AuthenticationError``
and ``CreditExhaustedError`` — fatal infrastructure errors that should
propagate to the loop supervisor so it can halt or trigger the
orchestrator's credit-pause mechanism.

Instead, these errors are silently logged as warnings and the item is
simply retried on the next cycle, meaning:

- An expired GitHub token causes infinite warning-level log spam with
  no escalation.
- Credit exhaustion is never surfaced to the orchestrator pause logic.

The fix is to re-raise ``AuthenticationError`` and
``CreditExhaustedError`` before the generic ``except Exception`` handler,
matching the pattern already used in ``BaseBackgroundLoop._execute_cycle``
(lines 141-144).

These tests are RED until ``_do_work`` lets fatal errors propagate.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from retrospective_loop import RetrospectiveLoop
from retrospective_queue import QueueItem, QueueKind
from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
) -> tuple[RetrospectiveLoop, MagicMock, MagicMock, MagicMock]:
    """Build a RetrospectiveLoop with mocks.

    Returns (loop, retro_mock, insights_mock, queue_mock).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    retro = MagicMock()
    retro._load_recent = MagicMock(return_value=[])
    retro._detect_patterns = AsyncMock()

    insights = MagicMock()
    insights.load_recent = MagicMock(return_value=[])
    insights.get_proposed_categories = MagicMock(return_value=set())

    queue = MagicMock()
    queue.load = MagicMock(return_value=[])
    queue.acknowledge = MagicMock()

    loop = RetrospectiveLoop(
        config=deps.config,
        deps=deps.loop_deps,
        retrospective=retro,
        insights=insights,
        queue=queue,
        prs=None,
    )
    return loop, retro, insights, queue


class TestAuthenticationErrorPropagates:
    """AuthenticationError must escape _do_work, not be swallowed."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6715 — fix not yet landed", strict=False)
    async def test_auth_error_propagates_from_retro_patterns(
        self, tmp_path: Path
    ) -> None:
        """An AuthenticationError during item processing must propagate.

        BUG: the broad ``except Exception`` on line 72 catches it, logs a
        warning, and continues — the error never reaches the loop supervisor.
        """
        loop, retro, _, queue = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=42)
        queue.load.return_value = [item]
        retro._detect_patterns.side_effect = AuthenticationError("token expired")

        with pytest.raises(AuthenticationError, match="token expired"):
            await loop._do_work()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6715 — fix not yet landed", strict=False)
    async def test_auth_error_propagates_from_review_patterns(
        self, tmp_path: Path
    ) -> None:
        """AuthenticationError during review pattern analysis must propagate."""
        loop, _, insights, queue = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.REVIEW_PATTERNS, pr_number=99)
        queue.load.return_value = [item]
        insights.load_recent.side_effect = AuthenticationError("bad credentials")

        with pytest.raises(AuthenticationError, match="bad credentials"):
            await loop._do_work()


class TestCreditExhaustedErrorPropagates:
    """CreditExhaustedError must escape _do_work, not be swallowed."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6715 — fix not yet landed", strict=False)
    async def test_credit_error_propagates_from_retro_patterns(
        self, tmp_path: Path
    ) -> None:
        """A CreditExhaustedError during item processing must propagate.

        BUG: the broad ``except Exception`` on line 72 catches it, logs a
        warning, and continues — credit exhaustion never triggers the
        orchestrator's credit-pause logic.
        """
        loop, retro, _, queue = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=42)
        queue.load.return_value = [item]

        exc = CreditExhaustedError("credits exhausted")
        exc.resume_at = None  # type: ignore[attr-defined]
        retro._detect_patterns.side_effect = exc

        with pytest.raises(CreditExhaustedError, match="credits exhausted"):
            await loop._do_work()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6715 — fix not yet landed", strict=False)
    async def test_credit_error_propagates_from_verify_proposals(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError during proposal verification must propagate."""
        from unittest.mock import patch

        loop, _, insights, queue = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.VERIFY_PROPOSALS)
        queue.load.return_value = [item]
        insights.load_recent.return_value = []

        exc = CreditExhaustedError("no credits left")
        exc.resume_at = None  # type: ignore[attr-defined]

        with patch("review_insights.verify_proposals", side_effect=exc):
            with pytest.raises(CreditExhaustedError, match="no credits left"):
                await loop._do_work()


class TestNonFatalErrorsStillCaught:
    """Regular exceptions should still be caught (existing behavior preserved)."""

    @pytest.mark.asyncio
    async def test_runtime_error_is_caught_not_propagated(self, tmp_path: Path) -> None:
        """A plain RuntimeError should still be caught and logged."""
        loop, retro, _, queue = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=42)
        queue.load.return_value = [item]
        retro._detect_patterns.side_effect = RuntimeError("transient failure")

        # Should NOT raise — the generic handler catches it
        result = await loop._do_work()
        assert result is not None
        assert result["processed"] == 0
