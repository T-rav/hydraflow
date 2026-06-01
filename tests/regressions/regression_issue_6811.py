"""Regression test for issue #6811.

The outer ``try/except Exception`` in ``verify_proposals`` (lines 572-638)
wraps the entire proposal-iteration loop.  A single corrupt proposal record
— e.g. one with ``pre_count=None`` bypassing Pydantic validation, or one
whose ``proposed_at`` is a non-string type — triggers an uncaught TypeError
or AttributeError that propagates to the outer catch and aborts verification
for ALL remaining proposals.

Issue #6580 demonstrated this with ``update_proposal_verified`` raising; this
test covers a distinct vector: corrupt *data* on the proposal object itself
causing exceptions in the comparison/arithmetic logic (lines 608-634) that
the inner ``try/except ValueError`` (lines 592-603) does not catch.

These tests will fail (RED) until per-proposal exception isolation is added
inside the ``for category, proposal in meta.items()`` loop.
"""

from __future__ import annotations

import pytest

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from models import ReviewVerdict
from review_insights import (
    ProposalMetadata,
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


class TestCorruptProposalDataAbortsEntireSweep:
    """Issue #6811: corrupt proposal *data* (not store operations) should not
    abort verification of remaining proposals.

    Distinct from #6580 which tested store-method exceptions — this covers
    corrupt field values on ProposalMetadata objects that cause TypeErrors
    in the comparison logic (lines 608-634), outside the inner try/except.
    """

    @pytest.mark.xfail(reason="Regression for issue #6811 — fix not yet landed", strict=False)
    def test_none_pre_count_does_not_abort_remaining_proposals(
        self, tmp_path: Path
    ) -> None:
        """A proposal with ``pre_count=None`` (bypassing validation) causes a
        ``TypeError`` at ``proposal.pre_count > 0`` (line 609).  This is NOT
        caught by the inner ``try/except ValueError`` and propagates to the
        outer catch, aborting the loop.

        With per-proposal isolation, the corrupt entry is skipped and remaining
        proposals are still evaluated.
        """
        store = _make_store(tmp_path)

        # Set up three valid proposals, then corrupt one via model_construct.
        store.record_proposal("good_stale", pre_count=5)
        store.record_proposal("corrupt", pre_count=10)
        store.record_proposal("also_stale", pre_count=3)

        meta = store.load_proposal_metadata()
        old = _old_timestamp(35)
        for cat in meta:
            meta[cat].proposed_at = old

        # Corrupt "corrupt" entry: pre_count=None bypasses Pydantic validation
        # via model_construct, simulating a deserialized record with bad data.
        meta["corrupt"] = ProposalMetadata.model_construct(
            pre_count=None,
            proposed_at=old,
            verified=False,
        )
        store.save_proposal_metadata(meta)

        # Reload to get the metadata through the normal path.  The JSON will
        # have ``"pre_count": null`` which Pydantic may coerce or reject —
        # so we patch load_proposal_metadata to return the crafted dict directly.
        crafted_meta = {
            "good_stale": ProposalMetadata(
                pre_count=5, proposed_at=old, verified=False
            ),
            "corrupt": ProposalMetadata.model_construct(
                pre_count=None, proposed_at=old, verified=False
            ),
            "also_stale": ProposalMetadata(
                pre_count=3, proposed_at=old, verified=False
            ),
        }

        # Records: good_stale has 5 hits (unchanged → stale), corrupt has 10,
        # also_stale has 3 hits (unchanged → stale).
        records = (
            [_make_record(categories=["good_stale"]) for _ in range(5)]
            + [_make_record(categories=["corrupt"]) for _ in range(10)]
            + [_make_record(categories=["also_stale"]) for _ in range(3)]
        )

        with patch.object(store, "load_proposal_metadata", return_value=crafted_meta):
            stale = verify_proposals(store, records)

        # Bug: TypeError from "corrupt" aborts the loop.
        # "good_stale" may or may not be in the list depending on iteration order,
        # but "also_stale" (which appears after "corrupt") must be present.
        assert "also_stale" in stale, (
            "Expected 'also_stale' in stale list — the TypeError from 'corrupt' "
            "(pre_count=None) should not abort processing of subsequent proposals"
        )

    @pytest.mark.xfail(reason="Regression for issue #6811 — fix not yet landed", strict=False)
    def test_non_string_proposed_at_type_error_does_not_abort(
        self, tmp_path: Path
    ) -> None:
        """A proposal with ``proposed_at`` set to an integer (bypassing
        validation) causes a ``TypeError`` when ``datetime.fromisoformat``
        receives a non-string.  The inner try catches ``ValueError`` but NOT
        ``TypeError``, so the exception propagates to the outer catch.

        With per-proposal isolation, the corrupt entry is skipped.
        """
        store = _make_store(tmp_path)

        old = _old_timestamp(35)
        crafted_meta = {
            "before": ProposalMetadata(pre_count=4, proposed_at=old, verified=False),
            "bad_timestamp": ProposalMetadata.model_construct(
                pre_count=5,
                proposed_at=12345,
                verified=False,  # int, not str
            ),
            "after": ProposalMetadata(pre_count=2, proposed_at=old, verified=False),
        }

        # "before" count=4 (same → stale), "after" count=2 (same → stale).
        records = (
            [_make_record(categories=["before"]) for _ in range(4)]
            + [_make_record(categories=["bad_timestamp"]) for _ in range(5)]
            + [_make_record(categories=["after"]) for _ in range(2)]
        )

        with patch.object(store, "load_proposal_metadata", return_value=crafted_meta):
            stale = verify_proposals(store, records)

        # Bug: TypeError from bad_timestamp aborts the loop, losing "after".
        assert "after" in stale, (
            "Expected 'after' in stale list — the TypeError from "
            "'bad_timestamp' (proposed_at=int) should not abort subsequent proposals"
        )

    @pytest.mark.xfail(reason="Regression for issue #6811 — fix not yet landed", strict=False)
    def test_attribute_error_on_proposal_does_not_abort(self, tmp_path: Path) -> None:
        """A proposal object missing expected attributes (e.g. a plain dict
        sneaked through somehow) causes an ``AttributeError``.  The outer
        try/except catches it and kills the loop.

        With per-proposal isolation, the malformed entry is skipped.
        """
        store = _make_store(tmp_path)

        old = _old_timestamp(35)

        # Use a mock-like object that has .verified but lacks .proposed_at
        class BrokenProposal(BaseModel):
            pre_count: int = 5
            verified: bool = False
            # no proposed_at field

        crafted_meta = {
            "healthy": ProposalMetadata(pre_count=6, proposed_at=old, verified=False),
            "broken": BrokenProposal(pre_count=5, verified=False),  # type: ignore[dict-item]
            "also_healthy": ProposalMetadata(
                pre_count=3, proposed_at=old, verified=False
            ),
        }

        records = (
            [_make_record(categories=["healthy"]) for _ in range(6)]
            + [_make_record(categories=["broken"]) for _ in range(5)]
            + [_make_record(categories=["also_healthy"]) for _ in range(3)]
        )

        with patch.object(store, "load_proposal_metadata", return_value=crafted_meta):
            stale = verify_proposals(store, records)

        assert "also_healthy" in stale, (
            "Expected 'also_healthy' in stale list — the AttributeError from "
            "'broken' (missing proposed_at) should not abort subsequent proposals"
        )
