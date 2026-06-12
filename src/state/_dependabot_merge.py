"""State accessors for bot PR auto-merge settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import DependabotMergeSettings

if TYPE_CHECKING:
    from models import StateData


class DependabotMergeStateMixin:
    """Mixed into StateTracker for bot PR settings persistence."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_dependabot_merge_settings(self) -> DependabotMergeSettings:
        """Return current bot PR settings."""
        return DependabotMergeSettings.model_validate(
            self._data.dependabot_merge_settings.model_dump()
        )

    def set_dependabot_merge_settings(self, settings: DependabotMergeSettings) -> None:
        """Persist bot PR settings."""
        self._data.dependabot_merge_settings = settings
        self.save()

    def get_dependabot_merge_processed(self) -> set[int]:
        """Return set of PR numbers already processed by the bot PR worker."""
        return set(self._data.dependabot_merge_processed)

    def add_dependabot_merge_processed(self, pr_number: int) -> None:
        """Mark a PR as processed (merged, closed, or escalated).

        Also clears any arch-staleness self-heal counter for the PR: a
        merged/closed/escalated PR will not be re-processed under the same
        number, and clearing keeps the counter dict from growing unbounded.
        """
        current = set(self._data.dependabot_merge_processed)
        current.add(pr_number)
        self._data.dependabot_merge_processed = sorted(current)
        self._data.dependabot_arch_refresh_attempts.pop(str(pr_number), None)
        self.save()

    def get_dependabot_arch_refresh_attempts(self, pr_number: int) -> int:
        """Return how many arch-staleness self-heal refreshes have run on *pr_number*."""
        return self._data.dependabot_arch_refresh_attempts.get(str(pr_number), 0)

    def bump_dependabot_arch_refresh_attempts(self, pr_number: int) -> int:
        """Increment and return the arch-staleness refresh count for *pr_number*."""
        key = str(pr_number)
        new_count = self._data.dependabot_arch_refresh_attempts.get(key, 0) + 1
        self._data.dependabot_arch_refresh_attempts[key] = new_count
        self.save()
        return new_count

    def clear_dependabot_arch_refresh_attempts(self, pr_number: int) -> None:
        """Drop the arch-staleness refresh counter for *pr_number* (no-op if absent)."""
        if str(pr_number) in self._data.dependabot_arch_refresh_attempts:
            del self._data.dependabot_arch_refresh_attempts[str(pr_number)]
            self.save()
