"""Regression guards for the #10367 escape-ledger hardening review.

Three review findings on the escape-ledger measurement instrument:

1. **Escape-headline inflation.** ``rolling_escape_count`` counted ALL rows
   regardless of confidence; in a fix-heavy repo every ``fix(...): fixes #N``
   merge is a low-confidence ``bug-issue`` row, so the headline "escapes per 100
   merges" conflated ordinary issue resolution with real gate escapes. Guard: a
   CONFIRMED-only (high/medium-confidence) count exists and low-confidence rows
   do not inflate it.

2. **p90 rank-off-by-one.** ``_percentile`` used ``round`` not nearest-rank
   ``ceil``, landing one rank low at small n (p90 of 5 → rank 4 not 5). Guard:
   p90 of ttd 1..5 is 5.0.

3. **Bogus sha references.** ``extract_referenced_shas`` matched any 7-40 hex
   token, so a pure-digit number or an all-letter hex-looking word could be
   mistaken for an originating merge sha (mis-attributing an escape). Guard:
   only real-sha-shaped tokens (a digit AND an a-f letter) are extracted.
"""

from __future__ import annotations

from datetime import UTC, datetime

from escape import attribution, metrics
from escape.models import EscapeRecord


def _record(
    rid: str,
    *,
    source: str = "revert",
    confidence: str = "high",
    ttd: float | None = 24.0,
    detected_at: str = "2026-01-20T00:00:00+00:00",
) -> EscapeRecord:
    return EscapeRecord(
        id=rid,
        detected_at=detected_at,
        detection_source=source,
        detection_ref=rid.split(":", 1)[-1],
        originating_pr=None,
        originating_merge_sha="abc1234",
        merged_at="2026-01-19T00:00:00+00:00",
        time_to_detection_hours=ttd,
        attribution_method="revert-parse",
        attribution_confidence=confidence,
        encoded_as="none-yet",
        notes="",
    )


class TestConfirmedEscapeHeadline:
    def test_low_confidence_rows_do_not_inflate_confirmed_count(self) -> None:
        now = datetime(2026, 2, 1, tzinfo=UTC)
        recs = [
            _record("revert:a", confidence="high"),
            _record("bug-issue:b", source="bug-issue", confidence="low"),
        ]
        assert metrics.rolling_escape_count(recs, now, days=30) == 2
        assert metrics.rolling_confirmed_escape_count(recs, now, days=30) == 1


class TestPercentileNearestRank:
    def test_p90_of_five_is_the_max(self) -> None:
        recs = [_record(f"revert:{i}", ttd=float(i)) for i in range(1, 6)]
        stats = metrics.time_to_detection_stats(recs)
        assert stats["overall"].p90_hours == 5.0


class TestShaReferenceTightening:
    def test_bogus_tokens_rejected_real_sha_kept(self) -> None:
        assert attribution.extract_referenced_shas("closes 12345678 today") == []
        assert attribution.extract_referenced_shas("the deadbeef word") == []
        assert attribution.extract_referenced_shas("from 9f8e7d6c5b4a") == [
            "9f8e7d6c5b4a"
        ]
