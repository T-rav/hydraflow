"""Regression test for issue #6742.

Bug: Phase classes use implicit truthiness checks (``if self._summarizer and ...``,
``if self._beads_manager:``) on attributes typed as
``X | None``.  This violates the avoided-patterns doc because a mock with
``__bool__`` returning False (or any object with a falsy ``__bool__``) will silently
short-circuit the guarded code path even though the object is not None.

The correct pattern is ``if self._x is not None and ...``.

These tests construct falsy-but-not-None mocks and verify that the guarded code
path still executes.  They are RED against the current (buggy) code because the
truthiness check treats the falsy mock as absent.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.conftest import TaskFactory, WorkerResultFactory
from tests.helpers import make_implement_phase, make_plan_phase

# ---------------------------------------------------------------------------
# Helper: create a mock that is not None but is falsy
# ---------------------------------------------------------------------------


def _falsy_mock(**kwargs):
    """Return a MagicMock whose bool() is False.

    This simulates the scenario described in docs/wiki/gotchas.md
    where a mock with spec= or a custom __bool__ evaluates as falsy, causing
    ``if obj and ...`` to skip the branch even though ``obj is not None``.
    """
    mock = MagicMock(**kwargs)
    mock.__bool__ = MagicMock(return_value=False)
    return mock


# ===========================================================================
# ImplementPhase — _summarizer truthiness checks (lines 112, 142)
# ===========================================================================


class TestImplementPhaseSummarizerTruthy:
    """Issue #6742 — ImplementPhase._summarizer must use ``is not None``."""

    @pytest.mark.asyncio
    async def test_post_impl_transcript_calls_summarizer_when_falsy(
        self, config
    ) -> None:
        """A falsy-but-present _summarizer must still be invoked (line 112).

        Current code: ``if self._summarizer and result.transcript and ...``
        The falsy mock causes this to short-circuit, so summarize_and_comment
        is never called.
        """
        issue = TaskFactory.create(id=7)
        phase, _, _ = make_implement_phase(config, [issue])

        falsy_summarizer = _falsy_mock()
        falsy_summarizer.summarize_and_comment = AsyncMock()
        phase._summarizer = falsy_summarizer

        # Silence the MemorySuggester so it doesn't interfere
        phase._suggest_memory = AsyncMock()

        result = WorkerResultFactory.create(
            issue_number=7,
            transcript="test transcript content",
            success=True,
        )

        await phase._post_impl_transcript(result, status="success")

        assert falsy_summarizer.summarize_and_comment.called, (
            "summarize_and_comment was NOT called because `if self._summarizer` "
            "evaluated as False on a falsy-but-not-None mock — "
            "should use `if self._summarizer is not None` (issue #6742, "
            "implement_phase.py:112)"
        )

    @pytest.mark.asyncio
    async def test_post_impl_transcript_hooks_calls_summarizer_when_falsy(
        self, config
    ) -> None:
        """A falsy-but-present _summarizer must still be invoked (line 142).

        The zero-diff branch at line 142 has the same pattern.
        """
        issue = TaskFactory.create(id=8)
        phase, _, _ = make_implement_phase(config, [issue])

        falsy_summarizer = _falsy_mock()
        falsy_summarizer.summarize_and_comment = AsyncMock()
        phase._summarizer = falsy_summarizer
        phase._suggest_memory = AsyncMock()

        result = WorkerResultFactory.create(
            issue_number=8,
            transcript="test transcript",
            success=True,
        )

        # Trigger the zero-diff-already-filed branch
        phase._zero_diff_memory_filed.add(8)

        await phase.post_impl_transcript_hooks([result])

        assert falsy_summarizer.summarize_and_comment.called, (
            "summarize_and_comment was NOT called in post_impl_transcript_hooks "
            "because `if self._summarizer` evaluated as False on a falsy mock — "
            "should use `if self._summarizer is not None` (issue #6742, "
            "implement_phase.py:142)"
        )


# ===========================================================================
# ImplementPhase — _beads_manager truthiness check (line 564)
# ===========================================================================


