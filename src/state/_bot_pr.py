"""State accessors for bot PR auto-merge settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import BotPRSettings

if TYPE_CHECKING:
    from models import StateData


class BotPRStateMixin:
    """Mixed into StateTracker for bot PR settings persistence."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_bot_pr_settings(self) -> BotPRSettings:
        """Return current bot PR settings."""
        return BotPRSettings.model_validate(self._data.bot_pr_settings.model_dump())

    def set_bot_pr_settings(self, settings: BotPRSettings) -> None:
        """Persist bot PR settings."""
        self._data.bot_pr_settings = settings
        self.save()

    def get_bot_pr_processed(self) -> set[int]:
        """Return set of PR numbers already processed by the bot PR worker."""
        return set(self._data.bot_pr_processed)

    def add_bot_pr_processed(self, pr_number: int) -> None:
        """Mark a PR as processed (merged, closed, or escalated)."""
        current = set(self._data.bot_pr_processed)
        current.add(pr_number)
        self._data.bot_pr_processed = sorted(current)
        self.save()
