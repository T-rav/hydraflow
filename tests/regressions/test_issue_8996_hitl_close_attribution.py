"""Regression: RetrospectiveLoop / ReviewPhase must distinguish a bot-closed
stale-insight (HITL) escalation from a human-closed one before re-arming the
in-memory window-tracker (#8996).

Before the fix, both ``RetrospectiveLoop._reconcile_closed_insight_escalations``
and the ``ReviewPhase`` fallback in ``review_phase/_phase.py`` cleared the
tracker for ANY closed escalation matching the title prefix — human or bot.
Design intent is "human close = re-arm", not "any close = re-arm": if a
code path closes an escalation programmatically (stamped with
``escalation_reconcile.BOT_CLOSE_MARKER_LABEL``), the very next tick must
NOT treat that as a human re-arm signal and refile a duplicate.

Both writers now delegate to the single shared implementation,
``review_insights.reconcile_closed_insight_escalations``, which uses
``escalation_reconcile.is_bot_close`` — the same predicate #9437 introduced
for ``EscalationReconciler.reconcile_closed`` — so the contract can't drift
between the loop and its fallback mirror.

Threading note: ``is_bot_close`` reads the ``labels`` key on the closed-issue
dict. ``PRManager.list_closed_issues_by_label`` did not previously project
labels (#9943 scoped that to the OPEN listing only); this fix threads
``labels`` through the closed listing too (adapter + ``FakeGitHub``), or
``is_bot_close`` would always fail open to "human" and this fix would be a
no-op in production. See ``tests/regressions/test_issue_9727_closedat_threading.py``
for the parallel ``closed_at`` threading precedent this mirrors.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from escalation_reconcile import BOT_CLOSE_MARKER_LABEL
from retrospective_loop import RetrospectiveLoop
from retrospective_queue import QueueItem, QueueKind
from review_insights import reconcile_closed_insight_escalations
from tests.helpers import make_bg_loop_deps

_PREFIX = "[Review Insight] Persistent finding: "
_DESC = "Missing test coverage"
_CATEGORY = "missing_tests"


def _closed_issue(number: int, title: str, *, bot: bool = False) -> dict:
    """A closed-issue row as returned by ``list_closed_issues_by_label``
    (post-#8996: carries ``labels`` in gh wire shape)."""
    issue: dict = {
        "number": number,
        "title": title,
        "body": "",
        "updated_at": "2026-07-20T00:00:00Z",
    }
    if bot:
        issue["labels"] = [{"name": BOT_CLOSE_MARKER_LABEL}]
    return issue


# ---------------------------------------------------------------------------
# Acceptance (1): the shared reconcile function distinguishes bot vs human.
# ---------------------------------------------------------------------------


class TestReconcileClosedInsightEscalationsDistinguishesCloser:
    """Unit coverage of ``review_insights.reconcile_closed_insight_escalations``
    in isolation — the single implementation both writers delegate to."""

    @pytest.mark.asyncio
    async def test_bot_closed_entry_is_retained(self) -> None:
        prs = AsyncMock()
        prs.list_closed_issues_by_label = AsyncMock(
            return_value=[_closed_issue(1, f"{_PREFIX}{_DESC}", bot=True)]
        )
        tracker = {_CATEGORY: datetime(2026, 7, 20, 0, 0, tzinfo=UTC)}

        with patch("review_insights.CATEGORY_DESCRIPTIONS", {_CATEGORY: _DESC}):
            cleared = await reconcile_closed_insight_escalations(
                prs=prs, insight_escalated_at=tracker, find_label="hydraflow-find"
            )

        assert cleared == []
        assert _CATEGORY in tracker, "bot close must not clear the window-tracker"

    @pytest.mark.asyncio
    async def test_human_closed_entry_is_cleared(self) -> None:
        prs = AsyncMock()
        prs.list_closed_issues_by_label = AsyncMock(
            return_value=[_closed_issue(1, f"{_PREFIX}{_DESC}")]
        )
        tracker = {_CATEGORY: datetime(2026, 7, 20, 0, 0, tzinfo=UTC)}

        with patch("review_insights.CATEGORY_DESCRIPTIONS", {_CATEGORY: _DESC}):
            cleared = await reconcile_closed_insight_escalations(
                prs=prs, insight_escalated_at=tracker, find_label="hydraflow-find"
            )

        assert cleared == [_CATEGORY]
        assert _CATEGORY not in tracker, "human close must clear the window-tracker"


# ---------------------------------------------------------------------------
# Acceptance (2) + (3): RetrospectiveLoop end-to-end.
# ---------------------------------------------------------------------------


def _make_loop(tmp_path: Path):
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

    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=0)
    prs.find_existing_issue = AsyncMock(return_value=0)
    prs.list_closed_issues_by_label = AsyncMock(return_value=[])
    prs.post_comment = AsyncMock()

    loop = RetrospectiveLoop(
        config=deps.config,
        deps=deps.loop_deps,
        retrospective=retro,
        insights=insights,
        queue=queue,
        prs=prs,
    )
    return loop, insights, queue, prs


