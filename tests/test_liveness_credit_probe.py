"""Unit tests for the stuck credit-pause probe (#10734)."""

from __future__ import annotations

from scripts.liveness import credit_probe
from scripts.liveness.credit_probe import CreditAction, RefreshOutcome

_THRESHOLD = credit_probe.DEFAULT_STUCK_THRESHOLD_TICKS


class TestClassifyCreditPause:
    def test_single_paused_tick_is_left_alone(self) -> None:
        d = credit_probe.classify_credit_pause(
            status="credits_paused", paused_ticks=0, threshold=_THRESHOLD
        )
        assert d.action is CreditAction.WAIT
        assert d.paused_ticks == 1

    def test_pause_past_threshold_requests_refresh(self) -> None:
        d = credit_probe.classify_credit_pause(
            status="credits_paused", paused_ticks=_THRESHOLD, threshold=_THRESHOLD
        )
        assert d.action is CreditAction.REQUEST_REFRESH
        # Counter resets so the kernel re-probes at most once per threshold run.
        assert d.paused_ticks == 0

    def test_non_paused_status_resets_counter(self) -> None:
        d = credit_probe.classify_credit_pause(
            status="running", paused_ticks=5, threshold=_THRESHOLD
        )
        assert d.action is CreditAction.RESET
        assert d.paused_ticks == 0

    def test_idle_status_resets_counter(self) -> None:
        d = credit_probe.classify_credit_pause(
            status="idle", paused_ticks=3, threshold=_THRESHOLD
        )
        assert d.action is CreditAction.RESET
        assert d.paused_ticks == 0

    def test_none_status_resets_counter(self) -> None:
        d = credit_probe.classify_credit_pause(
            status=None, paused_ticks=4, threshold=_THRESHOLD
        )
        assert d.action is CreditAction.RESET
        assert d.paused_ticks == 0

    def test_consecutive_ticks_accumulate_below_threshold(self) -> None:
        ticks = 0
        for _ in range(_THRESHOLD):
            d = credit_probe.classify_credit_pause(
                status="credits_paused", paused_ticks=ticks, threshold=_THRESHOLD
            )
            ticks = d.paused_ticks
            assert d.action is CreditAction.WAIT
        # The next tick crosses the threshold and arms the probe.
        d = credit_probe.classify_credit_pause(
            status="credits_paused", paused_ticks=ticks, threshold=_THRESHOLD
        )
        assert d.action is CreditAction.REQUEST_REFRESH


class TestInterpretRefreshResponse:
    def test_still_exhausted_confirms_real_pause(self) -> None:
        assert (
            credit_probe.interpret_refresh_response("still_exhausted")
            is RefreshOutcome.CONFIRMED_EXHAUSTED
        )

    def test_resuming_clears_the_wedge(self) -> None:
        assert (
            credit_probe.interpret_refresh_response("resuming")
            is RefreshOutcome.CLEARED
        )

    def test_not_paused_clears(self) -> None:
        assert (
            credit_probe.interpret_refresh_response("not_paused")
            is RefreshOutcome.CLEARED
        )

    def test_unknown_or_none_reply_is_fail_closed(self) -> None:
        # An unreadable reply must never wake loops onto an unconfirmed account.
        assert (
            credit_probe.interpret_refresh_response(None)
            is RefreshOutcome.CONFIRMED_EXHAUSTED
        )
        assert (
            credit_probe.interpret_refresh_response("weird")
            is RefreshOutcome.CONFIRMED_EXHAUSTED
        )
