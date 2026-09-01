"""The 5-field cron matcher (#11861).

Written rather than depended on, so the tests carry the weight a library's
own suite would. The risk of a hand-rolled matcher is SILENT wrongness — a
schedule that never fires reads exactly like a quiet loop — so the negative
cases matter as much as the positive ones.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from cron_window import CronError, fired_since, matches

_TUE_0900 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)  # a Tuesday, the 1st


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("0 9 * * *", True),
        ("0 9 1 * *", True),
        ("0 9 * 9 *", True),
        ("0 9 * * TUE", True),
        ("0 9 * * 2", True),
        ("* * * * *", True),
        ("0 9 1 9 TUE", True),
        ("30 9 * * *", False),
        ("0 10 * * *", False),
        ("0 9 2 * *", False),
        ("0 9 * 8 *", False),
        ("0 9 * * MON", False),
        # Day-of-month AND day-of-week — see the module docstring on Vixie.
        ("0 9 1 * MON", False),
    ],
    ids=str,
)
def test_matching(expression: str, expected: bool) -> None:
    assert matches(expression, _TUE_0900) is expected


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("0 9,17 * * *", True),
        ("0 8-10 * * *", True),
        ("0 */3 * * *", True),
        ("0 9 * * MON,TUE", True),
        ("0 9 * * MON-WED", True),
        ("*/30 9 * * *", True),
        # 8-10/2 is {8, 10} — 09:00 is NOT in it. Kept as a NEGATIVE
        # because a step over a range is the form most often assumed to
        # mean "every 2 hours between 8 and 10 inclusive of 9".
        ("0 8-10/2 * * *", False),
        ("0 9-11/2 * * *", True),
        ("0 9,17 * * MON", False),
        ("0 10-12 * * *", False),
        ("0 */5 * * *", False),
    ],
    ids=str,
)
def test_lists_ranges_and_steps(expression: str, expected: bool) -> None:
    assert matches(expression, _TUE_0900) is expected


def test_sunday_is_both_zero_and_seven() -> None:
    """Crontab accepts either; a matcher that took only one silently never
    fires for whichever the author wrote."""
    sunday = datetime(2026, 9, 6, 9, 0, tzinfo=UTC)
    assert matches("0 9 * * 0", sunday)
    assert matches("0 9 * * 7", sunday)
    assert matches("0 9 * * SUN", sunday)


@pytest.mark.parametrize(
    "expression",
    [
        "@weekly",
        "0 9 * *",
        "0 9 * * * *",
        "0 99 * * *",
        "0 9 * * FUNDAY",
        "0 9 * * */0",
    ],
    ids=["alias", "four-field", "six-field", "out-of-range", "bad-name", "zero-step"],
)
def test_an_unsupported_expression_is_refused_not_guessed(expression: str) -> None:
    """Refused LOUDLY. The alternative — parsing what we can and ignoring the
    rest — produces a loop that silently never fires, which is the failure this
    whole module exists to prevent."""
    with pytest.raises(CronError):
        matches(expression, _TUE_0900)


class TestFiredSince:
    def test_a_never_fired_loop_runs_on_the_next_tick(self) -> None:
        """`last is None` must not mean "wait a full period".

        A newly-declared loop that waited a month to prove it works is a loop
        nobody trusts.
        """
        assert fired_since("0 9 * * *", None, _TUE_0900) == _TUE_0900

    def test_a_window_already_recorded_does_not_re_fire(self) -> None:
        assert fired_since("0 9 * * *", _TUE_0900, _TUE_0900) is None

    def test_a_window_since_the_last_receipt_fires(self) -> None:
        yesterday = _TUE_0900 - timedelta(days=1)
        assert fired_since("0 9 * * *", yesterday, _TUE_0900) == _TUE_0900

    def test_it_never_backfills_missed_windows(self) -> None:
        """The catch-up policy, and the reason it is a policy.

        A factory down for a month must not wake and run a daily loop thirty
        times. `fired_since` returns ONE window — the most recent — so the
        caller cannot accidentally iterate them.
        """
        month_ago = _TUE_0900 - timedelta(days=30)
        assert fired_since("0 9 * * *", month_ago, _TUE_0900) == _TUE_0900

    def test_a_loop_whose_window_has_not_come_round_yet(self) -> None:
        just_after = _TUE_0900 + timedelta(minutes=1)
        assert fired_since("0 9 * * *", _TUE_0900, just_after) is None
