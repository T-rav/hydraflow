"""Regression canary for issue #10504 — the escape-ledger confirmed-rate gauge.

The confirmed-escape headline (``is_confirmed`` / ``CONFIRMED_CONFIDENCES =
("high", "medium")``) reads ``0`` today because every *real* ledger row lands at
``low`` confidence — a fix-heavy repo's ``fix(...): fixes #N`` bug-issue closes.
That is a *healthy* zero, but a permanently-zero gauge is indistinguishable from
a gauge that is *degenerate by construction* (``CONFIRMED_CONFIDENCES`` empty, or
``is_confirmed`` broken so high/medium can never match). A falsification
instrument that cannot go non-zero falsifies nothing.

No source bug was found: the mechanics are correct. Revert-with-parseable-sha
attributes ``high``; a revert without a sha, a ``tests/regressions/`` pin, and a
hotfix-with-origin-pointer each attribute ``medium`` — all reach ``is_confirmed``.
This canary is the fix the issue asks for: a check that *a window containing a
known revert or regression-pin commit produces a non-zero confirmed rate*, driven
end-to-end through the real pipeline (``detect_escapes`` → ``from_candidate`` →
``confirmed_escapes`` / rate). It fails if a future change makes the confirmed
rate unreachable-by-construction — distinguishing "healthy zero" from "broken
zero" so the gauge stays trustworthy.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from escape import metrics
from escape.detect import detect_escapes
from escape.models import CommitInfo, EscapeRecord

_NOW = datetime(2026, 7, 25, tzinfo=UTC)


def _known_revert() -> CommitInfo:
    """A real ``git revert`` commit — the canonical high-confidence escape.

    ``This reverts commit <sha>`` is the body line ``git revert`` writes; a
    parseable reverted sha attributes ``high`` mechanical confidence.
    """
    return CommitInfo(
        sha="aaaa111bbbb222",
        subject='Revert "feat: risky change that escaped the gates"',
        body="This reverts commit 1234abcd5678.",
        committed_at="2026-07-20T00:00:00+00:00",
    )


def _known_regression_pin() -> CommitInfo:
    """A commit adding a ``tests/regressions/`` pin — a medium-confidence escape."""
    return CommitInfo(
        sha="cccc333dddd444",
        subject="fix: pin the boot regression that escaped",
        body="Regression test for a failure introduced in 9f8e7d6c5b4a.",
        committed_at="2026-07-21T00:00:00+00:00",
        added_paths=("tests/regressions/test_boot_escape.py",),
    )


def _noise_bug_issue() -> CommitInfo:
    """An ordinary ``fix: … fixes #N`` close — low confidence, must NOT confirm."""
    return CommitInfo(
        sha="eeee555ffff666",
        subject="fix(triage): stop the crash",
        body="Fixes #9999.",
        committed_at="2026-07-22T00:00:00+00:00",
    )


def _noise_feature() -> CommitInfo:
    """A plain feature commit — not an escape at all."""
    return CommitInfo(
        sha="9999aaaa8888bbb",
        subject="feat: add a brand-new capability",
        body="Nothing reverted, nothing pinned.",
        committed_at="2026-07-22T00:00:00+00:00",
    )


def _records_for(commits: list[CommitInfo]) -> list[EscapeRecord]:
    """Drive the real pipeline: detect → attribute → assemble ledger rows."""
    return [EscapeRecord.from_candidate(cand) for cand in detect_escapes(commits)]


class TestConfirmedRateCanary:
    """The gauge CAN go non-zero from a known revert / regression-pin window."""

    def test_known_revert_and_pin_window_yields_nonzero_confirmed_rate(self) -> None:
        commits = [
            _known_revert(),
            _known_regression_pin(),
            _noise_bug_issue(),
            _noise_feature(),
        ]
        records = _records_for(commits)

        # The mechanical pipeline attributes high (revert) + medium (pin).
        confirmed = metrics.confirmed_escapes(records)
        assert {r.detection_source for r in confirmed} == {"revert", "regression-pin"}
        assert {r.attribution_confidence for r in confirmed} == {"high", "medium"}

        # The rolling CONFIRMED count is non-zero within the 30-day window …
        confirmed_count = metrics.rolling_confirmed_escape_count(records, _NOW, days=30)
        assert confirmed_count == 2

        # … so the confirmed-per-100-merges gauge is strictly non-zero.
        confirmed_rate = metrics.escapes_per_100_merges(confirmed_count, 100)
        assert confirmed_rate > 0.0

        # Sanity: the low-confidence bug-issue row is counted all-confidence but
        # NOT confirmed, so the confirmed rate sits strictly below the headline.
        all_count = metrics.rolling_escape_count(records, _NOW, days=30)
        assert all_count == 3
        assert confirmed_rate < metrics.escapes_per_100_merges(all_count, 100)

    def test_canary_would_fail_if_confirmed_confidences_were_degenerate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Prove the canary is not vacuously green: emptying CONFIRMED_CONFIDENCES
        # (the exact "degenerate by construction" failure #10504 warns about)
        # collapses the very same non-zero window back to a stuck zero. If this
        # assertion ever fails, the guard above has stopped guarding.
        records = _records_for([_known_revert(), _known_regression_pin()])
        monkeypatch.setattr(metrics, "CONFIRMED_CONFIDENCES", ())

        assert metrics.confirmed_escapes(records) == []
        stuck_count = metrics.rolling_confirmed_escape_count(records, _NOW, days=30)
        assert stuck_count == 0
        assert metrics.escapes_per_100_merges(stuck_count, 100) == 0.0

    def test_healthy_zero_is_a_real_reachable_state(self) -> None:
        # The other side of falsifiability: a window of only ordinary bug-issue
        # closes is a genuine HEALTHY zero (no confirmed escapes), distinct from
        # the broken zero above. The gauge reports zero here for the right reason.
        records = _records_for([_noise_bug_issue(), _noise_feature()])
        assert metrics.rolling_escape_count(records, _NOW, days=30) == 1
        assert metrics.rolling_confirmed_escape_count(records, _NOW, days=30) == 0
        assert (
            metrics.escapes_per_100_merges(
                metrics.rolling_confirmed_escape_count(records, _NOW, days=30), 100
            )
            == 0.0
        )
