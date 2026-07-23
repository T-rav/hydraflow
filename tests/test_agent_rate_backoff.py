"""Unit tests for the rate-aware agent-subprocess backoff primitive (#10289).

Two defects this covers:

1. *No backpressure* — the factory kept spawning agents at full rate into a
   depleted rate window, truncating runs. The backoff engine throttles spawning
   when the repeated-mid-run-failure signature appears, and recovers on success.
2. *Misdiagnosis as credit exhaustion* — a subprocess that exits non-zero with
   no terminal ``result`` frame (a truncated run under concurrent load) is the
   depleted-rate-window signature, NOT credit exhaustion. The classifier must
   keep the two distinct, and the ``overageDisabledReason:"out_of_credits"``
   overage flag (present even on SUCCESS) must never trip credit-exhaustion.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_rate_backoff import (
    AgentOutcomeKind,
    AgentRateBackoff,
    classify_agent_outcome,
)

# ---------------------------------------------------------------------------
# Classification — the misdiagnosis fix (defect 2)
# ---------------------------------------------------------------------------


class TestClassifyAgentOutcome:
    def test_success_when_rc_zero_and_result_frame(self) -> None:
        assert (
            classify_agent_outcome(
                returncode=0, has_result_frame=True, output_text="anything"
            )
            == AgentOutcomeKind.SUCCESS
        )

    def test_mid_run_failure_is_rate_limit_not_credit(self) -> None:
        """rc != 0 with no terminal result frame = truncated mid-run =
        depleted-rate-window signature, distinct from credit exhaustion."""
        assert (
            classify_agent_outcome(
                returncode=1,
                has_result_frame=False,
                output_text="assistant turn ... (process died mid-tool-use)",
            )
            == AgentOutcomeKind.MID_RUN_RATE_LIMIT
        )

    def test_out_of_credits_overage_flag_is_not_credit_exhaustion(self) -> None:
        """The persistent ``overageDisabledReason:"out_of_credits"`` overage flag
        appears even on SUCCESS (per the incident). On a mid-run failure it must
        classify as rate-limit, NOT credit exhaustion — the core misdiagnosis."""
        result = classify_agent_outcome(
            returncode=1,
            has_result_frame=False,
            output_text=(
                '{"type":"rate_limit_event","overageDisabledReason":"out_of_credits"}'
            ),
        )
        assert result == AgentOutcomeKind.MID_RUN_RATE_LIMIT
        assert result != AgentOutcomeKind.CREDIT_EXHAUSTION

    def test_genuine_credit_exhaustion_still_classified(self) -> None:
        """A real billing signal ("credit balance is too low") still wins."""
        assert (
            classify_agent_outcome(
                returncode=1,
                has_result_frame=False,
                output_text="Your credit balance is too low to run this.",
            )
            == AgentOutcomeKind.CREDIT_EXHAUSTION
        )

    def test_early_killed_run_is_not_a_failure_signal(self) -> None:
        """A run we intentionally early-killed is not a rate-limit signal."""
        assert (
            classify_agent_outcome(
                returncode=1,
                has_result_frame=False,
                output_text="partial",
                early_killed=True,
            )
            == AgentOutcomeKind.OTHER
        )

    def test_nonzero_rc_with_result_frame_is_not_mid_run(self) -> None:
        """A completed run that produced a terminal result frame is not the
        truncated signature even if rc != 0 (e.g. a non-zero business exit)."""
        assert (
            classify_agent_outcome(
                returncode=1, has_result_frame=True, output_text="done"
            )
            == AgentOutcomeKind.OTHER
        )


# ---------------------------------------------------------------------------
# Backoff engine — backpressure (defect 1)
# ---------------------------------------------------------------------------


class _Clock:
    """Deterministic injectable monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _engine(
    *,
    enabled: bool = True,
    failure_threshold: int = 3,
    window_seconds: float = 300.0,
    base_delay_seconds: float = 30.0,
    max_delay_seconds: float = 600.0,
    recovery_successes: int = 2,
    time_source: Callable[[], float] | None = None,
) -> AgentRateBackoff:
    return AgentRateBackoff(
        enabled=enabled,
        failure_threshold=failure_threshold,
        window_seconds=window_seconds,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
        recovery_successes=recovery_successes,
        time_source=time_source,
    )


