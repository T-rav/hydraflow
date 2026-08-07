"""Settling-window sensing (#10825, rung 1) — don't read your own actuation.

Mechanism 2 of the stillness umbrella (#10819): sensors read the process variable
and the control output *blended* — a merge perturbs the very metrics loops read,
so no loop can tell "the plant changed" from "I changed the plant." The fix is a
ladder of increasing fidelity (ADR-0120: *respond to innovations, not
measurements*); this is the lowest, crudest rung, and the one already on #10819's
gated-damper list:

  **Settling window** — after actuating in an area, do not treat readings from
  that area as signal for a settling window. It discards information (a real
  disturbance during the window is missed), which is why it is only rung 1; but
  it is dead simple and cannot itself introduce a model error, so it is the safe
  first move before expected-footprint discounting (rung 2, Smith predictor) and
  innovation-based sensing (rung 3, Kalman).

Pure engine: given the actuations (each merge, the areas it touched, when) and
the sensor readings, it partitions readings into *signal* (outside any settling
window) and *settling* (suppressed as likely self-effect). Loading actuations
from the merge history and areas from the erosion classifier is the caller's job.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

#: Days after an actuation during which readings from that area are suppressed.
DEFAULT_SETTLING_DAYS = 3


@dataclass(frozen=True)
class Actuation:
    """One control output: a merge that touched ``area`` on ``day``."""

    area: str
    day: int


@dataclass(frozen=True)
class Reading:
    """One sensor reading: ``value`` for ``area`` on ``day``."""

    area: str
    day: int
    value: float


def is_settling(
    area: str,
    day: int,
    actuations: Iterable[Actuation],
    *,
    window: int = DEFAULT_SETTLING_DAYS,
) -> bool:
    """True when ``area`` was actuated within the ``window`` days up to ``day``.

    A reading in a settling window is likely the loop's own actuation echoing
    back, not an independent disturbance — so it must not be trusted as signal.
    Only actuations at or before the reading count (a future merge cannot have
    perturbed a past reading).
    """
    return any(a.area == area and 0 <= day - a.day < window for a in actuations)


def partition_readings(
    readings: Sequence[Reading],
    actuations: Sequence[Actuation],
    *,
    window: int = DEFAULT_SETTLING_DAYS,
) -> tuple[list[Reading], list[Reading]]:
    """Split readings into ``(signal, suppressed)``.

    ``signal`` are the readings outside every settling window — the ones a loop
    may act on. ``suppressed`` are inside a settling window and discarded as
    likely self-effect.
    """
    signal: list[Reading] = []
    suppressed: list[Reading] = []
    for r in readings:
        target = (
            suppressed
            if is_settling(r.area, r.day, actuations, window=window)
            else signal
        )
        target.append(r)
    return signal, suppressed


@dataclass(frozen=True)
class SettlingReport:
    """Coverage of the settling filter over one batch of readings."""

    total: int
    signal_count: int
    suppressed_count: int
    suppressed_areas: tuple[str, ...]


def settling_report(
    readings: Sequence[Reading],
    actuations: Sequence[Actuation],
    *,
    window: int = DEFAULT_SETTLING_DAYS,
) -> SettlingReport:
    """Summarize how many readings the settling filter suppressed, and where."""
    signal, suppressed = partition_readings(readings, actuations, window=window)
    areas = tuple(sorted({r.area for r in suppressed}))
    return SettlingReport(
        total=len(readings),
        signal_count=len(signal),
        suppressed_count=len(suppressed),
        suppressed_areas=areas,
    )
