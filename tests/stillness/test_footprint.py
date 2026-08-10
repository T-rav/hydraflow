"""Unit tests for expected-footprint discounting (#10825, rung 2)."""

from __future__ import annotations

from stillness.footprint import (
    ExpectedFootprint,
    discount,
    discount_report,
    footprint_accuracy,
    is_explained,
    residual,
)


class TestResidual:
    def test_residual_is_observed_minus_expected(self) -> None:
        assert residual(5.0, 4.0) == 1.0
        assert residual(2.0, 4.0) == -2.0  # under-delivered actuation
        assert residual(4.0, 4.0) == 0.0  # fully explained


class TestIsExplained:
    def test_movement_within_relative_tolerance_is_explained(self) -> None:
        # 4.5 observed vs 4.0 predicted = 12.5% off, inside the default 25%.
        assert is_explained(4.5, 4.0)

    def test_movement_outside_tolerance_is_surprising(self) -> None:
        assert not is_explained(10.0, 4.0)

    def test_predicted_but_flat_is_a_surprising_footprint_miss(self) -> None:
        # Predicted to move, observed nothing → the actuation didn't land.
        assert not is_explained(0.0, 4.0)

    def test_unpredicted_movement_is_surprising(self) -> None:
        assert not is_explained(3.0, 0.0)

    def test_flat_and_unpredicted_is_explained(self) -> None:
        assert is_explained(0.0, 0.0)


class TestDiscount:
    def test_residual_over_union_of_areas(self) -> None:
        fp = ExpectedFootprint(merge_id="m1", deltas={"a": 4.0, "b": 1.0})
        observed = {"a": 5.0, "c": 2.0}
        res = discount(observed, fp)
        assert res == {"a": 1.0, "b": -1.0, "c": 2.0}

    def test_observed_only_area_keeps_full_movement(self) -> None:
        fp = ExpectedFootprint(merge_id="m1", deltas={})
        assert discount({"x": 3.0}, fp) == {"x": 3.0}

    def test_predicted_only_area_yields_negative_residual(self) -> None:
        fp = ExpectedFootprint(merge_id="m1", deltas={"y": 2.0})
        assert discount({}, fp) == {"y": -2.0}


class TestDiscountReport:
    def test_partitions_surprising_from_explained(self) -> None:
        fp = ExpectedFootprint(merge_id="m1", deltas={"a": 4.0, "b": 2.0})
        # a: 4.2 vs 4.0 explained; b: 10 vs 2 surprising; c: 3 unpredicted surprising
        report = discount_report({"a": 4.2, "b": 10.0, "c": 3.0}, fp)
        assert report.surprising_areas == ("b", "c")
        assert report.explained_areas == ("a",)

    def test_total_abs_residual_sums_unexplained_movement(self) -> None:
        fp = ExpectedFootprint(merge_id="m1", deltas={"a": 4.0})
        report = discount_report({"a": 6.0, "b": 3.0}, fp)
        # residuals: a=2, b=3 → total |residual| = 5
        assert report.total_abs_residual == 5.0

    def test_fully_explained_merge_surfaces_no_signal(self) -> None:
        fp = ExpectedFootprint(merge_id="m1", deltas={"a": 4.0, "b": 2.0})
        report = discount_report({"a": 4.0, "b": 2.0}, fp)
        assert report.surprising_areas == ()
        assert report.total_abs_residual == 0.0


class TestFootprintAccuracy:
    def test_exact_prediction_is_perfectly_accurate(self) -> None:
        pred = {"a": 4.0, "b": 2.0}
        assert footprint_accuracy(pred, {"a": 4.0, "b": 2.0}) == 1.0

    def test_nothing_moved_nothing_predicted_is_accurate(self) -> None:
        assert footprint_accuracy({}, {}) == 1.0

    def test_predicted_movement_that_never_happened_scores_zero(self) -> None:
        # Predicted 4, actual 0: error 4, scale max(4,0)=4 → 1 − 4/4 = 0.
        assert footprint_accuracy({"a": 4.0}, {"a": 0.0}) == 0.0

    def test_partial_miss_scores_between_zero_and_one(self) -> None:
        # a: |4−4|=0; b: |0−2|=2. error 2; scale max(4,4)+max(0,2)=6 → 1 − 2/6.
        acc = footprint_accuracy({"a": 4.0}, {"a": 4.0, "b": 2.0})
        assert acc == 1.0 - (2.0 / 6.0)

    def test_accuracy_is_floored_at_zero(self) -> None:
        # Opposite-sign prediction: error can exceed scale; clamp to 0.
        acc = footprint_accuracy({"a": 5.0}, {"a": -5.0})
        assert acc == 0.0
