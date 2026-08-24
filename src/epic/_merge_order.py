"""Merge coordination (ADR-0012): what an approved child means under each
merge strategy.

The three ``_handle_*_ready`` paths are one decision spelled three ways,
and they share ``_get_merge_order`` and ``_publish_ready_event``. Adding a
fourth ``MergeStrategy`` touches every method in this file and nothing
outside it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from events import EventBus, EventType, HydraFlowEvent
from models import (
    EpicProgress,
    EpicReadyPayload,
    EpicState,
)
from pr_manager import PRManager
from state import StateTracker

logger = logging.getLogger("hydraflow.epic")


class EpicMergeOrderMixin:
    """Merge coordination (ADR-0012): what an approved child means under each merge strategy."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``EpicManager.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _bus: EventBus
    _prs: PRManager
    _state: StateTracker

    if TYPE_CHECKING:

        def get_progress(
            self, epic_number: int
        ) -> EpicProgress | None: ...  # provided by _progress

        async def release_epic(
            self, epic_number: int
        ) -> dict[str, object]: ...  # provided by _release

    def _get_merge_order(self, epic: EpicState) -> list[int]:
        """Return child issues that still need merging, in their registered order.

        Returns children that are not yet completed, preserving the order they
        were registered in ``child_issues``.

        Note: BLOCKS/BLOCKED_BY dependency ordering is not yet implemented.
        For the "ordered" strategy, ensure children are registered in the
        correct dependency order at registration time.
        """
        return [c for c in epic.child_issues if c not in epic.completed_children]

    async def _handle_bundled_ready(self, epic_number: int) -> None:
        """All siblings approved — merge all in sequence automatically."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return
        merge_order = self._get_merge_order(epic)
        logger.info(
            "Epic #%d: all children approved — auto-merging %d PRs (bundled)",
            epic_number,
            len(merge_order),
        )
        await self._publish_ready_event(epic_number, "bundled")
        await self._prs.post_comment(
            epic_number,
            "## Epic Bundle Ready\n\n"
            "All sub-issues are approved and CI is passing. "
            "Merging all PRs automatically (bundled strategy).\n\n"
            "---\n*HydraFlow Epic Coordinator*",
        )
        result = await self.release_epic(epic_number)
        if "error" in result:
            logger.warning(
                "Epic #%d bundled release failed: %s", epic_number, result["error"]
            )
            await self._prs.post_comment(
                epic_number,
                f"## Epic Bundle Release Failed\n\n"
                f"Auto-merge encountered an error: {result['error']}\n\n"
                f"Please resolve any merge conflicts and retry via the dashboard "
                f"or `POST /api/epics/{epic_number}/release`.\n\n"
                "---\n*HydraFlow Epic Coordinator*",
            )

    async def _handle_bundled_hitl_ready(self, epic_number: int) -> None:
        """All siblings approved — pause and notify for human review."""
        logger.info(
            "Epic #%d: all children approved — awaiting human release (bundled_hitl)",
            epic_number,
        )
        await self._publish_ready_event(epic_number, "bundled_hitl")
        await self._prs.post_comment(
            epic_number,
            "## Epic Bundle Ready for Release\n\n"
            "All sub-issues are approved and CI is passing. "
            "Awaiting human confirmation to merge.\n\n"
            "Use the dashboard **Merge & Release** button or "
            f"`POST /api/epics/{epic_number}/release` to trigger the merge.\n\n"
            "---\n*HydraFlow Epic Coordinator*",
        )

    async def _handle_ordered_ready(self, epic_number: int) -> None:
        """All siblings approved — merge in dependency order."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return
        merge_order = self._get_merge_order(epic)
        logger.info(
            "Epic #%d: all children approved — merging in dependency order (%d PRs)",
            epic_number,
            len(merge_order),
        )
        await self._publish_ready_event(epic_number, "ordered")
        await self._prs.post_comment(
            epic_number,
            "## Epic Bundle Ready (Ordered)\n\n"
            "All sub-issues are approved and CI is passing. "
            "Merging PRs in dependency order.\n\n"
            "---\n*HydraFlow Epic Coordinator*",
        )
        result = await self.release_epic(epic_number)
        if "error" in result:
            logger.warning(
                "Epic #%d ordered release failed: %s", epic_number, result["error"]
            )
            await self._prs.post_comment(
                epic_number,
                f"## Epic Bundle Release Failed (Ordered)\n\n"
                f"Auto-merge encountered an error: {result['error']}\n\n"
                f"Please resolve any merge conflicts and retry via the dashboard "
                f"or `POST /api/epics/{epic_number}/release`.\n\n"
                "---\n*HydraFlow Epic Coordinator*",
            )

    async def _publish_ready_event(self, epic_number: int, strategy: str) -> None:
        """Publish an EPIC_READY event when all children are approved."""
        progress = self.get_progress(epic_number)
        data: EpicReadyPayload = {
            "epic_number": epic_number,
            "strategy": strategy,
        }
        if progress is not None:
            data["progress"] = progress.model_dump()
        await self._bus.publish(HydraFlowEvent(type=EventType.EPIC_READY, data=data))
