"""The child-lifecycle callbacks: what an epic does when one of its issues
moves.

Five entry points driven by the label state machine (ADR-0002) plus the
auto-close they can trigger. They break together because they share one
invariant — every one of them must invalidate the cache and publish an
update, and a new callback that forgets is invisible until the dashboard
goes stale.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from models import (
    EpicProgress,
    MergeStrategy,
)
from pr_manager import PRManager
from state import StateTracker

if TYPE_CHECKING:
    from ._completion import EpicCompletionChecker

logger = logging.getLogger("hydraflow.epic")


class EpicChildEventsMixin:
    """The child-lifecycle callbacks: what an epic does when one of its issues"""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``EpicManager.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _checker: EpicCompletionChecker
    _prs: PRManager
    _state: StateTracker

    if TYPE_CHECKING:

        async def _handle_bundled_hitl_ready(
            self, epic_number: int
        ) -> None: ...  # provided by _merge_order

        async def _handle_bundled_ready(
            self, epic_number: int
        ) -> None: ...  # provided by _merge_order

        async def _handle_ordered_ready(
            self, epic_number: int
        ) -> None: ...  # provided by _merge_order

        def _invalidate_cache(
            self, epic_number: int
        ) -> None: ...  # provided by _manager

        async def _publish_update(
            self, epic_number: int, action: str
        ) -> None: ...  # provided by _manager

        def get_progress(
            self, epic_number: int
        ) -> EpicProgress | None: ...  # provided by _progress

    async def on_child_planned(self, epic_number: int, child_number: int) -> None:
        """Update last_activity when a child issue completes planning."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return
        epic.last_activity = datetime.now(UTC).isoformat()
        self._state.upsert_epic_state(epic)
        self._invalidate_cache(epic_number)
        logger.debug(
            "Epic #%d child #%d planned — updated last_activity",
            epic_number,
            child_number,
        )

    async def on_child_approved(self, epic_number: int, child_number: int) -> None:
        """Record that a child's PR was approved (not yet merged).

        For bundled strategies, this is the trigger to check if all siblings
        are approved and optionally auto-merge or escalate for human review.
        """
        self._state.mark_epic_child_approved(epic_number, child_number)
        self._invalidate_cache(epic_number)
        await self._publish_update(epic_number, "child_approved")
        logger.info("Epic #%d child #%d approved", epic_number, child_number)

        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return

        if epic.released:
            return

        strategy = epic.merge_strategy
        if strategy == MergeStrategy.INDEPENDENT:
            return

        progress = self.get_progress(epic_number)
        if progress is None or not progress.ready_to_merge:
            return

        if strategy == MergeStrategy.BUNDLED:
            await self._handle_bundled_ready(epic_number)
        elif strategy == MergeStrategy.BUNDLED_HITL:
            await self._handle_bundled_hitl_ready(epic_number)
        elif strategy == MergeStrategy.ORDERED:
            await self._handle_ordered_ready(epic_number)

    async def on_child_completed(self, epic_number: int, child_number: int) -> None:
        """Record child completion and attempt auto-close."""
        self._state.mark_epic_child_complete(epic_number, child_number)
        self._invalidate_cache(epic_number)
        await self._publish_update(epic_number, "child_completed")
        logger.info(
            "Epic #%d child #%d completed",
            epic_number,
            child_number,
        )
        await self._try_auto_close(epic_number)

    async def on_child_failed(self, epic_number: int, child_number: int) -> None:
        """Record a child failure."""
        self._state.mark_epic_child_failed(epic_number, child_number)
        self._invalidate_cache(epic_number)
        await self._publish_update(epic_number, "child_failed")
        logger.info(
            "Epic #%d child #%d failed",
            epic_number,
            child_number,
        )

    async def on_child_excluded(self, epic_number: int, child_number: int) -> None:
        """Record a child exclusion (closed without merge) and attempt auto-close."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return
        if child_number not in epic.excluded_children:
            epic.excluded_children.append(child_number)
            epic.last_activity = datetime.now(UTC).isoformat()
            self._state.upsert_epic_state(epic)
        await self._publish_update(epic_number, "child_excluded")
        logger.info(
            "Epic #%d child #%d excluded (closed without merge)",
            epic_number,
            child_number,
        )
        await self._try_auto_close(epic_number)

    async def _propagate_epic_close(self, epic_number: int) -> None:
        """When *epic_number* (a decompose replacement) closes, record its
        superseded child completed in the parent epic and re-run the parent's
        auto-close. on_child_completed → _try_auto_close → (if it closes the
        parent) this helper again → recursion up the parent_epic chain until the
        root (parent_epic None). Inert for every ordinary epic (#9757)."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None or epic.parent_epic is None or epic.superseded_issue is None:
            return
        await self.on_child_completed(epic.parent_epic, epic.superseded_issue)

    async def _try_auto_close(self, epic_number: int) -> None:
        """Attempt to auto-close an epic if all children are resolved."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None or epic.closed:
            return

        all_children = set(epic.child_issues)
        if not all_children or not all_children.issubset(epic.resolved_children):
            return

        # Try the full checker workflow (body update, label, release).
        # close_specific_epic returns True (closed), False (not ready), or
        # None (epic not found on GitHub).
        result = await self._checker.close_specific_epic(epic_number)
        if result is True:
            self._state.close_epic(epic_number)
            await self._publish_update(epic_number, "closed")
            logger.info("Epic #%d auto-closed — all children resolved", epic_number)
            await self._propagate_epic_close(epic_number)
            return

        if result is False:
            # Checker found the epic but sub-issues are not all resolved
            # on GitHub — respect GitHub as source of truth.
            logger.warning(
                "Epic #%d: GitHub sub-issues not all resolved — skipping auto-close",
                epic_number,
            )
            return

        # Epic not found on GitHub — fall back to direct close.
        try:
            await self._prs.post_comment(
                epic_number,
                "All child issues completed — closing epic automatically.",
            )
            await self._prs.close_issue(epic_number)
        except RuntimeError:
            logger.warning(
                "Direct close failed for epic #%d",
                epic_number,
                exc_info=True,
            )
            return

        self._state.close_epic(epic_number)
        await self._publish_update(epic_number, "closed")
        logger.info("Epic #%d auto-closed — all children resolved", epic_number)
        await self._propagate_epic_close(epic_number)
