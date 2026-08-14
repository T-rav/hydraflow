"""Regression pins for the prompt-inefficiency sensor false-positive class.

The 2026-08-14 idle run exposed two ways `compute_skill_efficiency`
manufactured "regressions" out of clean data (#11093 was one such filing):

1. **Zero-usage deflation (#11117).** 563 straight ``term_proposer`` calls
   recorded ``usage_status=unavailable`` — cost 0 while still counting as
   calls. Raw-call denominators deflated the baseline rate, so the first
   window of REAL usage at an unchanged per-call rate read as a >50%
   "regression" and filed. Denominators now count only usage-bearing calls
   (`_effective_calls`); an all-zero-usage window raises the
   ``zero_usage_window`` operational flag instead of a rate.

2. **Under-sampled windows (#11133/#11140).** 1-3 call windows — pure
   per-call variance — produced trends that filed issues and reordered the
   refine queue. Windows below ``MIN_WINDOW_CALLS`` effective calls now
   yield ``None`` trend: insufficient evidence, not a measurement.
"""

from __future__ import annotations

from prompt_efficiency import (
    INEFFICIENCY_THRESHOLD,
    MIN_WINDOW_CALLS,
    compute_skill_efficiency,
)


def _totals(cost_microusd: int, calls: int, anomalies: int = 0) -> dict[str, int]:
    return {
        "inference_calls": calls,
        "estimated_cost_microusd": cost_microusd,
        "usage_unavailable_calls": anomalies,
    }


def test_zero_usage_era_does_not_manufacture_regression() -> None:
    """The #11093 mechanism: a source with a long zero-usage era must not
    read its first real-usage window as a cost regression when the true
    per-call rate is unchanged."""
    # Baseline era: 563 zero-usage calls + 37 real calls totalling $2.00
    # (true rate ~$0.054/real-call; raw-denominator rate would be ~$0.0033).
    baseline = {"term_proposer": _totals(2_000_000, 600, anomalies=563)}
    # This tick: 10 more REAL calls at the same ~$0.054 rate.
    current = {"term_proposer": _totals(2_540_000, 610, anomalies=563)}

    # Demonstrate the pre-fix arithmetic really would have filed: with raw
    # denominators the baseline rate is 2.0/600 and the window rate
    # 0.54/10 — a ~15x jump, far over the filing threshold.
    raw_baseline_rate = 2.0 / 600
    raw_trend = (0.54 / 10 - raw_baseline_rate) / raw_baseline_rate
    assert raw_trend > INEFFICIENCY_THRESHOLD

    row = compute_skill_efficiency(current, baseline=baseline)[0]
    assert row.trend_vs_baseline is not None
    assert abs(row.trend_vs_baseline) < INEFFICIENCY_THRESHOLD


def test_all_zero_usage_window_is_flagged_not_measured() -> None:
    rows = compute_skill_efficiency(
        {"term_proposer": _totals(0, 150, anomalies=150)},
        baseline={"term_proposer": _totals(0, 100, anomalies=100)},
    )
    row = rows[0]
    assert row.zero_usage_window is True
    assert row.trend_vs_baseline is None
    assert row.cost_per_call == 0.0


def test_zero_usage_estimated_cost_does_not_inflate_the_rate() -> None:
    """The inflation mirror of the deflation FP (found in #11152 review):
    zero-usage calls excluded from the denominator may still carry
    char-estimated cost — that cost must leave the numerator too, or a
    clean source reads as a regression in the opposite direction."""
    baseline = {"diff-sanity": _totals(1_000_000, 100)}
    current = _totals(1_090_000, 125, anomalies=20)
    current["unavailable_est_cost_microusd"] = 40_000
    row = compute_skill_efficiency({"diff-sanity": current}, baseline=baseline)[0]
    assert row.trend_vs_baseline is not None
    assert abs(row.trend_vs_baseline) < INEFFICIENCY_THRESHOLD


def test_blind_spot_flag_needs_the_evidence_floor() -> None:
    """#11167 (sampled-audit upheld on #11152): zero_usage_window fired off
    a single unavailable call — the alert path skipped the floor the
    regression path enforces. Both sides of the sensor share it now."""
    single = compute_skill_efficiency(
        {"term_proposer": _totals(0, 101, anomalies=101)},
        baseline={"term_proposer": _totals(0, 100, anomalies=100)},
    )[0]
    assert single.zero_usage_window is False

    floor_sized = compute_skill_efficiency(
        {
            "term_proposer": _totals(
                0, 100 + MIN_WINDOW_CALLS, anomalies=100 + MIN_WINDOW_CALLS
            )
        },
        baseline={"term_proposer": _totals(0, 100, anomalies=100)},
    )[0]
    assert floor_sized.zero_usage_window is True


def test_under_sampled_window_never_trends() -> None:
    """A sub-floor window with a genuine 100x per-call spike still yields no
    trend — 1-3 calls cannot distinguish variance from regression."""
    assert MIN_WINDOW_CALLS >= 4
    rows = compute_skill_efficiency(
        {"diff-sanity": _totals(4_000_000, 103)},  # +3 calls at $1.00 each
        baseline={"diff-sanity": _totals(1_000_000, 100)},  # $0.01/call
    )
    assert rows[0].trend_vs_baseline is None
    assert rows[0].window_calls == 3
