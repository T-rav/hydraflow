"""Regression guard for #10654: escape ledger double-counts one commit.

``EscapeCandidate.id`` folds ``detection_source`` into its dedup key
(``f"{detection_source}:{detection_ref}"``), so when one underlying commit is
detected under two distinct sources — the live case: a ``fix(...)`` close that
also adds a ``tests/regressions/`` pin, surfacing as BOTH a ``bug-issue``/low
row and a ``regression-pin``/medium row for the SAME ``detection_ref`` — the two
rows carry different ids. ``metrics.latest_by_id`` collapses only by id, so both
survive every derived read (``encoded_summary().total``, ``rolling_escape_count``,
the aging/low-confidence HITL surfaces), counting the one commit twice.

Live evidence at filing (``.hydraflow/diagnostics/escape_ledger.jsonl``): two
commits each had a ``bug-issue``/low and a ``regression-pin``/medium row for the
same ``detection_ref``::

    bug-issue:ee56677201303fa4de5b1dec341447d4a12076d4        (low,    none-yet)
    regression-pin:ee56677201303fa4de5b1dec341447d4a12076d4   (medium, none-yet)
    bug-issue:055267e7b2b7900d615b0ff8553ef511dc3e8652        (low,    none-yet)
    regression-pin:055267e7b2b7900d615b0ff8553ef511dc3e8652   (medium, none-yet)

Guard: the two-stage ``metrics.latest_by_escape`` collapse (id, then
``detection_ref``) folds each pair to exactly one row at the stronger (medium)
confidence, and ``EscapeLedger.read_latest`` — the single point every consumer
reads through — delegates to it, so the same commit surfaces as ONE escape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from escape import metrics
from escape.ledger import EscapeLedger
from escape.models import EscapeRecord

# The two live commits, each detected under both sources (issue body).
_SHA_A = "ee56677201303fa4de5b1dec341447d4a12076d4"
_SHA_B = "055267e7b2b7900d615b0ff8553ef511dc3e8652"


def _row(
    source: str,
    ref: str,
    *,
    confidence: str,
    encoded_as: str = "none-yet",
    detected_at: str = "2026-07-20T00:00:00+00:00",
) -> EscapeRecord:
    """A ledger row shaped like the live duplicate pair — id folds the source."""
    return EscapeRecord(
        id=f"{source}:{ref}",
        detected_at=detected_at,
        detection_source=source,
        detection_ref=ref,
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain" if source == "bug-issue" else "regression-pin",
        attribution_confidence=confidence,
        encoded_as=encoded_as,
        notes="",
    )


def _live_duplicate_pairs() -> list[EscapeRecord]:
    """The exact live shape: a bug-issue/low then a regression-pin/medium row
    for each of the two commits (append order as they landed on disk)."""
    return [
        _row("bug-issue", _SHA_A, confidence="low"),
        _row("regression-pin", _SHA_A, confidence="medium"),
        _row("bug-issue", _SHA_B, confidence="low"),
        _row("regression-pin", _SHA_B, confidence="medium"),
    ]


class TestIssue10654EscapeDoubleCount:
    def test_latest_by_escape_collapses_each_live_pair_to_one_medium_row(self) -> None:
        collapsed = metrics.latest_by_escape(_live_duplicate_pairs())

        # Exactly one row per underlying commit (detection_ref), not two.
        assert {r.detection_ref for r in collapsed} == {_SHA_A, _SHA_B}
        assert len(collapsed) == 2
        # The stronger (medium regression-pin) source wins each pair.
        assert all(r.detection_source == "regression-pin" for r in collapsed)
        assert all(r.attribution_confidence == "medium" for r in collapsed)

    def test_encoded_summary_and_rolling_count_count_each_commit_once(self) -> None:
        rows = _live_duplicate_pairs()
        now = datetime(2026, 7, 26, tzinfo=UTC)

        # Uncollapsed, the four rows count the two commits twice.
        assert metrics.encoded_summary(rows).total == 4
        assert metrics.rolling_escape_count(rows, now, days=60) == 4

        collapsed = metrics.latest_by_escape(rows)

        # Collapsed, each commit counts exactly once.
        assert metrics.encoded_summary(collapsed).total == 2
        assert metrics.rolling_escape_count(collapsed, now, days=60) == 2

    def test_ledger_read_latest_dedups_the_live_pairs_on_disk(
        self, tmp_path: Path
    ) -> None:
        # The single point every consumer reads through must dedup the pairs.
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        for row in _live_duplicate_pairs():
            ledger.append(row)

        # All four lines survive on disk (append-only audit trail)...
        assert len(ledger.read_all()) == 4
        # ...but the derived read surfaces one row per commit.
        latest = ledger.read_latest()
        assert {r.detection_ref for r in latest} == {_SHA_A, _SHA_B}
        assert len(latest) == 2
