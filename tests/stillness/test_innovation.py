"""Unit tests for innovation-based (Kalman) sensing (#10825, rung 3)."""

from __future__ import annotations

from stillness.innovation import (
    KalmanEstimate,
    KalmanStep,
    effective_measurement_noise,
    is_surprising,
    kalman_step,
)


class TestKalmanStep:
    def test_scalar_update_matches_hand_computation(self) -> None:
        # prior N(0, 4), Q=0 → P⁻=4; R=4 → S=8, K=0.5; z=10.
        step = kalman_step(
            KalmanEstimate(mean=0.0, variance=4.0),
            10.0,
            process_noise=0.0,
            measurement_noise=4.0,
        )
        assert step.innovation == 10.0
        assert step.innovation_variance == 8.0
        assert step.gain == 0.5
        assert step.estimate.mean == 5.0  # 0 + 0.5·10
        assert step.estimate.variance == 2.0  # (1−0.5)·4

    def test_control_input_absorbs_the_expected_footprint(self) -> None:
        # A measurement that exactly matches the predicted self-effect (control)
        # produces ZERO innovation — the loop is not surprised by its own actuation.
        step = kalman_step(
            KalmanEstimate(mean=0.0, variance=4.0),
            6.0,
            process_noise=0.0,
            measurement_noise=4.0,
            control=6.0,
        )
        assert step.innovation == 0.0
        assert step.estimate.mean == 6.0  # estimate tracks the control, no surprise

    def test_high_measurement_noise_trusts_the_prior(self) -> None:
        # Huge R → tiny gain → the estimate barely moves toward a wild measurement.
        step = kalman_step(
            KalmanEstimate(mean=0.0, variance=1.0),
            100.0,
            process_noise=0.0,
            measurement_noise=1000.0,
        )
        assert step.gain < 0.01
        assert step.estimate.mean < 1.0

    def test_low_measurement_noise_trusts_the_measurement(self) -> None:
        step = kalman_step(
            KalmanEstimate(mean=0.0, variance=1.0),
            100.0,
            process_noise=0.0,
            measurement_noise=0.001,
        )
        assert step.gain > 0.99
        assert step.estimate.mean > 99.0

    def test_repeated_measurements_converge_and_shrink_uncertainty(self) -> None:
        est = KalmanEstimate(mean=0.0, variance=100.0)
        for _ in range(50):
            est = kalman_step(
                est, 10.0, process_noise=0.01, measurement_noise=1.0
            ).estimate
        assert abs(est.mean - 10.0) < 0.5
        assert est.variance < 100.0


class TestEffectiveMeasurementNoise:
    def test_perfect_predictor_leaves_noise_unchanged(self) -> None:
        assert effective_measurement_noise(2.0, 1.0) == 2.0

    def test_untrustworthy_predictor_inflates_noise(self) -> None:
        # accuracy 0.5 → R doubled.
        assert effective_measurement_noise(2.0, 0.5) == 4.0

    def test_accuracy_is_floored_so_noise_cannot_blow_up(self) -> None:
        # accuracy 0 would divide by zero; floored at 0.1 → R × 10.
        assert effective_measurement_noise(2.0, 0.0) == 20.0


class TestIsSurprising:
    def _step(self, innovation: float, innovation_variance: float) -> KalmanStep:
        return KalmanStep(
            estimate=KalmanEstimate(mean=0.0, variance=1.0),
            innovation=innovation,
            innovation_variance=innovation_variance,
            gain=0.5,
        )

    def test_innovation_within_threshold_is_not_surprising(self) -> None:
        # |1| vs 3σ of unit variance → not surprising.
        assert not is_surprising(self._step(1.0, 1.0))

    def test_innovation_beyond_threshold_is_surprising(self) -> None:
        assert is_surprising(self._step(5.0, 1.0))

    def test_zero_spread_step_treats_any_nonzero_innovation_as_surprising(
        self,
    ) -> None:
        assert is_surprising(self._step(0.5, 0.0))
        assert not is_surprising(self._step(0.0, 0.0))

    def test_sigma_threshold_is_configurable(self) -> None:
        step = self._step(2.5, 1.0)  # 2.5σ
        assert not is_surprising(step, sigma_threshold=3.0)
        assert is_surprising(step, sigma_threshold=2.0)
