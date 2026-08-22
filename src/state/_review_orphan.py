"""Review-orphan requeue counters (#9815).

A factory restart mid-implement can leave an issue review-labeled with no
open ``agent/issue-N`` PR — unreviewable and never requeued. These counters
let the review loop distinguish "PR not propagated yet" (strikes below the
threshold) from a genuine orphan (requeue with fresh budget, bounded before
HITL escalation). Persisted so a crash cannot reset the bound.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class ReviewOrphanStateMixin:
    """Per-issue strike + requeue counters for PR-less review issues."""

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

        @staticmethod
        def _key(issue_id: int | str) -> str: ...

    def increment_review_orphan_strike(self, issue_id: int) -> int:
        """Record one PR-less sighting; returns the new strike count."""
        key = self._key(issue_id)
        new = self._data.review_orphan_strikes.get(key, 0) + 1
        self._data.review_orphan_strikes[key] = new
        self.save()
        return new

    def clear_review_orphan_strikes(self, issue_id: int) -> None:
        """Reset strikes (PR appeared, or a requeue was performed)."""
        if self._data.review_orphan_strikes.pop(self._key(issue_id), None) is not None:
            self.save()

    def increment_review_orphan_requeue(self, issue_id: int) -> int:
        """Record one orphan requeue; returns the new requeue count."""
        key = self._key(issue_id)
        new = self._data.review_orphan_requeues.get(key, 0) + 1
        self._data.review_orphan_requeues[key] = new
        self.save()
        return new

    def get_review_orphan_requeues(self, issue_id: int) -> int:
        return self._data.review_orphan_requeues.get(self._key(issue_id), 0)
