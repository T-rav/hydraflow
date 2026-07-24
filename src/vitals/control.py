"""Shewhart individuals (X / I-MR) control chart — one per input series (#10373).

The spec decided each input series carries *its own* Shewhart individuals-chart
control limits, baselined from the series' own history. An individuals chart is
the right tool for one-observation-per-window data (a c-chart, as used for the
fail-open RATE in ``judge_independence``, needs constant-size defect samples;
here each window yields a single scalar, so the moving-range individuals chart
is correct):

* centre line = the mean of the baseline observations
* dispersion  = estimated from the mean moving range ``MR̄`` (successive
  absolute differences), σ̂ = MR̄ / d₂ with d₂ = 1.128 for the n=2 moving range
* upper control limit = centre + 3·σ̂

All five families' series are *adverse when high* (more escapes, more erosion,
more corrections, more disagreements, more fail-opens), so only the UPPER limit
matters — a value below the mean is never a divergence signal. Pure functions
over ``list[float]``; no IO, no ML — counting and control limits only, because
legibility is the feature in the instrument that has to be trusted when it
fires.
"""

from __future__ import annotations

# d₂ bias-correction constant for a moving range of n=2 successive observations.
_D2_N2 = 1.128


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def mean_moving_range(baseline: list[float]) -> float:
    """Mean of successive absolute differences ``|xᵢ − xᵢ₋₁|`` over *baseline*.

    ``0.0`` for fewer than two points (no range is defined). A flat series
    yields ``0.0`` — a legitimate zero-dispersion estimate, handled by the
    caller (any rise above a flat mean then reads as a breach, which is the
    correct behaviour: a dead-flat series that suddenly climbs IS a signal).
    """
    if len(baseline) < 2:
        return 0.0
    diffs = [abs(baseline[i] - baseline[i - 1]) for i in range(1, len(baseline))]
    return _mean(diffs)


def individuals_limits(baseline: list[float]) -> tuple[float, float]:
    """Return ``(centre, upper_control_limit)`` for an individuals chart.

    ``centre`` is the baseline mean; ``ucl = centre + 3·σ̂`` with σ̂ derived from
    the mean moving range. An empty baseline yields ``(0.0, 0.0)``; a single
    point yields ``(x, x)`` (no dispersion estimable yet). These degenerate
    limits never fire on their own because :func:`breaches_upper` also gates on
    ``min_windows``.
    """
    if not baseline:
        return (0.0, 0.0)
    centre = _mean(baseline)
    sigma_hat = mean_moving_range(baseline) / _D2_N2
    return (centre, centre + 3.0 * sigma_hat)


def breaches_upper(value: float, baseline: list[float], *, min_windows: int) -> bool:
    """Whether *value* sits STRICTLY above the 3σ UCL computed over *baseline*.

    This is the ONE breach predicate the whole capstone shares: the verdict
    engine's :func:`vitals.verdict._series_sustained_breach` tests each of a
    series' monitored recent windows through this exact function, so the
    "above the 3σ upper control limit" boundary — above the LIMIT, not merely
    above the baseline mean — is defined in a single place and cannot drift
    between the control chart and the verdict.

    Returns ``False`` — never a breach — until *baseline* has at least
    ``min_windows`` observations: a control limit computed from one or two
    points is noise, not signal (the same discipline
    ``judge_independence.fail_open_rate_breach`` applies with its ``min_days``
    floor). The value being tested is deliberately NOT part of its own baseline
    (the caller passes the prior windows), so a spike cannot inflate the limit
    it is measured against.
    """
    if len(baseline) < max(1, min_windows):
        return False
    _centre, ucl = individuals_limits(baseline)
    return value > ucl
