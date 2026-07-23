"""Background worker — periodic retrospective analysis via durable queue.

Producers (PostMergeHandler, ReviewPhase) append work items to the queue.
This loop polls the queue, runs analysis (pattern detection, proposal
verification), publishes dashboard events, and acknowledges processed items.
Unacknowledged items survive crashes for replay.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from events import EventType, HydraFlowEvent
from exception_classify import reraise_on_credit_or_bug
from retrospective_queue import QueueKind
from review_insights import reconcile_closed_insight_escalations

if TYPE_CHECKING:
    from ports import PRPort
    from retrospective import RetrospectiveCollector
    from retrospective_queue import QueueItem, RetrospectiveQueue
    from review_insights import ReviewInsightStore

logger = logging.getLogger("hydraflow.retrospective_loop")

# Window (#8988): once a stale-insight escalation is filed for a category,
# do not refile within this window even if the open-issue GitHub lookup races
# and returns 0.  An hour is much shorter than the 30-minute
# retrospective_interval default cadence, but long enough to survive
# back-to-back ticks that hit GitHub before its search index catches up to a
# freshly-created issue.
_INSIGHT_DEDUP_WINDOW = timedelta(hours=1)


def _now_utc() -> datetime:
    """Indirection seam so tests can pin the clock."""
    return datetime.now(UTC)


class RetrospectiveLoop(BaseBackgroundLoop):
    """Polls the retrospective durable queue and runs analysis.

    Work items arrive from PostMergeHandler (retro patterns) and
    ReviewPhase (review patterns).  Processing runs out of sync
    with the main pipeline loops, keeping the factory floor clear.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        deps: LoopDeps,
        retrospective: RetrospectiveCollector,
        insights: ReviewInsightStore,
        queue: RetrospectiveQueue,
        prs: PRPort | None = None,
    ) -> None:
        super().__init__(worker_name="retrospective", config=config, deps=deps)
        self._retro = retrospective
        self._insights = insights
        self._queue = queue
        self._prs = prs
        # Per-category last-escalated timestamps for stale-insight dedup
        # (#8988).  Lives in-memory; the open-issue GitHub lookup is the
        # cross-restart authority.  This dict is the race-safety net.
        self._insight_escalated_at: dict[str, datetime] = {}

    def _get_default_interval(self) -> int:
        return self._config.retrospective_interval

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.retrospective_loop_enabled:
            return {"status": "config_disabled"}
        items = self._queue.load()
        if not items:
            return {"processed": 0, "patterns_filed": 0, "stale_proposals": 0}

        acknowledged: list[str] = []
        patterns_filed = 0
        stale_proposals = 0

        for item in items:
            if self._stop_event.is_set():
                break
            try:
                result = await self._process_item(item)
                patterns_filed += result.get("patterns_filed", 0)
                stale_proposals += result.get("stale_proposals", 0)
                acknowledged.append(item.id)
                await self._publish_update(item, "processed")
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "Retrospective: failed to process %s item (id=%s) — will retry",
                    item.kind,
                    item.id,
                    exc_info=True,
                )

        if acknowledged:
            self._queue.acknowledge(acknowledged)

        return {
            "processed": len(acknowledged),
            "patterns_filed": patterns_filed,
            "stale_proposals": stale_proposals,
        }

    async def _process_item(self, item: QueueItem) -> dict[str, int]:
        """Dispatch a single queue item to the appropriate handler."""
        if item.kind == QueueKind.RETRO_PATTERNS:
            return await self._handle_retro_patterns()
        if item.kind == QueueKind.REVIEW_PATTERNS:
            return await self._handle_review_patterns()
        if item.kind == QueueKind.VERIFY_PROPOSALS:
            return await self._handle_verify_proposals()
        logger.warning("Unknown queue item kind: %s", item.kind)
        return {}

    async def _handle_retro_patterns(self) -> dict[str, int]:
        """Run retrospective pattern detection."""
        entries = self._retro._load_recent(self._config.retrospective_window)
        await self._retro._detect_patterns(entries)
        return {"patterns_filed": 0}

    async def _handle_review_patterns(self) -> dict[str, int]:
        """Run review insight pattern analysis and file issues for new patterns."""
        from review_insights import (  # noqa: PLC0415
            CATEGORY_DESCRIPTIONS,
            analyze_patterns,
            build_insight_issue_body,
        )

        records = self._insights.load_recent(self._config.review_insight_window)
        patterns = analyze_patterns(records, self._config.review_pattern_threshold)
        proposed = self._insights.get_proposed_categories()
        filed = 0

        for category, count, evidence in patterns:
            if category in proposed:
                continue
            if self._prs is None:
                logger.warning(
                    "Retrospective: cannot file review insight issue — no PRPort"
                )
                break
            body = build_insight_issue_body(category, count, len(records), evidence)
            desc = CATEGORY_DESCRIPTIONS.get(category, category)
            title = f"[Review Insight] Recurring feedback: {desc}"
            labels = self._config.find_label[:1]
            await self._prs.create_issue(title, body, labels)
            self._insights.mark_category_proposed(category)
            self._insights.record_proposal(category, pre_count=count)
            filed += 1

        return {"patterns_filed": filed}

    async def _handle_verify_proposals(self) -> dict[str, int]:
        """Verify improvement-proposal outcomes and route stale ones to the factory.

        A *stale* proposal means the factory's first pass at a recurring review
        finding (filed by :meth:`_handle_review_patterns`) did not reduce its
        frequency after ``_PROPOSAL_STALE_DAYS``. Rather than a ``hydraflow-hitl``
        dead-end, file an actionable ``find_label`` issue (#9227) so the pipeline
        (triage → plan → implement → review → merge) takes another, better-informed
        pass at the root cause. The proposal auto-verifies — and this escalation
        stops — once the pattern frequency drops >50% (see :func:`verify_proposals`).

        Dedup rules (issue #8988):

        - **Open escalation exists** for the category → skip. The factory is
          already working it; no duplicate, and no comment spam.
        - **Closed escalation exists** → treat the close (factory merged a fix,
          or a human dismissed it) as a re-arm signal: clear the in-memory
          window-tracker so a still-stale proposal files fresh. Mirrors
          ``FakeCoverageAuditorLoop._reconcile_closed_escalations``.
        - **In-memory window guard** (:data:`_INSIGHT_DEDUP_WINDOW`): if this
          category was escalated within the window, skip entirely. Catches
          races where GitHub's search index has not caught up to a
          freshly-created issue.
        """
        from review_insights import (  # noqa: PLC0415
            _PROPOSAL_STALE_DAYS,
            CATEGORY_DESCRIPTIONS,
            PERSISTENT_FINDING_PREFIX,
            build_persistent_finding_body,
            verify_proposals,
        )

        # Sample current_count over the SAME window the baseline pre_count was
        # measured over (review_insight_window). Hardcoding 50 here while
        # pre_count is captured over review_insight_window (default 10) makes
        # current_count >= pre_count permanently true for high-frequency
        # categories, so verify_proposals could never observe improvement and
        # re-filed false stale-insight HITL issues forever (#9444). This
        # mirrors ReviewPhase._record_review_insight's correct window usage.
        records = self._insights.load_recent(self._config.review_insight_window)
        stale = verify_proposals(self._insights, records)

        if not stale:
            return {"stale_proposals": 0}

        if self._prs is None:
            logger.warning(
                "Retrospective: cannot file review-insight issue — no PRPort"
            )
            return {"stale_proposals": len(stale)}

        # Re-arm: any closed escalation clears its category from the in-memory
        # window-tracker so the next stale tick files fresh.  Cheap; runs once
        # per verify-proposals tick.
        await self._reconcile_closed_insight_escalations()

        now = _now_utc()
        for category in stale:
            desc = CATEGORY_DESCRIPTIONS.get(category, category)
            title = f"{PERSISTENT_FINDING_PREFIX}{desc}"

            # 1. Window guard — protects against races where GitHub's
            #    search index has not surfaced our just-filed issue yet.
            last = self._insight_escalated_at.get(category)
            if last is not None and (now - last) < _INSIGHT_DEDUP_WINDOW:
                logger.debug(
                    "Retrospective: skipping stale-insight refile for "
                    "category=%s — within %s dedup window",
                    category,
                    _INSIGHT_DEDUP_WINDOW,
                )
                continue

            # 2. Open-issue lookup — if the factory is already working a routed
            #    issue, skip (no duplicate, no comment spam).
            existing = await self._prs.find_existing_issue(title)
            if existing:
                # Touch the window-tracker so we keep skipping cheaply.
                self._insight_escalated_at[category] = now
                continue

            # 3. File a fresh actionable find-queue issue. Set the window-tracker
            #    BEFORE the await so a crash between issue creation and the
            #    assignment doesn't strand the freshly-filed issue with no
            #    in-memory guard — protects against the cross-tick race where
            #    ``find_existing_issue`` may not yet see the just-filed issue via
            #    GitHub's search index.
            body = build_persistent_finding_body(category, desc, _PROPOSAL_STALE_DAYS)
            labels = self._config.find_label[:1]
            self._insight_escalated_at[category] = now
            try:
                await self._prs.create_issue(title, body, labels)
            except Exception:
                # Filing failed — clear the optimistic guard so the next
                # tick can retry. Re-raise to preserve normal error flow.
                self._insight_escalated_at.pop(category, None)
                raise

        return {"stale_proposals": len(stale)}

    async def _reconcile_closed_insight_escalations(self) -> None:
        """Clear the in-memory window-tracker for HUMAN-closed stale-insight
        escalations only — bot/programmatic closes must not re-arm (#8996).

        Delegates to :func:`review_insights.reconcile_closed_insight_escalations`,
        the single shared implementation this loop and the ``ReviewPhase``
        fallback (``review_phase/_phase.py``) both call so the two writers
        can't drift apart. See that function's docstring for the full
        bot-vs-human contract.
        """
        if self._prs is None:
            return
        if not self._insight_escalated_at:
            return  # Nothing to re-arm.

        find_labels = list(self._config.find_label)
        if not find_labels:
            return

        cleared = await reconcile_closed_insight_escalations(
            prs=self._prs,
            insight_escalated_at=self._insight_escalated_at,
            find_label=find_labels[0],
        )
        if cleared:
            logger.info(
                "Retrospective: re-armed stale-insight tracker for %s",
                cleared,
            )

    async def _publish_update(self, item: QueueItem, status: str) -> None:
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.RETROSPECTIVE_UPDATE,
                data={
                    "kind": item.kind,
                    "issue": item.issue_number,
                    "pr": item.pr_number,
                    "status": status,
                },
            )
        )
