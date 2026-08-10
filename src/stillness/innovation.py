"""Innovation-based sensing (#10825, rung 3) — the principled Kalman target.

The top rung of the stillness sensing ladder (#10819, ADR-0120). Rung 1
([[settling.py]]) discards readings in a window; rung 2 ([[footprint.py]])
subtracts a merge's expected footprint and keeps the residual. Rung 3 states the
design rule for the whole sensing layer outright — **respond to innovations, not
measurements** — and gives it the scalar-Kalman form the earlier rungs were
approximating:

* the loop carries an *estimate* of a metric's true level with an uncertainty;
* each cycle it PREDICTS forward, adding its own known actuation as the control
  input (the rung-2 expected footprint) and growing uncertainty by process noise;
* it then UPDATES against the measurement, and the correction it applies is the
  Kalman gain times the **innovation** — measurement minus prediction, i.e. pure
  surprise. A loop acts on that corrected surprise, never the raw reading.

The two noises are exactly the earlier instruments' outputs, so this rung is the
join, not new theory:

* **R (measurement noise)** — the sensor's own false-positive floor from finder
  calibration (#10821, ADR-0126), inflated when the footprint predictor has
  proven untrustworthy (rung 2's :func:`footprint_accuracy` series): a distrusted
  self-model makes the innovation less informative, so we lean on the prior.
* **the control input** — rung 2's expected footprint for this merge.

Pure engine: a scalar Kalman step over floats. Loading R from the calibrated
finder floor, the control from the convergence exhaust, and driving the estimate
per cycle is the caller's job.
"""

from __future__ import annotations

from dataclasses import dataclass

#: A footprint predictor is never fully trusted (accuracy 1.0 would divide by
#: nothing); this floors the accuracy used to inflate R so a single bad merge
#: cannot send the effective measurement noise to infinity.
DEFAULT_ACCURACY_FLOOR = 0.1


@dataclass(frozen=True)
class KalmanEstimate:
    """A loop's belief about a metric's true level: ``mean`` ± √``variance``."""

    mean: float
    variance: float


@dataclass(frozen=True)
class KalmanStep:
    """The outcome of one predict+update cycle.

    ``innovation`` is the surprise the loop responds to — measurement minus the
    control-adjusted prior. ``innovation_variance`` (S = P⁻ + R) is how large a
    surprise the model already expected, so the two together are the normalized
    innovation the sensing layer acts on. ``gain`` is how much of the innovation
    was believed (0 → trust the prior entirely, 1 → trust the measurement).
    """

    estimate: KalmanEstimate
    innovation: float
    innovation_variance: float
    gain: float


def effective_measurement_noise(
    base_noise: float,
    footprint_accuracy: float,
    *,
    accuracy_floor: float = DEFAULT_ACCURACY_FLOOR,
) -> float:
    """Inflate the sensor's base noise ``R`` by how untrustworthy the predictor is.

    ``base_noise`` is the calibrated finder floor variance (#10821). When the
    footprint predictor is perfect (accuracy 1.0) the noise is unchanged; as its
    accuracy falls, ``R`` is inflated by ``1 / accuracy`` so the filter leans on
    the prior instead of an innovation it cannot interpret. Accuracy is floored
    (never 0) so one bad merge cannot send ``R`` to infinity.
    """
    trust = max(footprint_accuracy, accuracy_floor)
    return base_noise / trust


def kalman_step(
    prior: KalmanEstimate,
    measurement: float,
    *,
    process_noise: float,
    measurement_noise: float,
    control: float = 0.0,
) -> KalmanStep:
    """One scalar Kalman predict+update cycle.

    PREDICT applies the known actuation (``control`` = the expected footprint)
    and grows uncertainty by ``process_noise`` (Q). UPDATE forms the innovation
    against that control-adjusted prediction and corrects by ``gain × innovation``
    with ``gain = P⁻ / (P⁻ + R)``. Because the control carries the known
    self-effect, the innovation is exactly the unexplained surprise — rung 2's
    residual, now optimally weighted against the prior.
    """
    predicted_mean = prior.mean + control
    predicted_var = prior.variance + process_noise
    innovation = measurement - predicted_mean
    innovation_variance = predicted_var + measurement_noise
    gain = predicted_var / innovation_variance
    posterior_mean = predicted_mean + gain * innovation
    posterior_var = (1.0 - gain) * predicted_var
    return KalmanStep(
        estimate=KalmanEstimate(mean=posterior_mean, variance=posterior_var),
        innovation=innovation,
        innovation_variance=innovation_variance,
        gain=gain,
    )


def is_surprising(step: KalmanStep, *, sigma_threshold: float = 3.0) -> bool:
    """Whether a step's innovation is large enough to act on (a real disturbance).

    The normalized-innovation test: compare the innovation against the spread the
    model already expected (√``innovation_variance``). This is the sensing-layer
    decision the whole ladder exists to make honest — the loop reacts only when
    the surprise exceeds ``sigma_threshold`` standard deviations of what was
    predicted, never to a movement its own actuation explained. A degenerate
    zero-spread step (no uncertainty and no noise) treats any non-zero innovation
    as surprising.
    """
    if step.innovation_variance <= 0.0:
        return step.innovation != 0.0
    return abs(step.innovation) > sigma_threshold * (step.innovation_variance**0.5)