class TestImplementPhaseBeadsManagerTruthy:
    """Issue #6742 — ImplementPhase._beads_manager must use ``is not None``."""

    @pytest.mark.asyncio
    async def test_beads_manager_checked_via_identity_not_truthiness(
        self, config
    ) -> None:
        """A falsy-but-present _beads_manager must still be consulted (line 564).

        Current code: ``if self._beads_manager:``
        A falsy mock skips the bead-mapping lookup entirely.
        """
        issue = TaskFactory.create(id=9)
        phase, _, _ = make_implement_phase(config, [issue])

        falsy_bm = _falsy_mock()
        phase._beads_manager = falsy_bm
        del falsy_bm

        import implement_phase._build as build_mod  # noqa: PLC0415

        src = inspect.getsource(build_mod)
        assert "if self._beads_manager:" not in src, (
            "implement_phase reads _beads_manager by truthiness; a "
            "falsy-but-present manager would be skipped (issue #6742)"
        )


# ===========================================================================
# PlanPhase — _summarizer truthiness checks (lines 159, 480)
# ===========================================================================


class TestPlanPhaseSummarizerTruthy:
    """Issue #6742 — PlanPhase._summarizer must use ``is not None``."""

    @pytest.mark.asyncio
    async def test_plan_transcript_calls_summarizer_when_falsy(self, config) -> None:
        """A falsy-but-present _summarizer must still be invoked (line 480).

        PlanPhase._post_plan_transcript at line 480:
        ``if self._summarizer and result.transcript:``
        """
        from models import PlanResult

        phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)

        falsy_summarizer = _falsy_mock()
        falsy_summarizer.summarize_and_comment = AsyncMock()
        phase._summarizer = falsy_summarizer
        phase._suggest_memory = AsyncMock()

        issue = TaskFactory.create(id=10)
        result = PlanResult(
            plan="some plan",
            transcript="plan transcript text",
            issue_number=10,
            duration_seconds=1.0,
        )

        await phase._post_plan_transcript(issue, result, status="success")

        assert falsy_summarizer.summarize_and_comment.called, (
            "summarize_and_comment was NOT called because `if self._summarizer` "
            "evaluated as False on a falsy mock — "
            "should use `if self._summarizer is not None` (issue #6742, "
            "plan_phase.py:480)"
        )


# ===========================================================================
# PlanPhase — _beads_manager truthiness check (line 283)
# ===========================================================================


class TestPlanPhaseBeadsManagerTruthy:
    """Issue #6742 — PlanPhase._beads_manager must use ``is not None``."""

    @pytest.mark.asyncio
    async def test_beads_manager_checked_via_identity_not_truthiness(
        self, config
    ) -> None:
        """A falsy-but-present _beads_manager must still trigger bead creation (line 283).

        Current code: ``if self._beads_manager and result.plan:``
        """
        phase, _state, _planners, _prs, _store, _stop = make_plan_phase(config)

        phase._beads_manager = _falsy_mock()

        import implement_phase._build as build_mod  # noqa: PLC0415

        src = inspect.getsource(build_mod)
        assert "self._beads_manager and " not in src, (
            "a _beads_manager guard still reads by truthiness, so a "
            "falsy-but-present manager skips bead creation (issue #6742)"
        )
        assert "self._beads_manager is not None" in src, (
            "the identity check disappeared — nothing pins #6742's fix"
        )


# ===========================================================================
# ReviewPhase — _summarizer truthiness check (line 274)
# ===========================================================================


class TestReviewPhaseSummarizerTruthy:
    """Issue #6742 — ReviewPhase._summarizer must use ``is not None``."""

    @pytest.mark.asyncio
    async def test_post_review_transcript_calls_summarizer_when_falsy(
        self, config
    ) -> None:
        """A falsy-but-present _summarizer must still be invoked (line 274).

        Current code: ``if self._summarizer and result.transcript and result.issue_number > 0:``
        """
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)

        falsy_summarizer = _falsy_mock()
        falsy_summarizer.summarize_and_comment = AsyncMock()
        phase._summarizer = falsy_summarizer
        phase._suggest_memory = AsyncMock()

        from models import ReviewResult

        result = ReviewResult(
            pr_number=100,
            issue_number=10,
            transcript="review transcript text",
            duration_seconds=2.0,
        )

        await phase._post_review_transcript(result, status="success")

        assert falsy_summarizer.summarize_and_comment.called, (
            "summarize_and_comment was NOT called because `if self._summarizer` "
            "evaluated as False on a falsy mock — "
            "should use `if self._summarizer is not None` (issue #6742, "
            "review_phase.py:274)"
        )
