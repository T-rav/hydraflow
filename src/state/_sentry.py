"""Sentry ingestion state — creation attempt + per-issue cooldown tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class SentryStateMixin:
    """State methods for the Sentry ingestion loop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def fail_sentry_creation(self, sentry_id: str) -> int:
        """Increment creation attempt count for a Sentry issue. Returns new count."""
        current = self._data.sentry_creation_attempts.get(sentry_id, 0)
        current += 1
        self._data.sentry_creation_attempts[sentry_id] = current
        self.save()
        return current

    def get_sentry_creation_attempts(self, sentry_id: str) -> int:
        """Return the number of creation attempts for a Sentry issue."""
        return self._data.sentry_creation_attempts.get(sentry_id, 0)

    def clear_sentry_creation_attempts(self, sentry_id: str) -> None:
        """Clear creation attempt tracking for a Sentry issue."""
        self._data.sentry_creation_attempts.pop(sentry_id, None)
        self.save()

    # ------------------------------------------------------------- cooldown
    def stamp_sentry_cooldown(self, sentry_id: str) -> None:
        """Record now() as the last filing-attempt time for a Sentry issue.

        Persisted in ``StateData`` so the cooldown survives restarts. Used to
        suppress re-filing the same Sentry issue every poll while a recently
        attempted/filed error is still flapping in the unresolved feed.
        """
        self._data.sentry_signal_cooldown[sentry_id] = datetime.now(UTC).isoformat()
        self.save()

    def get_sentry_cooldown_stamp(self, sentry_id: str) -> str:
        """Return the ISO timestamp of the last filing attempt, or '' if none."""
        return self._data.sentry_signal_cooldown.get(sentry_id, "")

    def clear_sentry_cooldown(self, sentry_id: str) -> None:
        """Clear the cooldown stamp for a Sentry issue."""
        self._data.sentry_signal_cooldown.pop(sentry_id, None)
        self.save()
