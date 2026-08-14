"""Regression pin for #11121 — indefinite warmup read as 100% healthy.

`RCBudgetLoop` returned `{"status": "warmup"}` forever when the RC-run cache
never reached `_MIN_HISTORY`, and the trust-fleet roll-up only counted
`status == "error"` on the PAYLOAD (which is always "ok" for a completed
cycle) — so a loop that never did productive work reported perfectly
healthy. Two-sided fix pinned here: the loop degrades itself to
`warmup_stalled` after a streak, and the roll-up counts warmup ticks from
the details status.
"""

from __future__ import annotations

from rc_budget_loop import _MIN_HISTORY, _WARMUP_STALL_TICKS


def test_stall_threshold_exists_and_is_bounded() -> None:
    # The streak must be long enough that a genuine fresh-cache warmup
    # (< _MIN_HISTORY runs) doesn't false-flag, and short enough that a
    # stuck loop surfaces within ~a day of default 4h ticks.
    assert 2 <= _WARMUP_STALL_TICKS <= 12
    assert _MIN_HISTORY >= 1


def test_tally_counts_warmup_from_details_status() -> None:
    from dashboard_routes._trust_routes import _tally_events

    def _ev(detail_status: str):
        return {
            "type": "background_worker_status",
            "data": {
                "worker": "rc_budget",
                "status": "ok",
                "details": {"status": detail_status},
            },
        }

    rows = _tally_events([_ev("warmup"), _ev("warmup_stalled"), _ev("ok")])
    row = rows["rc_budget"]
    assert row["ticks_total"] == 3
    assert row["ticks_warmup"] == 2
    assert row["warmup_stalled"] is True
    # Payload-status accounting unchanged: none of these are errored ticks.
    assert row["ticks_errored"] == 0