class TestBackoffEngine:
    def test_disabled_by_default_never_throttles(self) -> None:
        """Conservative default: a fresh engine is DISABLED and inert — it can
        never wedge the pipeline no matter how many failures arrive."""
        engine = AgentRateBackoff()
        assert engine.enabled is False
        for _ in range(20):
            engine.record_mid_run_failure()
        assert engine.is_backing_off is False
        assert engine.current_delay_seconds() == 0.0

    def test_below_threshold_does_not_engage(self) -> None:
        engine = _engine()
        engine.record_mid_run_failure()
        engine.record_mid_run_failure()
        assert engine.is_backing_off is False
        assert engine.current_delay_seconds() == 0.0

    def test_engages_at_threshold(self) -> None:
        engine = _engine()
        for _ in range(3):
            engine.record_mid_run_failure()
        assert engine.is_backing_off is True
        assert engine.current_delay_seconds() == 30.0

    def test_escalates_exponentially_and_caps(self) -> None:
        engine = _engine()
        for _ in range(3):  # reach threshold -> level 1 -> 30s
            engine.record_mid_run_failure()
        assert engine.current_delay_seconds() == 30.0
        engine.record_mid_run_failure()  # level 2 -> 60s
        assert engine.current_delay_seconds() == 60.0
        engine.record_mid_run_failure()  # level 3 -> 120s
        assert engine.current_delay_seconds() == 120.0
        for _ in range(10):  # keep failing -> caps at max
            engine.record_mid_run_failure()
        assert engine.current_delay_seconds() == 600.0

    def test_old_failures_outside_window_do_not_count(self) -> None:
        clock = _Clock()
        engine = _engine(window_seconds=300.0, time_source=clock)
        engine.record_mid_run_failure()
        engine.record_mid_run_failure()
        clock.advance(301.0)  # both fall out of the rolling window
        engine.record_mid_run_failure()  # only 1 within window -> below threshold
        assert engine.is_backing_off is False

    def test_recovers_after_consecutive_successes(self) -> None:
        engine = _engine(recovery_successes=2)
        for _ in range(3):
            engine.record_mid_run_failure()
        assert engine.is_backing_off is True
        engine.record_success()  # one success is not enough
        assert engine.is_backing_off is True
        engine.record_success()  # second consecutive success -> full reset
        assert engine.is_backing_off is False
        assert engine.current_delay_seconds() == 0.0

    def test_failure_breaks_the_recovery_streak(self) -> None:
        engine = _engine(recovery_successes=2)
        for _ in range(3):
            engine.record_mid_run_failure()
        engine.record_success()
        engine.record_mid_run_failure()  # resets the success streak
        engine.record_success()
        assert engine.is_backing_off is True  # only 1 consecutive success again

    def test_record_outcome_routes_by_kind(self) -> None:
        engine = _engine()
        for _ in range(3):
            engine.record_outcome(AgentOutcomeKind.MID_RUN_RATE_LIMIT)
        assert engine.is_backing_off is True
        # Credit exhaustion is a separate billing signal — it must NOT feed the
        # rate-limit backoff, and it must not count as a success for recovery.
        engine.record_outcome(AgentOutcomeKind.CREDIT_EXHAUSTION)
        assert engine.is_backing_off is True
        engine.record_outcome(AgentOutcomeKind.SUCCESS)
        engine.record_outcome(AgentOutcomeKind.SUCCESS)
        assert engine.is_backing_off is False


class TestWaitIfThrottled:
    @pytest.mark.asyncio
    async def test_no_sleep_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = AgentRateBackoff()  # disabled
        calls: list[float] = []

        async def _fake_sleep(secs: float) -> None:
            calls.append(secs)

        monkeypatch.setattr("agent_rate_backoff.asyncio.sleep", _fake_sleep)
        await engine.wait_if_throttled()
        assert calls == []

    @pytest.mark.asyncio
    async def test_sleeps_for_delay_when_engaged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = _engine()
        for _ in range(3):
            engine.record_mid_run_failure()
        calls: list[float] = []

        async def _fake_sleep(secs: float) -> None:
            calls.append(secs)

        monkeypatch.setattr("agent_rate_backoff.asyncio.sleep", _fake_sleep)
        await engine.wait_if_throttled()
        assert calls == [30.0]


# ---------------------------------------------------------------------------
# Integration point — the central stream_claude_process path records outcomes
# ---------------------------------------------------------------------------


class TestRunnerUtilsIntegration:
    def _reset_singleton(self) -> None:
        from agent_rate_backoff import get_agent_rate_backoff

        get_agent_rate_backoff().reset()
        get_agent_rate_backoff().configure(enabled=False)

    def test_post_stream_result_records_mid_run_failure(self) -> None:
        """The wired integration point: a mid-run failure flowing through
        ``_post_stream_result`` engages the (enabled) singleton engine."""
        import logging
        from unittest.mock import MagicMock

        from agent_rate_backoff import get_agent_rate_backoff
        from runner_utils import StreamConfig, _post_stream_result

        try:
            get_agent_rate_backoff().configure(enabled=True, failure_threshold=2)
            get_agent_rate_backoff().reset()
            parser = MagicMock()
            parser.usage_snapshot = {}
            for _ in range(2):
                _post_stream_result(
                    raw_lines=["assistant chunk, then the process died"],
                    accumulated_text="assistant chunk\n",
                    result_text="",  # <- no terminal result frame
                    early_killed=False,
                    returncode=1,  # <- non-zero mid-run exit
                    stderr_text="",
                    parser=parser,
                    config=StreamConfig(),
                    logger=logging.getLogger("test"),
                )
            assert get_agent_rate_backoff().is_backing_off is True
        finally:
            self._reset_singleton()

    def test_post_stream_result_records_success(self) -> None:
        """A clean run records a success (drives recovery), never a failure."""
        import logging
        from unittest.mock import MagicMock

        from agent_rate_backoff import get_agent_rate_backoff
        from runner_utils import StreamConfig, _post_stream_result

        try:
            get_agent_rate_backoff().configure(enabled=True, failure_threshold=2)
            get_agent_rate_backoff().reset()
            parser = MagicMock()
            parser.usage_snapshot = {}
            _post_stream_result(
                raw_lines=["final"],
                accumulated_text="final\n",
                result_text="final result",
                early_killed=False,
                returncode=0,
                stderr_text="",
                parser=parser,
                config=StreamConfig(),
                logger=logging.getLogger("test"),
            )
            assert get_agent_rate_backoff().is_backing_off is False
        finally:
            self._reset_singleton()
