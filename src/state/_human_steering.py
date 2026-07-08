"""HumanSteeringLoop per-issue steering reference accessors (ADR-0099 #4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import SteeringState

if TYPE_CHECKING:
    from models import StateData


class HumanSteeringStateMixin:
    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_human_steering(self, issue: str) -> SteeringState:
        return self._data.human_steering.get(issue, SteeringState())

    def set_human_steering(self, issue: str, state: SteeringState) -> None:
        self._data.human_steering[issue] = state
        self.save()