class TestRetrospectiveLoopBotVsHumanClose:
    """Issue #8996 — the loop site."""

    @pytest.mark.asyncio
    async def test_bot_closed_escalation_does_not_re_arm_next_tick(
        self, tmp_path: Path
    ) -> None:
        """Programmatic close, stamped with the bot marker, shortly after
        filing must NOT re-arm — the next tick (well within the 1h window)
        must stay suppressed, not file a duplicate."""
        loop, insights, queue, prs = _make_loop(tmp_path)
        insights.load_recent.return_value = []

        with (
            patch("review_insights.verify_proposals", return_value=[_CATEGORY]),
            patch("review_insights.CATEGORY_DESCRIPTIONS", {_CATEGORY: _DESC}),
            patch("review_insights._PROPOSAL_STALE_DAYS", 30),
        ):
            # Tick 1 — files the escalation.
            queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
            prs.find_existing_issue.return_value = 0
            prs.create_issue.return_value = 6001
            with patch(
                "retrospective_loop._now_utc",
                return_value=datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC),
            ):
                await loop._do_work()
            assert prs.create_issue.await_count == 1

            # A programmatic path closes #6001, stamping the bot marker
            # BEFORE closing (mirrors escalation_reconcile's contract).
            prs.find_existing_issue.return_value = 0
            prs.list_closed_issues_by_label.return_value = [
                _closed_issue(6001, f"{_PREFIX}{_DESC}", bot=True)
            ]

            # Tick 2 — 15 minutes later, still well inside the 1h window.
            queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
            with patch(
                "retrospective_loop._now_utc",
                return_value=datetime(2026, 7, 20, 0, 15, 0, tzinfo=UTC),
            ):
                await loop._do_work()

            assert prs.create_issue.await_count == 1, (
                "bot close must not re-arm the window-tracker — a duplicate "
                "was filed on the very next tick"
            )

    @pytest.mark.asyncio
    async def test_human_closed_escalation_re_arms_and_refiles(
        self, tmp_path: Path
    ) -> None:
        """A human/external close (no bot marker) IS the re-arm signal — the
        next stale tick must be free to file fresh, even within the window."""
        loop, insights, queue, prs = _make_loop(tmp_path)
        insights.load_recent.return_value = []

        with (
            patch("review_insights.verify_proposals", return_value=[_CATEGORY]),
            patch("review_insights.CATEGORY_DESCRIPTIONS", {_CATEGORY: _DESC}),
            patch("review_insights._PROPOSAL_STALE_DAYS", 30),
        ):
            queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
            prs.find_existing_issue.return_value = 0
            prs.create_issue.return_value = 6002
            with patch(
                "retrospective_loop._now_utc",
                return_value=datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC),
            ):
                await loop._do_work()
            assert prs.create_issue.await_count == 1

            # A human closes #6002 shortly after — no bot marker.
            prs.find_existing_issue.return_value = 0
            prs.list_closed_issues_by_label.return_value = [
                _closed_issue(6002, f"{_PREFIX}{_DESC}")
            ]

            queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
            with patch(
                "retrospective_loop._now_utc",
                return_value=datetime(2026, 7, 20, 0, 15, 0, tzinfo=UTC),
            ):
                await loop._do_work()

            assert prs.create_issue.await_count == 2, (
                "human close must re-arm the window-tracker and allow a fresh file"
            )


# ---------------------------------------------------------------------------
# Acceptance (4): same treatment at the ``_phase.py`` mirror site.
# ---------------------------------------------------------------------------


