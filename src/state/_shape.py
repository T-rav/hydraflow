"""Shape conversation state: persistence for multi-turn design conversations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import ShapeConversation, StateData


class ShapeStateMixin:
    """Methods for persisting shape conversation state."""

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

        @staticmethod
        def _key(issue_id: int | str) -> str: ...

    def set_shape_conversation(
        self, issue_number: int, conversation: ShapeConversation
    ) -> None:
        """Save or update a shape conversation for *issue_number*."""
        self._data.shape_conversations[self._key(issue_number)] = conversation
        self.save()

    def get_shape_conversation(self, issue_number: int) -> ShapeConversation | None:
        """Return the shape conversation for *issue_number*, or *None*."""
        return self._data.shape_conversations.get(self._key(issue_number))

    def remove_shape_conversation(self, issue_number: int) -> None:
        """Clear the shape conversation for *issue_number*."""
        self._data.shape_conversations.pop(self._key(issue_number), None)
        self.save()

    def set_shape_response(self, issue_number: int, response: str) -> None:
        """Store a human response for a shape conversation (from dashboard/WhatsApp)."""
        self._data.shape_responses[self._key(issue_number)] = response
        self.save()

    def get_shape_response(self, issue_number: int) -> str | None:
        """Return a pending shape response for *issue_number*, or *None*."""
        return self._data.shape_responses.get(self._key(issue_number))

    def clear_shape_response(self, issue_number: int) -> None:
        """Clear a consumed shape response."""
        self._data.shape_responses.pop(self._key(issue_number), None)
        self.save()
