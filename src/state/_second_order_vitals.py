"""State accessors for SecondOrderVitalsLoop (#10373).

Two fields — the per-series observation histories the Shewhart individuals
charts are baselined from, and the last verdict (episode boundary for the
single diverging alarm):

* ``second_order_vitals_series_history`` — ``{series_name: [reading, …]}``, one
  bounded per-window observation list per input series (oldest → newest). This
  IS the baseline: each series' control limit is computed from its own history,
  so persisting the readings is what lets ``watch``/``diverging`` require
  sustained drift across windows rather than re-deriving from scratch each tick.
* ``second_order_vitals_last_verdict`` — the previous tick's verdict token, so
  the diverging alarm fires exactly once on the transition INTO ``diverging``
  (the episode boundary) and not every subsequent tick while it persists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class SecondOrderVitalsStateMixin:
    """Per-series observation histories + last-verdict episode state."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_second_order_vitals_series_history(self) -> dict[str, list[float]]:
        return {
            series: list(values)
            for series, values in self._data.second_order_vitals_series_history.items()
        }

    def set_second_order_vitals_series_history(
        self, history: dict[str, list[float]]
    ) -> None:
        self._data.second_order_vitals_series_history = {
            series: list(values) for series, values in history.items()
        }
        self.save()

    def get_second_order_vitals_last_verdict(self) -> str:
        return self._data.second_order_vitals_last_verdict

    def set_second_order_vitals_last_verdict(self, verdict: str) -> None:
        self._data.second_order_vitals_last_verdict = verdict
        self.save()
