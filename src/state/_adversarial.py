"""Per-issue AdversarialState persistence (earlier-adversarial pipeline).

The earlier-adversarial pipeline persists one ``AdversarialState`` per
issue into ``state.json`` so each pipeline phase can read carryover
concerns surfaced in earlier phases without re-running their stages.

Storage: ``StateData.adversarial_states`` (``dict[str, AdversarialState]``).
Schema-evolution safe: legacy state files load cleanly because the
field defaults to an empty dict on the StateData model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from models import StateData
    from pending_concerns import AdversarialState

_V = TypeVar("_V")


class AdversarialStateMixin:
    """Mixin for reading/writing per-issue AdversarialState."""

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

        @staticmethod
        def _key(issue_id: int | str) -> str: ...

    def set_adversarial_state(
        self, issue_number: int, adversarial_state: AdversarialState
    ) -> None:
        """Persist *adversarial_state* for *issue_number*.

        Called by each adversarial stage after it finishes (success or
        exhaustion) so the next stage can read the accumulated pending
        concerns. Per dark-factory contract: every stage persists before
        returning.
        """
        self._data.adversarial_states[self._key(issue_number)] = adversarial_state
        self.save()

    def get_adversarial_state(self, issue_number: int) -> AdversarialState | None:
        """Return the persisted ``AdversarialState`` for *issue_number*, or None."""
        return self._data.adversarial_states.get(self._key(issue_number))

    def clear_adversarial_state(self, issue_number: int) -> None:
        """Remove the persisted ``AdversarialState`` for *issue_number*."""
        self._data.adversarial_states.pop(self._key(issue_number), None)
        self.save()
