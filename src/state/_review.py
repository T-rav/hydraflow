"""Review attempt, feedback, and last-reviewed-SHA state."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class ReviewStateMixin:
    """Methods for review attempts, feedback, and last-reviewed SHA."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker

    # --- review attempt tracking ---

    def get_review_attempts(self, issue_number: int) -> int:
        """Return the current review attempt count for *issue_number* (default 0)."""
        return self._data.review_attempts.get(self._key(issue_number), 0)

    def increment_review_attempts(self, issue_number: int) -> int:
        """Increment and return the new review attempt count for *issue_number*."""
        key = self._key(issue_number)
        current = self._data.review_attempts.get(key, 0)
        self._data.review_attempts[key] = current + 1
        self.save()
        return current + 1

    def reset_review_attempts(self, issue_number: int) -> None:
        """Clear the review attempt counter for *issue_number*."""
        self._data.review_attempts.pop(self._key(issue_number), None)
        self.save()

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

    # --- blast radius ---

    def set_review_blast_radius(self, issue_number: int, radius: str) -> None:
        """Record the blast-radius tier for *issue_number*."""
        self._data.review_blast_radii[self._key(issue_number)] = radius
        self.save()

    def get_review_blast_radius(self, issue_number: int) -> str | None:
        """Return the blast-radius tier for *issue_number*, or *None*."""
        return self._data.review_blast_radii.get(self._key(issue_number))

    def min_review_passes_required(self, issue_number: int) -> int:
        """Return the minimum fresh-eyes review passes for *issue_number*.

        Defaults to 1 (low) when no blast radius has been recorded yet.
        Delegates the tier->count mapping to ``review_advisor`` so there is a
        single source of truth (ADR-0051 stratified table).
        """
        from review_advisor import (  # noqa: PLC0415
            min_review_passes_for_blast_radius,
        )

        radius = self._data.review_blast_radii.get(self._key(issue_number), "low")
        if radius not in ("low", "medium", "high"):
            radius = "low"
        return min_review_passes_for_blast_radius(radius)  # type: ignore[arg-type]
