"""Regression: Claude Code's *weekly*-cap message must drive the credit-pause
path, not be mistaken for an ordinary agent failure.

Incident — 2026-06-17. The factory hit its Claude subscription WEEKLY limit.
Agents printed::

    You've hit your weekly limit · resets Jun 18 at 5pm

This is the same failure class as the 2026-06-13 session-limit incident
(see test_session_limit_credit_pause.py / PR #9529): the word "weekly" sits
between "hit your" and "limit", so it slipped past every substring in
``_CREDIT_PATTERNS``. ``is_credit_exhaustion`` returned False, no
``CreditExhaustedError`` was raised, the orchestrator never paused, and the
factory burned its whole attempt budget into HITL (one issue accumulated 492
billing-message comments).

This pins the fix: a future-proof "hit your <period> limit" detector plus
weekly resume-time parsing, asserted through the lightweight runner classifier
that every ``run_simple``-based runner uses.
"""

from __future__ import annotations

import pytest

from runner_utils import raise_if_credit_exhausted
from subprocess_util import (
    CreditExhaustedError,
    is_credit_exhaustion,
    parse_credit_resume_time,
)

WEEKLY_MSG = "You've hit your weekly limit · resets Jun 18 at 5pm"
WEEKLY_WEEKDAY_MSG = "You've hit your weekly limit · resets Wednesday at 5pm"


def test_weekly_limit_is_classified_as_credit_exhaustion() -> None:
    assert is_credit_exhaustion(WEEKLY_MSG)
    assert is_credit_exhaustion(WEEKLY_WEEKDAY_MSG)


def test_lightweight_runner_raises_on_weekly_limit() -> None:
    """The path every run_simple-based runner uses must raise so the orchestrator
    pauses + refunds the attempt instead of failing it.
    """
    with pytest.raises(CreditExhaustedError):
        raise_if_credit_exhausted(WEEKLY_MSG, "", tool="claude")
    with pytest.raises(CreditExhaustedError):
        raise_if_credit_exhausted("", WEEKLY_WEEKDAY_MSG, tool="claude")


def test_weekly_weekday_reset_populates_resume_time() -> None:
    """The weekday form yields a concrete resume time so the pause lasts the
    right duration rather than waking every 5h on the default fallback.
    """
    with pytest.raises(CreditExhaustedError) as excinfo:
        raise_if_credit_exhausted(WEEKLY_WEEKDAY_MSG, "", tool="claude")
    assert excinfo.value.resume_at is not None


def test_future_proof_period_family_detected() -> None:
    """A new single-word cap wording (daily/monthly) must not recur the burn."""
    for period in ("daily", "monthly", "hourly"):
        assert is_credit_exhaustion(f"You've hit your {period} limit")


def test_weekly_with_unparseable_reset_still_raises() -> None:
    """Even when the reset clause can't be parsed, detection must fire (the
    orchestrator falls back to its default pause window).
    """
    assert parse_credit_resume_time("You've hit your weekly limit") is None
    with pytest.raises(CreditExhaustedError):
        raise_if_credit_exhausted("You've hit your weekly limit", "", tool="claude")
