"""Review attempt, feedback, and last-reviewed-SHA state."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class ReviewStateMixin:
    """Methods for review attempts, feedback, and last-reviewed SHA."""

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

        @staticmethod
        def _key(issue_id: int | str) -> str: ...

    # --- review feedback storage ---

    def set_review_feedback(self, issue_number: int, feedback: str) -> None:
        """Store review feedback for *issue_number*."""
        self._data.review_feedback[self._key(issue_number)] = feedback
        self.save()

    def get_review_feedback(self, issue_number: int) -> str | None:
        """Return stored review feedback for *issue_number*, or *None*."""
        return self._data.review_feedback.get(self._key(issue_number))

    def clear_review_feedback(self, issue_number: int) -> None:
        """Clear stored review feedback for *issue_number*."""
        self._data.review_feedback.pop(self._key(issue_number), None)
        self.save()

    # --- last reviewed SHA tracking ---

    def set_last_reviewed_sha(self, issue_number: int, sha: str) -> None:
        """Record the last-reviewed commit SHA for *issue_number*."""
        self._data.last_reviewed_shas[self._key(issue_number)] = sha
        self.save()

    def get_last_reviewed_sha(self, issue_number: int) -> str | None:
        """Return the last-reviewed commit SHA for *issue_number*, or *None*."""
        return self._data.last_reviewed_shas.get(self._key(issue_number))

    def clear_last_reviewed_sha(self, issue_number: int) -> None:
        """Clear the last-reviewed commit SHA for *issue_number*."""
        self._data.last_reviewed_shas.pop(self._key(issue_number), None)
        self.save()
