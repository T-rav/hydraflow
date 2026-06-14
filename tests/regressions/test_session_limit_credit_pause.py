"""Regression: a Claude Code *session*-limit message must drive the credit-pause
path, not be mistaken for an ordinary agent failure.

Incident — 2026-06-13 overnight run. The factory hit its Claude subscription
session cap. Every in-flight agent (implement / review / auto-agent / diagnostic)
printed::

    You've hit your session limit · resets 5:50am (America/Denver)

Two latent bugs in ``subprocess_util`` meant this was NOT recognised as a
billing pause:

1. ``_CREDIT_PATTERNS`` listed ``"you've hit your limit"`` / ``"hit your usage
   limit"`` — but the word "session" sits between "hit your" and "limit", so no
   substring matched and :func:`is_credit_exhaustion` returned ``False``.
2. ``_RESET_TIME_RE`` only accepted whole hours (``5am``); it could not parse the
   ``H:MM`` form (``5:50am``), so even a detected pause had no resume time.

Consequence: no :class:`CreditExhaustedError` was raised, the orchestrator never
paused, each agent's attempt was burned as a "failure", ~8 in-flight PRs were
closed, and their issues were dumped into the HITL queue. This test pins both
halves of the fix end-to-end through the lightweight runner classifier so a
future pattern/regex edit cannot silently re-open the gap.
"""

from __future__ import annotations

import pytest

from runner_utils import raise_if_credit_exhausted
from subprocess_util import (
    CreditExhaustedError,
    is_credit_exhaustion,
    parse_credit_resume_time,
)

# The exact transcript line Claude Code emits when the subscription session cap
# is reached. Keep verbatim — the bug was a phrasing mismatch.
SESSION_LIMIT_MSG = "You've hit your session limit · resets 5:50am (America/Denver)"


def test_session_limit_is_classified_as_credit_exhaustion() -> None:
    assert is_credit_exhaustion(SESSION_LIMIT_MSG)


def test_session_limit_resume_time_parses_hour_and_minutes() -> None:
    # 5:50am MDT (June → UTC-6) == 11:50 UTC. Deterministic regardless of "now":
    # the past-time roll-forward preserves the Denver wall-clock time.
    resume = parse_credit_resume_time(SESSION_LIMIT_MSG)
    assert resume is not None
    assert (resume.hour, resume.minute) == (11, 50)


def test_lightweight_runner_raises_credit_error_with_resume_time() -> None:
    """raise_if_credit_exhausted is the path every run_simple-based runner uses;
    a session limit on stdout must raise with a populated resume_at so the
    orchestrator schedules a resume instead of failing the attempt.
    """
    with pytest.raises(CreditExhaustedError) as excinfo:
        raise_if_credit_exhausted(SESSION_LIMIT_MSG, "", tool="claude")
    assert excinfo.value.resume_at is not None
    assert excinfo.value.resume_at.minute == 50


def test_session_limit_on_stderr_also_raises() -> None:
    with pytest.raises(CreditExhaustedError):
        raise_if_credit_exhausted("", SESSION_LIMIT_MSG, tool="claude")
