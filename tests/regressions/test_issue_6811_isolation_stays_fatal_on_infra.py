"""Per-record isolation must not absorb the infra-fatal signals.

#6580 and #6811 moved the ``try/except`` inside ``verify_proposals``'s
per-category loop so one corrupt record can no longer end the sweep. That
isolation is deliberately broad — a record's failure is a fact about the
record, not the code — which means it would just as happily have swallowed
an exhausted billing budget or a dead credential, once per remaining
category, while reporting a clean sweep.

``INFRA_FATAL_EXCEPTIONS`` is re-raised ahead of it for that reason. These
tests pin that ordering: nothing in #6580/#6811 fails if the re-raise clause
is deleted, because every case those issues describe is one the isolation is
*supposed* to absorb.

The RuntimeError case is the decoy. Without it a test that simply asserted
"verify_proposals raises" would also pass against no isolation at all.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from exception_classify import INFRA_FATAL_EXCEPTIONS
from models import ReviewVerdict
from review_insights import ReviewInsightStore, ReviewRecord, verify_proposals
from subprocess_util import AuthenticationError, CreditExhaustedError


def _record(category: str) -> ReviewRecord:
    return ReviewRecord(
        pr_number=101,
        issue_number=42,
        timestamp="2026-02-20T10:30:00Z",
        verdict=ReviewVerdict.REQUEST_CHANGES,
        summary="Test record",
        fixes_made=False,
        categories=[category],
    )


def _store_with_two_verifiable_proposals(tmp_path: Path) -> ReviewInsightStore:
    """Two proposals that both take the ``update_proposal_verified`` branch.

    Each has a pre_count high enough that one matching record is a >50% drop,
    so the loop calls the store for BOTH — the first raises, and whether the
    second is reached is what these tests are about.
    """
    store = ReviewInsightStore(tmp_path)
    store.record_proposal("aaa", pre_count=10)
    store.record_proposal("bbb", pre_count=10)
    meta = store.load_proposal_metadata()
    old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    for entry in meta.values():
        entry.proposed_at = old
    store.save_proposal_metadata(meta)
    return store


@pytest.mark.parametrize(
    "exc",
    [
        CreditExhaustedError("billing budget exhausted"),
        AuthenticationError("credential rejected"),
        MemoryError("no headroom"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_infra_fatal_from_inside_the_loop_propagates(
    tmp_path: Path, exc: BaseException
) -> None:
    """An infra-fatal raised per-record escapes, rather than being isolated."""
    assert isinstance(exc, INFRA_FATAL_EXCEPTIONS), (
        f"{type(exc).__name__} is not in INFRA_FATAL_EXCEPTIONS — this test "
        "would be asserting the isolation branch, not the re-raise branch"
    )
    store = _store_with_two_verifiable_proposals(tmp_path)
    records = [_record("aaa"), _record("bbb")]

    with (
        patch.object(store, "update_proposal_verified", side_effect=exc),
        pytest.raises(type(exc)),
    ):
        verify_proposals(store, records)


def test_a_non_fatal_error_is_still_isolated(tmp_path: Path) -> None:
    """The decoy: an ordinary failure stays absorbed, per #6580/#6811.

    Without this, deleting the isolation entirely would leave the tests above
    passing — every exception would propagate and they could not tell the
    difference.
    """
    store = _store_with_two_verifiable_proposals(tmp_path)
    records = [_record("aaa"), _record("bbb")]

    calls: list[str] = []

    def _explode(category: str, *, verified: bool) -> None:
        calls.append(category)
        raise RuntimeError("simulated per-record failure")

    with patch.object(store, "update_proposal_verified", side_effect=_explode):
        verify_proposals(store, records)  # must not raise

    assert calls == ["aaa", "bbb"], (
        "Both categories should have been attempted — the first one's "
        f"RuntimeError must not end the sweep. Attempted: {calls}"
    )
