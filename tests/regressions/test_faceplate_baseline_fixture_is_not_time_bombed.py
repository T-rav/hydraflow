"""Regression: the faceplate fixture's vetted-at must not be a literal date.

`tests/test_diagnostics_finder_faceplates_route.py` carried
`_NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)` while
`finder_calibration.DEFAULT_MAX_BASELINE_AGE` is 30 days. The fixture vouched
for a baseline as "recently vetted" and asserted `baseline_stale is False` — a
claim that was true when written and became false on 2026-09-02, exactly 30 days
later. The suite went red on a date, with no code change.

The general shape: **a fixture that encodes a moment, used to assert a property
that decays.** It cannot fail in review and cannot fail in CI until the fuse
burns down, so the cost lands on whoever is unlucky.

This guards the invariant the fixture actually needs — *recently* vetted,
whenever the suite runs — and it fails the day a literal is reintroduced rather
than a month afterwards.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from finder_calibration import DEFAULT_MAX_BASELINE_AGE  # noqa: E402
from tests import test_diagnostics_finder_faceplates_route as faceplate  # noqa: E402


def test_the_fixture_vets_its_baseline_recently_whenever_the_suite_runs() -> None:
    age = datetime.now(UTC) - faceplate._NOW

    assert age < DEFAULT_MAX_BASELINE_AGE, (
        f"the faceplate fixture vouches for a baseline {age.days} days old, but "
        f"DEFAULT_MAX_BASELINE_AGE is {DEFAULT_MAX_BASELINE_AGE.days} days — so "
        "its `baseline_stale is False` assertion is now false. Anchor _NOW to "
        "datetime.now(UTC) rather than a literal date."
    )


def test_the_fixture_is_not_in_the_future() -> None:
    """The decoy: a far-future literal would satisfy the age check above."""
    assert datetime.now(UTC) >= faceplate._NOW, (
        "a fixture dated in the future passes an age check while still being a "
        "literal moment, and decays the same way once reached"
    )
