"""The epic detail read-model the dashboard renders, and its cache.

Building a detail is expensive (per-child GitHub reads), so the cache is
part of this concern rather than a separate one: ``get_detail``,
``get_cached_detail`` and ``refresh_cache`` are three doors into the same
stored object, and a change to what a detail contains has to move all
three together.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from exception_classify import reraise_on_credit_or_bug
from models import (
    CIStatus,
    EpicChildInfo,
    EpicChildStatus,
    EpicDetail,
    EpicProgress,
    EpicProgressPayload,
    EpicReadiness,
    EpicReadyPayload,
    EpicState,
    ReviewStatus,
)
from state import StateTracker

from ._parse import extract_version_from_title

if TYPE_CHECKING:
    from ._manager import WorkerTruthStore

logger = logging.getLogger("hydraflow.epic")


class EpicDetailMixin:
    """The epic detail read-model the dashboard renders, and its cache."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``EpicManager.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _bus: EventBus
    _cache_timestamps: dict[int, float]
    _cache_ttl_seconds: float
    _config: HydraFlowConfig
    _detail_cache: dict[int, EpicDetail]
    _issue_store: WorkerTruthStore | None
    _state: StateTracker

    if TYPE_CHECKING:

        async def _build_child_info(
            self,
            child_num: int,
            epic: EpicState,
            repo: str,
            fixed_label: str,
            worker_held: dict[int, str] | None = None,
            queued: dict[int, str] | None = None,
        ) -> EpicChildInfo: ...  # provided by _child_info

        def get_progress(
            self, epic_number: int
        ) -> EpicProgress | None: ...  # provided by _progress

    async def get_detail(self, epic_number: int) -> EpicDetail | None:
        """Fetch full epic detail including child issue info from GitHub.

        Uses background cache when available to avoid N GitHub API calls.
        """
        cached = self.get_cached_detail(epic_number)
        if cached is not None:
            return cached
        return await self._build_detail(epic_number)

    async def get_all_detail(self) -> list[EpicDetail]:
        """Return enriched detail for all tracked epics (for /api/epics)."""
        results: list[EpicDetail] = []
        for epic in self._state.get_all_epic_states().values():
            try:
                detail = await self.get_detail(epic.epic_number)
                if detail is not None:
                    results.append(detail)
            except Exception:
                logger.warning(
                    "Failed to get detail for epic #%d, continuing",
                    epic.epic_number,
                    exc_info=True,
                )
        return results

    def get_cached_detail(self, epic_number: int) -> EpicDetail | None:
        """Return cached detail if still fresh, else None."""
        ts = self._cache_timestamps.get(epic_number, 0.0)
        if time.monotonic() - ts > self._cache_ttl_seconds:
            return None
        return self._detail_cache.get(epic_number)

    async def refresh_cache(self) -> None:
        """Refresh the background cache for all tracked epics.

        Called periodically to avoid N GitHub API calls per dashboard request.
        """
        for epic in self._state.get_all_epic_states().values():
            if epic.closed:
                continue
            try:
                detail = await self._build_detail(epic.epic_number)
                if detail is not None:
                    # Publish progress event
                    await self._bus.publish(
                        HydraFlowEvent(
                            type=EventType.EPIC_PROGRESS,
                            data=EpicProgressPayload(
                                epic_number=epic.epic_number,
                                progress=detail.model_dump(),
                            ),
                        )
                    )
                    # Check and publish readiness (skip already-released epics).
                    # Re-fetch live state to avoid stale snapshot from get_all_epic_states.
                    live_epic = self._state.get_epic_state(epic.epic_number)
                    if (
                        live_epic is not None
                        and not live_epic.released
                        and detail.readiness.all_implemented
                        and detail.readiness.all_approved
                        and detail.readiness.all_ci_passing
                        and detail.readiness.no_conflicts
                    ):
                        await self._bus.publish(
                            HydraFlowEvent(
                                type=EventType.EPIC_READY,
                                data=EpicReadyPayload(
                                    epic_number=epic.epic_number,
                                    readiness=detail.readiness.model_dump(),
                                ),
                            )
                        )
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "Failed to refresh cache for epic #%d, continuing",
                    epic.epic_number,
                    exc_info=True,
                )

    async def _build_detail(self, epic_number: int) -> EpicDetail | None:
        """Build full epic detail by fetching live data from GitHub."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return None

        progress = self.get_progress(epic_number)
        if progress is None:
            return None

        repo = self._config.repo
        fixed_label = self._config.fixed_label[0] if self._config.fixed_label else ""
        children: list[EpicChildInfo] = []
        merged_count = 0
        active_count = 0
        queued_count = 0

        # Worker-truth snapshots (issue #10299): a child is "running" only when
        # a worker actually holds it, and "queued" only when it sits in a stage
        # queue — not because it carries an implement/review label. Parked
        # children appear in neither set, so an all-parked epic reports
        # active=0/queued=0 and the panel reads paused instead of active.
        store = self._issue_store
        worker_held = store.get_worker_held_issues() if store is not None else {}
        queued = store.get_queued_issues() if store is not None else {}

        for child_num in epic.child_issues:
            child_info = await self._build_child_info(
                child_num, epic, repo, fixed_label, worker_held, queued
            )
            # Count by status (failed is tracked via progress.failed; exclude here)
            if child_info.status == EpicChildStatus.DONE:
                merged_count += 1
            elif child_info.status == EpicChildStatus.RUNNING:
                active_count += 1
            # With a store wired, only children genuinely awaiting dispatch
            # count as queued; parked/idle children (in neither worker nor
            # queue set) drop out so the epic reads paused, not queued.
            elif child_info.status != EpicChildStatus.FAILED and (
                store is None or child_info.issue_number in queued
            ):
                queued_count += 1
            children.append(child_info)

        readiness = self._compute_readiness(children, epic)
        release_data = self._get_release_data(epic_number)

        detail = EpicDetail(
            epic_number=epic.epic_number,
            title=epic.title,
            url=f"https://github.com/{repo}/issues/{epic_number}",
            total_children=progress.total_children,
            completed=progress.completed,
            failed=progress.failed,
            in_progress=progress.in_progress,
            merged_children=merged_count,
            active_children=active_count,
            queued_children=queued_count,
            approved=progress.approved,
            ready_to_merge=progress.ready_to_merge,
            status=progress.status,
            percent_complete=progress.percent_complete,
            last_activity=epic.last_activity,
            created_at=epic.created_at,
            auto_decomposed=epic.auto_decomposed,
            merge_strategy=progress.merge_strategy,
            children=children,
            readiness=readiness,
            release=release_data,
        )
        self._detail_cache[epic_number] = detail
        self._cache_timestamps[epic_number] = time.monotonic()
        return detail

    def _compute_readiness(
        self, children: list[EpicChildInfo], epic: EpicState
    ) -> EpicReadiness:
        """Compute epic readiness from child status data."""
        if not children:
            return EpicReadiness()

        all_implemented = all(
            c.status == EpicChildStatus.DONE or c.pr_number is not None
            for c in children
        )
        all_approved = all(
            c.review_status == ReviewStatus.APPROVED for c in children if c.pr_number
        )
        all_ci_passing = all(
            c.ci_status == CIStatus.PASSING for c in children if c.pr_number
        )
        no_conflicts = all(c.mergeable is not False for c in children if c.pr_number)

        version = extract_version_from_title(epic.title)
        changelog_ready = bool(version)

        return EpicReadiness(
            all_implemented=all_implemented,
            all_approved=all_approved,
            all_ci_passing=all_ci_passing,
            no_conflicts=no_conflicts,
            changelog_ready=changelog_ready,
            version=version or None,
        )

    def _get_release_data(self, epic_number: int) -> dict[str, object] | None:
        """Return release info dict if a release exists for this epic."""
        release = self._state.get_release(epic_number)
        if release is None:
            return None
        return {
            "version": release.version,
            "tag": release.tag,
            "released_at": release.released_at,
            "status": release.status,
        }
