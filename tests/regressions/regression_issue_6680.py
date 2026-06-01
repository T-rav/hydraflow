"""Regression test for issue #6680.

``ReviewInsightStore.load_recent`` (line 281),
``ReviewInsightStore.load_proposal_metadata`` (line 312), and
``verify_proposals`` (line 636) use bare ``except Exception`` handlers
that log-and-continue without calling ``reraise_on_credit_or_bug``.

This means programming bugs (``TypeError``, ``AttributeError``) inside
these methods are silently swallowed as if they were benign parse errors.

Test 1: ``TypeError`` raised during ``ReviewRecord.model_validate_json``
must propagate from ``load_recent``.  Currently FAILS — the handler on
line 281 catches it and logs a warning.

Test 2: ``TypeError`` raised during ``ProposalMetadata.model_validate``
must propagate from ``load_proposal_metadata``.  Currently FAILS — the
inner handler on line 312 catches it.

Test 3: ``AttributeError`` raised inside the ``verify_proposals`` try
block must propagate.  Currently FAILS — the handler on line 636 logs
via ``logger.exception`` but swallows the error.

Test 4 (green guard): A ``json.JSONDecodeError`` in ``load_recent``
should still be caught and skipped — transient/data errors are not bugs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from models import ReviewVerdict
from review_insights import (
    ProposalMetadata,
    ReviewInsightStore,
    ReviewRecord,
    verify_proposals,
)


def _make_store(tmp_path: Path) -> ReviewInsightStore:
    """Build a ReviewInsightStore backed by *tmp_path*."""
    return ReviewInsightStore(memory_dir=tmp_path)


# ---------------------------------------------------------------------------
# Test 1: TypeError in load_recent must propagate
# ---------------------------------------------------------------------------


class TestLoadRecentTypeError:
    """A TypeError during model_validate_json is a programming bug (e.g.
    a validator receives an unexpected type) and must not be silently
    swallowed by the except Exception handler on line 281."""

    @pytest.mark.xfail(reason="Regression for issue #6680 — fix not yet landed", strict=False)
    def test_type_error_in_model_validate_json_propagates(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        # Write a valid-looking JSONL line so the loop body executes
        reviews_path = tmp_path / "reviews.jsonl"
        reviews_path.write_text(
            '{"pr_number":1,"issue_number":1,"timestamp":"2026-01-01T00:00:00Z","verdict":"approve","summary":"ok","fixes_made":false,"categories":[]}\n'
        )

        with patch.object(
            ReviewRecord,
            "model_validate_json",
            side_effect=TypeError("argument of type 'NoneType' is not iterable"),
        ):
            # BUG: should raise TypeError, but the bare except Exception
            # on line 281 catches it and logs a warning instead
            with pytest.raises(TypeError, match="NoneType"):
                store.load_recent(n=10)


# ---------------------------------------------------------------------------
# Test 2: TypeError in load_proposal_metadata must propagate
# ---------------------------------------------------------------------------


class TestLoadProposalMetadataTypeError:
    """A TypeError during ProposalMetadata.model_validate is a programming
    bug and must propagate from the inner except Exception on line 312."""

    @pytest.mark.xfail(reason="Regression for issue #6680 — fix not yet landed", strict=False)
    def test_type_error_in_model_validate_propagates(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        # Write valid proposal_metadata.json so we enter the inner loop
        meta_path = tmp_path / "proposal_metadata.json"
        meta_path.write_text(
            json.dumps(
                {
                    "missing_tests": {
                        "pre_count": 5,
                        "proposed_at": "2026-01-01T00:00:00Z",
                        "verified": False,
                    }
                }
            )
        )

        with patch.object(
            ProposalMetadata,
            "model_validate",
            side_effect=TypeError("expected str, got NoneType"),
        ):
            # BUG: should raise TypeError, but the inner except Exception
            # on line 312 catches it and logs a warning
            with pytest.raises(TypeError, match="expected str"):
                store.load_proposal_metadata()


# ---------------------------------------------------------------------------
# Test 3: AttributeError in verify_proposals must propagate
# ---------------------------------------------------------------------------


class TestVerifyProposalsAttributeError:
    """An AttributeError inside the verify_proposals try block is a
    programming bug and must propagate.  The except Exception on line 636
    currently swallows it."""

    @pytest.mark.xfail(reason="Regression for issue #6680 — fix not yet landed", strict=False)
    def test_attribute_error_propagates(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        # Create a minimal record
        record = ReviewRecord(
            pr_number=1,
            issue_number=1,
            timestamp="2026-01-01T00:00:00Z",
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="missing tests",
            fixes_made=False,
            categories=["missing_tests"],
        )

        # Store proposal metadata with an unverified entry
        meta = {
            "missing_tests": ProposalMetadata(
                pre_count=5,
                proposed_at="2026-01-01T00:00:00Z",
                verified=False,
            ),
        }
        store.save_proposal_metadata(meta)

        with patch.object(
            store,
            "load_proposal_metadata",
            side_effect=AttributeError("'NoneType' object has no attribute 'items'"),
        ):
            # BUG: should raise AttributeError, but the except Exception
            # on line 636 catches it and logs via logger.exception
            with pytest.raises(AttributeError, match="has no attribute"):
                verify_proposals(store, [record])


# ---------------------------------------------------------------------------
# Test 4 (green guard): json.JSONDecodeError in load_recent is transient
# ---------------------------------------------------------------------------


class TestLoadRecentTransientError:
    """A JSONDecodeError from a malformed line is NOT a programming bug —
    it should be caught and the line skipped.  This test is GREEN today
    and guards against over-correction when fixing the bug."""

    def test_json_decode_error_is_skipped(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)

        # Write one malformed line followed by a valid line
        reviews_path = tmp_path / "reviews.jsonl"
        valid_line = '{"pr_number":1,"issue_number":1,"timestamp":"2026-01-01T00:00:00Z","verdict":"approve","summary":"ok","fixes_made":false,"categories":[]}'
        reviews_path.write_text(f"NOT VALID JSON\n{valid_line}\n")

        # The malformed line should be skipped, the valid line returned
        # (Pydantic's model_validate_json raises ValidationError, not
        # JSONDecodeError, but the except Exception correctly catches both
        # non-bug errors today)
        records = store.load_recent(n=10)
        assert len(records) == 1
        assert records[0].pr_number == 1
