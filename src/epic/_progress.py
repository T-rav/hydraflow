"""Epic progress: the counted view of an epic and its freshness test.

``_is_stale`` lives here rather than with the stale sweep because it is
the predicate ``get_progress`` stamps onto every row; the sweep is one
caller of it, not its owner.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from config import HydraFlowConfig
from models import (
    EpicProgress,
    EpicState,
    EpicStatus,
    MergeStrategy,
)
from state import StateTracker

logger = logging.getLogger("hydraflow.epic")


class EpicProgressMixin:
    """Epic progress: the counted view of an epic and its freshness test."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``EpicManager.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _state: StateTracker

    def get_progress(self, epic_number: int) -> EpicProgress | None:
        """Compute progress from persisted state."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return None

        p = epic.progress  # {total, completed, failed, excluded, approved, remaining}
        total = p["total"]
        completed = p["completed"]
        failed = p["failed"]
        excluded = p["excluded"]
        approved = p["approved"]
        in_progress = total - completed - failed - excluded

        if epic.closed:
            status = EpicStatus.COMPLETED
        elif failed > 0 and in_progress == 0:
            status = EpicStatus.BLOCKED
        elif self._is_stale(epic):
            status = EpicStatus.STALE
        else:
            status = EpicStatus.ACTIVE

        resolved = completed + excluded
        pct = (resolved / total * 100) if total > 0 else 0.0
        strategy = epic.merge_strategy

        # Ready to merge when all children are approved or already merged,
        # the strategy is not independent, and the epic has not yet been released.
        ready_to_merge = (
            total > 0
            and failed == 0
            and not epic.released
            and strategy != MergeStrategy.INDEPENDENT
            and all(
                c in epic.approved_children or c in epic.completed_children
                for c in epic.child_issues
            )
        )

        return EpicProgress(
            epic_number=epic.epic_number,
            title=epic.title,
            total_children=total,
            completed=completed,
            failed=failed,
            excluded=excluded,
            in_progress=max(in_progress, 0),
            approved=approved,
            ready_to_merge=ready_to_merge,
            merge_strategy=strategy,
            status=status,
            percent_complete=round(pct, 1),
            last_activity=epic.last_activity,
            auto_decomposed=epic.auto_decomposed,
            child_issues=list(epic.child_issues),
        )

    def get_all_progress(self) -> list[EpicProgress]:
        """Return progress for all tracked epics (for dashboard API)."""
        results: list[EpicProgress] = []
        for epic in self._state.get_all_epic_states().values():
            try:
                progress = self.get_progress(epic.epic_number)
                if progress is not None:
                    results.append(progress)
            except Exception:
                logger.warning(
                    "Failed to get progress for epic #%d, continuing",
                    epic.epic_number,
                    exc_info=True,
                )
        return results

    def _is_stale(self, epic: EpicState) -> bool:
        """Return True if the epic has had no activity within the stale threshold."""
        try:
            last = datetime.fromisoformat(epic.last_activity)
            cutoff = datetime.now(UTC) - timedelta(days=self._config.epic_stale_days)
            return last < cutoff
        except (ValueError, TypeError):
            return False
