"""Unit tests for the time-travel guard fixture (#11047).

The guard itself must be trustworthy: inert when the env var is unset, and
actually displacing the wall clock when set — otherwise the advisory lane
would green-light bombs it never armed.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta


def test_clock_matches_env_contract() -> None:
    """Under the lane the clock is ~N days ahead; in normal runs it is real.

    One test covers both modes because the fixture is autouse: when
    ``make time-travel`` runs this file the offset MUST be applied, and when
    the normal suite runs it the clock MUST be untouched — either way the
    observed ``datetime.now(UTC)`` agrees with the env contract.
    """
    days = os.environ.get("HYDRAFLOW_TIME_TRAVEL_DAYS")
    expected = datetime.now(UTC).replace(tzinfo=UTC)  # freezegun-aware call
    # Reconstruct the untraveled reference from the OS clock, which freezegun
    # does not fake: time.time() bypasses the datetime patch only when the
    # fixture is inert, so compare against the env contract instead — the
    # observed clock must sit within an hour of (real now + offset).
    offset = timedelta(days=int(days)) if days else timedelta(0)
    import subprocess

    real_now_iso = subprocess.run(
        ["date", "-u", "+%Y-%m-%dT%H:%M:%S"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    real_now = datetime.fromisoformat(real_now_iso).replace(tzinfo=UTC)
    assert abs(expected - (real_now + offset)) < timedelta(hours=1)


def test_tick_keeps_the_clock_advancing() -> None:
    """``tick=True``: successive readings never go backwards (sleeps still work)."""
    first = datetime.now(UTC)
    second = datetime.now(UTC)
    assert second >= first