class TestReviewPhaseFallbackBotVsHumanClose:
    """Issue #8996 — the ``review_phase/_phase.py`` fallback mirror site.

    The fallback branch of ``_record_review_insight`` fires only when no
    ``retrospective_queue`` is wired (mirrors ``RetrospectiveLoop
    ._handle_verify_proposals`` inline). It now calls the SAME shared
    ``review_insights.reconcile_closed_insight_escalations`` the loop calls,
    so the bot-vs-human contract can't drift between the two sites.
    """

    @staticmethod
    def _phase(default_mocks: bool = True):
        from tests.conftest import ConfigFactory
        from tests.helpers import make_review_phase

        config = ConfigFactory.create()
        phase = make_review_phase(config, default_mocks=default_mocks)
        phase._retrospective_queue = None  # force the fallback branch
        phase._prs.find_existing_issue = AsyncMock(return_value=None)
        phase._prs.post_comment = AsyncMock()
        phase._prs.create_task = AsyncMock()
        phase._prs.list_closed_issues_by_label = AsyncMock(return_value=[])

        mock_insights = MagicMock()
        mock_insights.load_recent.return_value = []
        mock_insights.get_proposed_categories.return_value = set()
        phase._insights = mock_insights
        return phase

    @pytest.mark.asyncio
    async def test_bot_closed_escalation_does_not_re_arm(self) -> None:
        from models import ReviewVerdict
        from tests.conftest import ReviewResultFactory

        phase = self._phase()
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        with (
            patch("review_phase.analyze_patterns", return_value=[]),
            patch("review_phase._phase.verify_proposals", return_value=[_CATEGORY]),
            patch("review_phase._phase.CATEGORY_DESCRIPTIONS", {_CATEGORY: _DESC}),
            # The shared reconcile function lives in ``review_insights`` and
            # reads ITS OWN module-global ``CATEGORY_DESCRIPTIONS`` for the
            # desc->category reverse lookup — patch both bound names so the
            # filing path (``_phase``) and the reconcile path (shared
            # function) agree on the same category/desc mapping.
            patch("review_insights.CATEGORY_DESCRIPTIONS", {_CATEGORY: _DESC}),
            patch("review_phase._phase._PROPOSAL_STALE_DAYS", 30),
        ):
            await phase._record_review_insight(result)
            assert phase._prs.create_task.await_count == 1

            # A programmatic close stamps the bot marker before closing.
            phase._prs.list_closed_issues_by_label = AsyncMock(
                return_value=[_closed_issue(9001, f"{_PREFIX}{_DESC}", bot=True)]
            )
            await phase._record_review_insight(result)

        assert phase._prs.create_task.await_count == 1, (
            "bot close must not re-arm the fallback window-tracker"
        )

    @pytest.mark.asyncio
    async def test_human_closed_escalation_re_arms(self) -> None:
        from models import ReviewVerdict
        from tests.conftest import ReviewResultFactory

        phase = self._phase()
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)

        with (
            patch("review_phase.analyze_patterns", return_value=[]),
            patch("review_phase._phase.verify_proposals", return_value=[_CATEGORY]),
            patch("review_phase._phase.CATEGORY_DESCRIPTIONS", {_CATEGORY: _DESC}),
            # The shared reconcile function lives in ``review_insights`` and
            # reads ITS OWN module-global ``CATEGORY_DESCRIPTIONS`` for the
            # desc->category reverse lookup — patch both bound names so the
            # filing path (``_phase``) and the reconcile path (shared
            # function) agree on the same category/desc mapping.
            patch("review_insights.CATEGORY_DESCRIPTIONS", {_CATEGORY: _DESC}),
            patch("review_phase._phase._PROPOSAL_STALE_DAYS", 30),
        ):
            await phase._record_review_insight(result)
            assert phase._prs.create_task.await_count == 1

            # A human closes the routed issue — no bot marker.
            phase._prs.list_closed_issues_by_label = AsyncMock(
                return_value=[_closed_issue(9002, f"{_PREFIX}{_DESC}")]
            )
            await phase._record_review_insight(result)

        assert phase._prs.create_task.await_count == 2, (
            "human close must re-arm the fallback window-tracker and allow a fresh file"
        )
