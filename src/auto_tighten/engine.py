from __future__ import annotations

from functools import reduce

from auto_tighten.models import Measurement, Observation
from auto_tighten.ratchet_adapter import RatchetAdapter


class MonotoneViolation(RuntimeError):
    """Raised if a non-tightening value ever reaches actuation."""


class TighteningEngine:
    def classify(
        self, adapter: RatchetAdapter, current: Measurement, baseline: Measurement
    ) -> str:
        if adapter.is_tighter(current, baseline):
            return "tighter"
        if adapter.is_tighter(baseline, current):
            return "looser"
        return "same"

    def confirm(
        self,
        adapter: RatchetAdapter,
        window: list[Observation],
        baseline: Measurement,
        stability_ticks: int,
    ) -> Measurement | None:
        if stability_ticks < 1:
            raise ValueError(f"stability_ticks must be >= 1, got {stability_ticks}")
        if len(window) < stability_ticks:
            return None
        recent = window[-stability_ticks:]
        folded = reduce(adapter.weakest, (o.current for o in recent))
        proposed = adapter.apply_margin(folded)
        if not adapter.is_tighter(proposed, baseline):
            return None
        return proposed

    def guard_is_tighter(
        self, adapter: RatchetAdapter, candidate: Measurement, baseline: Measurement
    ) -> None:
        if not adapter.is_tighter(candidate, baseline):
            raise MonotoneViolation(
                f"{adapter.ratchet_id}: refusing non-tightening value {candidate!r} vs {baseline!r}"
            )
