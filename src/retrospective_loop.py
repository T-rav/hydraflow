"""Background worker — periodic retrospective analysis via durable queue.

Producers (PostMergeHandler, ReviewPhase) append work items to the queue.
This loop polls the queue, runs analysis (pattern detection, proposal
verification), publishes dashboard events, and acknowledges processed items.
Unacknowledged items survive crashes for replay.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from events import EventType, HydraFlowEvent
from retrospective_queue import QueueKind

if TYPE_CHECKING:
    from retrospective import RetrospectiveCollector
    from retrospective_queue import QueueItem, RetrospectiveQueue
    from review_insights import ReviewInsightStore

logger = logging.getLogger("hydraflow.retrospective_loop")


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
    ) -> None:
        super().__init__(worker_name="retrospective", config=config, deps=deps)
        self._retro = retrospective
        self._insights = insights
        self._queue = queue

    def _get_default_interval(self) -> int:
        return self._config.retrospective_interval

    async def _do_work(self) -> dict[str, Any] | None:
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
            except Exception:
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
        """Run review insight pattern analysis."""
        from review_insights import analyze_patterns  # noqa: PLC0415

        records = self._insights.load_recent(self._config.review_insight_window)
        patterns = analyze_patterns(records, self._config.review_pattern_threshold)
        return {"patterns_filed": len(patterns)}

    async def _handle_verify_proposals(self) -> dict[str, int]:
        """Verify improvement proposal outcomes."""
        from review_insights import verify_proposals  # noqa: PLC0415

        records = self._insights.load_recent(50)
        stale = verify_proposals(self._insights, records)
        return {"stale_proposals": len(stale)}

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
