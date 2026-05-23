"""Onboarding wizard draft state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models import StateData


class OnboardingStateMixin:
    """Persist onboarding draft payloads in the shared StateTracker store."""

    _data: StateData

    def save(self) -> None: ...  # provided by core StateTracker

    def list_onboarding_drafts(self) -> list[dict[str, Any]]:
        return list(self._data.onboarding_drafts.values())

    def get_onboarding_draft(self, draft_id: str) -> dict[str, Any] | None:
        draft = self._data.onboarding_drafts.get(draft_id)
        return dict(draft) if draft is not None else None

    def set_onboarding_draft(self, draft_id: str, draft: dict[str, Any]) -> None:
        self._data.onboarding_drafts[draft_id] = dict(draft)
        self.save()
