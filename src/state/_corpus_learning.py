"""CorpusLearningLoop state: per-escape self-validation attempt counter.

Spec §4.1 v2 step 5: "Self-validation failure 3× on the same escape
issue → label it `hitl-escalation`, `corpus-learning-stuck`, record
the three rejected attempts in the issue body, move on."

The counter is keyed by escape-issue number (as a string for JSON
round-trip parity with other counter dicts in StateData).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class CorpusLearningStateMixin:
    """Per-escape validation-failure counter for CorpusLearningLoop."""

    _data: StateData

    def save(self) -> None: ...  # provided by core StateTracker

    def get_corpus_validation_attempts(self, issue_number: int) -> int:
        return self._data.corpus_learning_validation_attempts.get(str(issue_number), 0)

    def increment_corpus_validation_attempts(self, issue_number: int) -> int:
        """Bump the per-issue counter and return the new value."""
        key = str(issue_number)
        current = self._data.corpus_learning_validation_attempts.get(key, 0) + 1
        self._data.corpus_learning_validation_attempts[key] = current
        self.save()
        return current

    def reset_corpus_validation_attempts(self, issue_number: int) -> None:
        """Drop the counter for *issue_number* — invoked when the
        escalation issue closes (spec §3.2 lifecycle)."""
        self._data.corpus_learning_validation_attempts.pop(str(issue_number), None)
        self.save()
