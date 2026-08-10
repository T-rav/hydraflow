"""Expected-footprint discounting (#10825, rung 2) — a Smith-predictor move.

Rung 2 of the stillness sensing ladder (#10819, ADR-0120: *respond to innovations,
not measurements*). Rung 1 ([[settling.py]]) is binary — it discards EVERY reading
in a window after actuation, losing a real disturbance that happens to land in
that window. Rung 2 keeps the information: every merge ships an EXPECTED FOOTPRINT
(which areas move, by how much), the sensor subtracts the predicted movement, and
only the unexplained RESIDUAL — the surprise — counts as signal. That is the
classical Smith predictor: model the known effect of your own actuation and
respond to what the model did not predict.

Because the footprint is predicted by a generative agent (the convergence
pipeline's per-change expectation, already in the exhaust), not derived from an
identified plant model, its accuracy is not assumed: :func:`footprint_accuracy`
turns predicted-vs-actual into a measurable 0..1 series per merge — the free
calibration signal rung 3 (Kalman) needs.

Pure engine: given a merge's expected footprint and the observed per-area
movement, it returns the residuals and flags the surprising areas. Loading the
footprint from the convergence exhaust and the observed movement from the sensors
is the caller's job.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

#: A generative footprint is approximate. An observed movement within this
#: relative tolerance of its prediction reads as *explained* (self-effect), not
#: signal — chosen loose (25%) because the predictor is an agent, not an
#: identified plant model, and over-trusting exact prediction would resurface
#: every self-effect as a false disturbance.
DEFAULT_RELATIVE_TOLERANCE = 0.25


@dataclass(frozen=True)
class ExpectedFootprint:
    """A merge's predicted effect: how much each area is expected to move.

    ``deltas`` maps an area to the predicted signed movement of its metric for
    this merge (the convergence pipeline's per-change expectation). An area
    absent from ``deltas`` was predicted not to move (expected delta 0).
    """

    merge_id: str
    deltas: Mapping[str, float]


def residual(observed: float, expected: float) -> float:
    """The innovation: observed movement minus what the footprint predicted.

    Sign is meaningful — a positive residual moved *more* than predicted, a
    negative one *less* (the actuation under-delivered). It is ``|residual|``
    that measures surprise.
    """
    return observed - expected


def is_explained(
    observed: float,
    expected: float,
    *,
    rel_tol: float = DEFAULT_RELATIVE_TOLERANCE,
    abs_tol: float = 0.0,
) -> bool:
    """Whether an observed movement is within tolerance of its prediction.

    Explained movement is self-effect and must be discounted, not read as
    signal. Uses :func:`math.isclose`, so an area predicted to move but observed
    flat (a footprint *miss*) is correctly surprising, as is movement in an area
    predicted to stay still.
    """
    return math.isclose(observed, expected, rel_tol=rel_tol, abs_tol=abs_tol)


def discount(
    observed: Mapping[str, float], footprint: ExpectedFootprint
) -> dict[str, float]:
    """Per-area residual over the union of observed and predicted areas.

    An area only observed (not predicted) keeps its full movement as residual —
    unexplained by the footprint. An area only predicted (not observed) yields a
    negative residual — the actuation was expected to move it and did not.
    """
    areas = set(observed) | set(footprint.deltas)
    return {
        area: residual(observed.get(area, 0.0), footprint.deltas.get(area, 0.0))
        for area in areas
    }


@dataclass(frozen=True)
class FootprintDiscountReport:
    """How much of a batch of movement the footprint explained, and what surprised."""

    residuals: dict[str, float]
    surprising_areas: tuple[str, ...]
    explained_areas: tuple[str, ...]
    total_abs_residual: float


def discount_report(
    observed: Mapping[str, float],
    footprint: ExpectedFootprint,
    *,
    rel_tol: float = DEFAULT_RELATIVE_TOLERANCE,
    abs_tol: float = 0.0,
) -> FootprintDiscountReport:
    """Partition observed movement into surprising (signal) vs explained areas.

    ``surprising_areas`` are the areas whose movement the footprint did not
    predict within tolerance — the only ones a sensor should treat as a
    disturbance. ``total_abs_residual`` is the summed unexplained movement.
    """
    residuals = discount(observed, footprint)
    areas = set(observed) | set(footprint.deltas)
    surprising = tuple(
        sorted(
            area
            for area in areas
            if not is_explained(
                observed.get(area, 0.0),
                footprint.deltas.get(area, 0.0),
                rel_tol=rel_tol,
                abs_tol=abs_tol,
            )
        )
    )
    surprising_set = set(surprising)
    explained = tuple(sorted(area for area in areas if area not in surprising_set))
    total = sum(abs(v) for v in residuals.values())
    return FootprintDiscountReport(
        residuals=residuals,
        surprising_areas=surprising,
        explained_areas=explained,
        total_abs_residual=total,
    )


def footprint_accuracy(
    predicted: Mapping[str, float], actual: Mapping[str, float]
) -> float:
    """A merge's footprint accuracy in ``[0, 1]``: how well prediction matched reality.

    ``1 − Σ|pred − actual| / Σ max(|pred|, |actual|)`` over the union of areas.
    ``1.0`` when the prediction is exact (and when nothing moved and nothing was
    predicted); trends to ``0`` as the prediction diverges. The per-merge history
    of this value is the calibration series (#10825): rung 3 weights innovations
    by how trustworthy the predictor has proven, so its trustworthiness must be
    measured, never assumed.
    """
    areas = set(predicted) | set(actual)
    error = sum(abs(predicted.get(area, 0.0) - actual.get(area, 0.0)) for area in areas)
    scale = sum(
        max(abs(predicted.get(area, 0.0)), abs(actual.get(area, 0.0))) for area in areas
    )
    if scale == 0.0:
        return 1.0
    return max(0.0, 1.0 - error / scale)
