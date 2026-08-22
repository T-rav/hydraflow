"""Regression pin: a fresh escape-free reading must NEVER score as clean (#11593).

The first cut of the calibration loader set ``escaped=False`` the instant a
closing PR was known, so a PR that merged an hour ago — with no chance to
accumulate an escape yet — became a confirmed-good accept-arm data point and
over-credited the gate. That is exactly the failure ADR-0127's
``DEFAULT_GRACE_WINDOW`` exists to prevent, and it silently inflated the
measured accept-arm score (Brier 0.400 → 0.182 on the August corpus).

The invariant, pinned here because it is the honesty contract of the whole
instrument: an escape-free reading resolves *good* only once its ``closed_at``
has aged past the grace window, and a reading with **no** ``closed_at`` never
resolves at all — "we cannot date it" is the same epistemic state as "too
recent", never "old enough". An attributed escape still resolves *bad*
immediately; waiting cannot un-observe it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from adequacy_calibration import IssueOutcome, resolved_escapes

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("closed_at", "reason"),
    [
        pytest.param(
            datetime(2026, 8, 30, tzinfo=UTC), "inside-grace", id="too-recent"
        ),
        pytest.param(None, "undatable", id="no-close-date"),
    ],
)
def test_an_unaged_escape_free_reading_never_resolves(
    closed_at: datetime | None, reason: str
) -> None:
    outcome = IssueOutcome(
        issue_number=9001, closing_prs=(1101,), escaped=False, closed_at=closed_at
    )

    assert resolved_escapes([outcome], now=_NOW) == {}, reason


def test_an_attributed_escape_resolves_bad_without_waiting() -> None:
    outcome = IssueOutcome(
        issue_number=9001,
        closing_prs=(1101,),
        escaped=True,
        closed_at=datetime(2026, 8, 31, 23, tzinfo=UTC),
    )

    assert resolved_escapes([outcome], now=_NOW) == {9001: True}
