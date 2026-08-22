"""HumanSteeringLoop per-issue steering reference accessors (ADR-0099 #4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import SteeringState

if TYPE_CHECKING:
    from models import StateData


class HumanSteeringStateMixin:
    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

    def get_human_steering(self, issue: str) -> SteeringState:
        return self._data.human_steering.get(issue, SteeringState())

    def get_all_human_steering(self) -> dict[str, SteeringState]:
        """Return every per-issue steering directive (read-only snapshot copy).

        Used by InterventionTallyLoop (#10369) to sense steering interventions
        across the whole backlog. A shallow copy so callers cannot mutate the
        persisted map through the returned dict.
        """
        return dict(self._data.human_steering)

    def set_human_steering(self, issue: str, state: SteeringState) -> None:
        self._data.human_steering[issue] = state
        self.save()
