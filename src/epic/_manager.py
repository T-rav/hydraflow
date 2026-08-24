"""Epic lifecycle management — tracking, progress, stale detection, and auto-close."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Protocol

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_fetcher import IssueFetcher
from models import (
    EpicDetail,
    EpicState,
    EpicUpdatePayload,
)
from pr_manager import PRManager
from state import StateTracker

from ._child_info import EpicChildInfoMixin
from ._children import EpicChildEventsMixin
from ._completion import EpicCompletionChecker
from ._detail import EpicDetailMixin
from ._merge_order import EpicMergeOrderMixin
from ._parse import _coerce_merge_strategy
from ._progress import EpicProgressMixin
from ._release import EpicReleaseMixin
from ._staleness import EpicStalenessMixin

logger = logging.getLogger("hydraflow.epic")


class WorkerTruthStore(Protocol):
    """Minimal ``IssueStore`` surface the EpicManager needs for worker-derived
    epic execution state (issue #10299).

    Both accessors map ``issue_number -> stage``. The real ``IssueStore``
    satisfies this structurally; tests can pass a lightweight stub. Injecting
    the *raw* store (not the ``CachingIssueStore`` decorator) matters — queue
    state lives on the inner object.
    """

    def get_worker_held_issues(self) -> dict[int, str]:
        """Issues a worker is actually on (``_active`` ∪ ``_in_flight``)."""
        ...

    def get_queued_issues(self) -> dict[int, str]:
        """Issues sitting in a stage queue awaiting dispatch."""
        ...


class EpicManager(
    EpicChildEventsMixin,
    EpicChildInfoMixin,
    EpicDetailMixin,
    EpicMergeOrderMixin,
    EpicProgressMixin,
    EpicReleaseMixin,
    EpicStalenessMixin,
):
    """Centralized epic lifecycle management.

    Handles registration, progress tracking, stale detection, and
    auto-close of epics. Wraps ``EpicCompletionChecker`` for the
    actual close logic and adds state persistence + event publishing.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        prs: PRManager,
        fetcher: IssueFetcher,
        event_bus: EventBus,
        issue_store: WorkerTruthStore | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._prs = prs
        self._fetcher = fetcher
        self._bus = event_bus
        # Ground truth for factory occupancy (issue #10299). Optional so legacy
        # construction (and tests that don't care) keep working — child
        # execution state then falls back to label-derived.
        self._issue_store = issue_store
        self._checker = EpicCompletionChecker(config, prs, fetcher, state=state)
        # Background cache: keyed by epic_number → EpicDetail
        self._detail_cache: dict[int, EpicDetail] = {}
        self._cache_timestamps: dict[int, float] = {}  # per-entry TTL
        self._cache_ttl_seconds: float = 60.0
        self._release_jobs: dict[int, str] = {}  # epic_number → job_id
        self._release_locks: dict[int, asyncio.Lock] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def register_epic(
        self,
        epic_number: int,
        title: str,
        children: list[int],
        *,
        auto_decomposed: bool = False,
    ) -> None:
        """Register a new epic for lifecycle tracking."""
        now = datetime.now(UTC).isoformat()
        epic_state = EpicState(
            epic_number=epic_number,
            title=title,
            child_issues=list(children),
            created_at=now,
            last_activity=now,
            auto_decomposed=auto_decomposed,
            merge_strategy=_coerce_merge_strategy(self._config.epic_merge_strategy),
        )
        self._state.upsert_epic_state(epic_state)
        await self._publish_update(epic_number, "registered")
        logger.info(
            "Registered epic #%d with %d children (auto_decomposed=%s)",
            epic_number,
            len(children),
            auto_decomposed,
        )

    def _invalidate_cache(self, epic_number: int) -> None:
        """Remove cached detail for *epic_number* so the next read fetches fresh data."""
        self._detail_cache.pop(epic_number, None)
        self._cache_timestamps.pop(epic_number, None)

    def find_parent_epics(self, child_number: int) -> list[int]:
        """Return epic numbers that include *child_number* as a child."""
        parents: list[int] = []
        for epic in self._state.get_all_epic_states().values():
            if child_number in epic.child_issues:
                parents.append(epic.epic_number)
        return parents

    async def _publish_update(self, epic_number: int, action: str) -> None:
        """Publish an EPIC_UPDATE event with current progress."""
        progress = self.get_progress(epic_number)
        data: EpicUpdatePayload = {
            "epic_number": epic_number,
            "action": action,
        }
        if progress is not None:
            data["progress"] = progress.model_dump()
        await self._bus.publish(HydraFlowEvent(type=EventType.EPIC_UPDATE, data=data))
