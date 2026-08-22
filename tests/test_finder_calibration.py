"""Unit tests for the golden-baseline finder-calibration pure core (#10821).

Fast, subprocess-free, no real finder runs: exercises the noise-floor math
(``measure_floor``, ``threshold_above_floor``, ``indistinguishable_from_floor``),
the read-only ``propose_gain`` guardrail, the stale-baseline / drift guardrails,
``calibrate_finder``, the injected ``FinderRunner`` seam, and the append-only
``CalibrationLedger`` round-trip. Known distributions with hand-computed
expectations so the statistics are pinned, not merely exercised.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from finder_calibration import (
    DEFAULT_MAX_BASELINE_AGE,
    FINDERS_BY_ID,
    GENERATIVE_FINDERS,
    CalibrationLedger,
    FinderFloor,
    GainProposal,
    GenerativeFinder,
    GoldenBaseline,
    NoiseSample,
    calibrate_finder,
    calibration_ledger_path,
    collect_samples,
    drift_since,
    indistinguishable_from_floor,
    is_baseline_stale,
    measure_floor,
    propose_gain,
    threshold_above_floor,
)

_NOW = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)


# -- factories ------------------------------------------------------------------


def _samples(
    counts: list[int], finder_id: str = "erosion_metrics"
) -> list[NoiseSample]:
    """Build noise samples with the given flagged-counts against one baseline."""
    return [
        NoiseSample(
            finder_id=finder_id,
            baseline_sha="cafe1234",
            flagged_count=c,
            ran_at=_NOW,
        )
        for c in counts
    ]


def _baseline(*, vetted_at: datetime = _NOW) -> GoldenBaseline:
    return GoldenBaseline(
        sha="cafe1234",
        vetted_at=vetted_at,
        vetted_by="travis",
        signal_class="erosion",
        note="hand-vetted clean for erosion",
    )


def _floor(
    *,
    finder_id: str = "erosion_metrics",
    mean: float = 2.0,
    sigma: float = 1.0,
    n: int = 8,
    threshold: int = 5,
    last_calibrated: datetime = _NOW,
    mean_drift: float = 0.0,
) -> FinderFloor:
    return FinderFloor(
        finder_id=finder_id,
        floor_mean=mean,
        floor_sigma=sigma,
        sample_count=n,
        threshold=threshold,
        last_calibrated=last_calibrated,
        mean_drift=mean_drift,
    )


class _FakeRunner:
    """Injected seam returning pre-scripted flagged-counts, one per call."""

    def __init__(self, counts: list[int]) -> None:
        self._counts = list(counts)
        self.calls: list[tuple[str, str]] = []

    def run_against_baseline(self, finder_id: str, baseline: GoldenBaseline) -> int:
        self.calls.append((finder_id, baseline.sha))
        return self._counts.pop(0)


# -- measure_floor --------------------------------------------------------------


def test_measure_floor_computes_mean_and_sample_stddev() -> None:
    # counts [1,2,3,4,5]: mean 3, ddof=1 variance = 10/4 = 2.5, sigma = sqrt(2.5)
    mean, sigma = measure_floor(_samples([1, 2, 3, 4, 5]))
    assert mean == pytest.approx(3.0)
    assert sigma == pytest.approx(math.sqrt(2.5))


def test_measure_floor_zero_floor_has_zero_mean_and_sigma() -> None:
    # A perfectly clean baseline: every run flags nothing.
    mean, sigma = measure_floor(_samples([0, 0, 0, 0]))
    assert mean == 0.0
    assert sigma == 0.0


def test_measure_floor_no_samples_returns_zero_zero_not_crash() -> None:
    assert measure_floor([]) == (0.0, 0.0)


def test_measure_floor_single_sample_uses_poisson_fallback_sigma() -> None:
    # One sample: empirical sigma undefined → Poisson prior sigma = sqrt(mean).
    mean, sigma = measure_floor(_samples([4]))
    assert mean == pytest.approx(4.0)
    assert sigma == pytest.approx(2.0)  # sqrt(4)


def test_measure_floor_single_zero_sample_has_zero_sigma() -> None:
    mean, sigma = measure_floor(_samples([0]))
    assert mean == 0.0
    assert sigma == 0.0


def test_measure_floor_single_sample_matches_c_chart_ucl_at_k3() -> None:
    # The documented reuse: with the 1-sample Poisson sigma and k=3 the UCL
    # equals the existing shewhart c-chart UCL (mean + 3*sqrt(mean)).
    from judge_independence import shewhart_c_chart_ucl

    mean, sigma = measure_floor(_samples([9]))
    ucl = mean + 3.0 * sigma
    assert ucl == pytest.approx(shewhart_c_chart_ucl([9.0]))


# -- threshold_above_floor ------------------------------------------------------


def test_threshold_is_ceil_of_mean_plus_k_sigma() -> None:
    # mean 2, sigma 1, k=3 → 5.0 → ceil 5
    assert threshold_above_floor(2.0, 1.0, k=3.0) == 5


def test_threshold_rounds_up_fractional_ucl() -> None:
    # mean 0.3, sigma 0.5, k=3 → 1.8 → ceil 2 (rounding down would leak signal)
    assert threshold_above_floor(0.3, 0.5, k=3.0) == 2


def test_threshold_floored_at_zero_for_clean_floor() -> None:
    assert threshold_above_floor(0.0, 0.0) == 0


def test_threshold_honours_custom_k() -> None:
    assert threshold_above_floor(1.0, 1.0, k=2.0) == 3  # ceil(1 + 2*1)


# -- indistinguishable_from_floor ----------------------------------------------


def test_live_count_inside_limits_is_indistinguishable() -> None:
    # floor mean 2, sigma 1, k=3 → UCL 5; a live count of 5 is on/under the limit.
    assert indistinguishable_from_floor(5, 2.0, 1.0, k=3.0) is True


def test_live_count_below_limit_is_indistinguishable() -> None:
    assert indistinguishable_from_floor(3, 2.0, 1.0, k=3.0) is True


def test_live_count_above_limit_is_distinguishable_signal() -> None:
    assert indistinguishable_from_floor(6, 2.0, 1.0, k=3.0) is False


def test_zero_floor_makes_any_flag_distinguishable() -> None:
    # A perfectly clean floor (0,0) → UCL 0; even a single live flag is signal.
    assert indistinguishable_from_floor(1, 0.0, 0.0) is False
    assert indistinguishable_from_floor(0, 0.0, 0.0) is True


# -- calibrate_finder -----------------------------------------------------------


def test_calibrate_finder_builds_floor_with_threshold_and_count() -> None:
    floor = calibrate_finder("erosion_metrics", _samples([1, 2, 3, 4, 5]), _NOW)
    assert floor.finder_id == "erosion_metrics"
    assert floor.floor_mean == pytest.approx(3.0)
    assert floor.sample_count == 5
    assert floor.threshold == threshold_above_floor(3.0, math.sqrt(2.5))
    assert floor.last_calibrated == _NOW
    assert floor.mean_drift == 0.0  # no prior


def test_calibrate_finder_records_mean_drift_from_prior() -> None:
    prior = _floor(mean=2.0)
    floor = calibrate_finder(
        "erosion_metrics", _samples([5, 5, 5, 5]), _NOW, prior=prior
    )
    assert floor.floor_mean == pytest.approx(5.0)
    assert floor.mean_drift == pytest.approx(3.0)  # |5 - 2|


def test_calibrate_finder_few_samples_is_low_confidence() -> None:
    floor = calibrate_finder("erosion_metrics", _samples([1]), _NOW)
    assert floor.sample_count == 1
    assert floor.low_confidence is True


def test_calibrate_finder_enough_samples_is_confident() -> None:
    floor = calibrate_finder("erosion_metrics", _samples([1, 2]), _NOW)
    assert floor.low_confidence is False


# -- propose_gain (read-only guardrail) ----------------------------------------


def test_propose_gain_when_threshold_below_floor() -> None:
    floor = _floor(mean=3.0, sigma=1.0, n=8, threshold=6)
    proposal = propose_gain(floor, current_threshold=2)
    assert isinstance(proposal, GainProposal)
    assert proposal.finder_id == "erosion_metrics"
    assert proposal.current_threshold == 2
    assert proposal.proposed_threshold == 6  # raise to the measured floor
    assert "gain DOWN" in proposal.reason


def test_propose_gain_none_when_threshold_already_above_floor() -> None:
    floor = _floor(threshold=5)
    assert propose_gain(floor, current_threshold=9) is None


def test_propose_gain_none_when_threshold_equals_floor() -> None:
    floor = _floor(threshold=5)
    assert propose_gain(floor, current_threshold=5) is None


def test_propose_gain_none_for_low_confidence_floor() -> None:
    # Even with the threshold below the floor, one sample is too little signal
    # to justify turning gain down.
    floor = _floor(n=1, threshold=8)
    assert propose_gain(floor, current_threshold=1) is None


def test_propose_gain_is_read_only_and_mutates_nothing() -> None:
    # The engine's only actuation output is an inert proposal object. Assert the
    # inputs are untouched and the models are frozen (cannot mutate a finder).
    floor = _floor(mean=3.0, sigma=1.0, n=8, threshold=6)
    snapshot = dataclasses.asdict(floor)
    proposal = propose_gain(floor, current_threshold=2)

    assert isinstance(proposal, GainProposal)
    assert dataclasses.asdict(floor) == snapshot  # floor unchanged
    with pytest.raises(dataclasses.FrozenInstanceError):
        floor.threshold = 99  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        proposal.proposed_threshold = 0  # type: ignore[misc]


# -- staleness / drift guardrails ----------------------------------------------


def test_baseline_fresh_within_max_age() -> None:
    baseline = _baseline(vetted_at=_NOW - timedelta(days=5))
    assert is_baseline_stale(baseline, _NOW) is False


def test_baseline_stale_beyond_max_age() -> None:
    baseline = _baseline(
        vetted_at=_NOW - (DEFAULT_MAX_BASELINE_AGE + timedelta(days=1))
    )
    assert is_baseline_stale(baseline, _NOW) is True


def test_baseline_staleness_honours_custom_max_age() -> None:
    baseline = _baseline(vetted_at=_NOW - timedelta(hours=2))
    assert is_baseline_stale(baseline, _NOW, max_age=timedelta(hours=1)) is True


def test_drift_since_is_time_since_last_calibration() -> None:
    floor = _floor(last_calibrated=_NOW - timedelta(days=3))
    assert drift_since(floor, _NOW) == timedelta(days=3)


# -- injected measurement seam --------------------------------------------------


def test_collect_samples_drives_runner_and_packages_counts() -> None:
    runner = _FakeRunner([0, 1, 0, 2])
    baseline = _baseline()
    samples = collect_samples(runner, "erosion_metrics", baseline, runs=4, ran_at=_NOW)
    assert [s.flagged_count for s in samples] == [0, 1, 0, 2]
    assert all(s.baseline_sha == baseline.sha for s in samples)
    assert runner.calls == [("erosion_metrics", baseline.sha)] * 4


def test_collect_samples_zero_runs_is_empty() -> None:
    runner = _FakeRunner([])
    samples = collect_samples(runner, "edge_proposer", _baseline(), runs=0, ran_at=_NOW)
    assert samples == []


def test_end_to_end_floor_from_injected_runner() -> None:
    # A finder that flags noise (0-1) on the clean baseline, then a real live
    # count is checked against the measured floor — no real finder run involved.
    runner = _FakeRunner([0, 1, 0, 0, 1, 0])
    samples = collect_samples(
        runner, "erosion_metrics", _baseline(), runs=6, ran_at=_NOW
    )
    floor = calibrate_finder("erosion_metrics", samples, _NOW)
    # Live output equal to the noise floor is indistinguishable → propose gain.
    assert indistinguishable_from_floor(
        floor.threshold, floor.floor_mean, floor.floor_sigma
    )
    assert propose_gain(floor, current_threshold=0) is not None


# -- catalog --------------------------------------------------------------------


def test_catalog_ids_are_unique() -> None:
    ids = [f.finder_id for f in GENERATIVE_FINDERS]
    assert len(ids) == len(set(ids))


def test_catalog_every_finder_has_a_signal_class() -> None:
    assert all(f.signal_class for f in GENERATIVE_FINDERS)
    assert all(isinstance(f, GenerativeFinder) for f in GENERATIVE_FINDERS)


def test_catalog_index_matches_catalog() -> None:
    assert set(FINDERS_BY_ID) == {f.finder_id for f in GENERATIVE_FINDERS}
    assert FINDERS_BY_ID["wiki_rot"].signal_class == "wiki-rot"


# -- CalibrationLedger ----------------------------------------------------------


def test_ledger_path_under_calibration_subdir(tmp_path: Path) -> None:
    assert calibration_ledger_path(tmp_path) == (
        tmp_path / "calibration" / "finder_floors.jsonl"
    )


def test_ledger_missing_file_reads_empty(tmp_path: Path) -> None:
    ledger = CalibrationLedger(calibration_ledger_path(tmp_path))
    assert ledger.read_all() == []
    assert ledger.latest_by_finder() == {}


def test_ledger_round_trip_preserves_floor(tmp_path: Path) -> None:
    ledger = CalibrationLedger(calibration_ledger_path(tmp_path))
    floor = calibrate_finder("erosion_metrics", _samples([1, 2, 3]), _NOW)
    ledger.record(floor)

    reloaded = ledger.read_all()
    assert len(reloaded) == 1
    got = reloaded[0]
    assert got.finder_id == floor.finder_id
    assert got.floor_mean == pytest.approx(floor.floor_mean)
    assert got.floor_sigma == pytest.approx(floor.floor_sigma)
    assert got.threshold == floor.threshold
    assert got.last_calibrated == floor.last_calibrated


def test_ledger_latest_by_finder_last_write_wins(tmp_path: Path) -> None:
    ledger = CalibrationLedger(calibration_ledger_path(tmp_path))
    ledger.record(_floor(finder_id="erosion_metrics", mean=1.0, threshold=3))
    ledger.record(_floor(finder_id="edge_proposer", mean=2.0, threshold=4))
    later = _NOW + timedelta(days=1)
    ledger.record(
        _floor(
            finder_id="erosion_metrics",
            mean=5.0,
            threshold=9,
            last_calibrated=later,
        )
    )

    latest = ledger.latest_by_finder()
    assert set(latest) == {"erosion_metrics", "edge_proposer"}
    assert latest["erosion_metrics"].threshold == 9  # the later row wins
    assert latest["erosion_metrics"].last_calibrated == later
