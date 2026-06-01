"""Regression test for issue #6580.

``verify_proposals`` wraps its entire proposal-iteration loop in a single
broad ``except Exception`` (line 636).  If processing one proposal raises
(e.g. ``update_proposal_verified`` hits an OSError, or any unexpected
exception), the entire stale-proposal sweep aborts and subsequent proposals
are never processed.  This means stale proposals silently accumulate in the
review-insights memory bank.

This test sets up three proposals — the first triggers ``update_proposal_verified``
which is mocked to raise, the other two are stale.  The bug causes the loop
to abort on the first proposal's exception, returning an empty stale list
instead of ``["beta", "gamma"]``.

These tests will fail (RED) until the ``try/except`` is moved inside the
per-category loop so one bad entry is skipped rather than aborting the pass.
"""

from __future__ import annotations

import pytest

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from models import ReviewVerdict
from review_insights import (
    ReviewInsightStore,
    ReviewRecord,
    verify_proposals,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> ReviewInsightStore:
    return ReviewInsightStore(tmp_path)


def _old_timestamp(days_ago: int = 35) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _make_record(
    *,
    verdict: ReviewVerdict = ReviewVerdict.REQUEST_CHANGES,
    categories: list[str] | None = None,
) -> ReviewRecord:
    return ReviewRecord(
        pr_number=101,
        issue_number=42,
        timestamp="2026-02-20T10:30:00Z",
        verdict=verdict,
        summary="Test record",
        fixes_made=False,
        categories=categories or [],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOneBadProposalAbortsEntireSweep:
    """Issue #6580: a single bad proposal should not abort the whole pass."""

    @pytest.mark.xfail(reason="Regression for issue #6580 — fix not yet landed", strict=False)
    def test_exception_in_update_proposal_verified_does_not_skip_remaining(
        self, tmp_path: Path
    ) -> None:
        """When ``update_proposal_verified`` raises for one category, stale
        proposals that come later in iteration order must still be detected.

        With the bug (outer try/except), the exception aborts the loop and
        stale_categories is returned empty.
        """
        store = _make_store(tmp_path)

        # "alpha": pre_count=10, current_count=2 → >50% drop → triggers
        # update_proposal_verified, which we mock to raise.
        store.record_proposal("alpha", pre_count=10)
        # "beta":  pre_count=5, current_count=5 → unchanged after 35 days → stale
        store.record_proposal("beta", pre_count=5)
        # "gamma": pre_count=3, current_count=3 → unchanged after 35 days → stale
        store.record_proposal("gamma", pre_count=3)

        # Back-date all proposals to 35 days ago so staleness check kicks in.
        meta = store.load_proposal_metadata()
        for cat in meta:
            meta[cat].proposed_at = _old_timestamp(35)
        store.save_proposal_metadata(meta)

        # Build records: alpha appears 2 times (triggers verify), beta 5, gamma 3.
        records = (
            [_make_record(categories=["alpha"]) for _ in range(2)]
            + [_make_record(categories=["beta"]) for _ in range(5)]
            + [_make_record(categories=["gamma"]) for _ in range(3)]
        )

        # Mock update_proposal_verified to raise on "alpha".
        original = store.update_proposal_verified

        def _exploding_update(category: str, *, verified: bool) -> None:
            if category == "alpha":
                raise OSError("disk full — simulated failure")
            original(category, verified=verified)

        with patch.object(
            store, "update_proposal_verified", side_effect=_exploding_update
        ):
            stale = verify_proposals(store, records)

        # With the fix, beta and gamma should be reported as stale.
        # With the bug, the exception from alpha aborts the loop and we get [].
        assert "beta" in stale, (
            "Expected 'beta' in stale list — the exception from 'alpha' "
            "should not abort processing of subsequent proposals"
        )
        assert "gamma" in stale, (
            "Expected 'gamma' in stale list — the exception from 'alpha' "
            "should not abort processing of subsequent proposals"
        )

    @pytest.mark.xfail(reason="Regression for issue #6580 — fix not yet landed", strict=False)
    def test_exception_midway_still_processes_earlier_and_later_proposals(
        self, tmp_path: Path
    ) -> None:
        """If the *middle* proposal raises during verification, proposals
        before and after it should still be processed correctly.

        With the bug, any proposal after the raising one is lost.
        """
        store = _make_store(tmp_path)

        # aaa: stale (unchanged count, old date)
        store.record_proposal("aaa", pre_count=4)
        # bbb: should verify (>50% drop), but update_proposal_verified raises
        store.record_proposal("bbb", pre_count=10)
        # ccc: stale (unchanged count, old date)
        store.record_proposal("ccc", pre_count=2)

        meta = store.load_proposal_metadata()
        for cat in meta:
            meta[cat].proposed_at = _old_timestamp(40)
        store.save_proposal_metadata(meta)

        # aaa count=4 (same → stale), bbb count=2 (80% drop → verify), ccc count=2 (same → stale)
        records = (
            [_make_record(categories=["aaa"]) for _ in range(4)]
            + [_make_record(categories=["bbb"]) for _ in range(2)]
            + [_make_record(categories=["ccc"]) for _ in range(2)]
        )

        # Mock update_proposal_verified to raise only for "bbb".
        original = store.update_proposal_verified

        def _exploding_update(category: str, *, verified: bool) -> None:
            if category == "bbb":
                raise RuntimeError("simulated mid-loop failure")
            original(category, verified=verified)

        with patch.object(
            store, "update_proposal_verified", side_effect=_exploding_update
        ):
            stale = verify_proposals(store, records)

        # aaa was processed before bbb — should be stale.
        assert "aaa" in stale, (
            "Expected 'aaa' in stale list — it was processed before the "
            "failing 'bbb' entry"
        )
        # ccc comes after bbb in iteration order.
        # With the bug, bbb's exception aborts the loop and ccc is never checked.
        assert "ccc" in stale, (
            "Expected 'ccc' in stale list — the exception from 'bbb' "
            "should not abort processing of subsequent proposals"
        )
