"""Regression test for issue #10503.

Bug: ``EscapeLedgerLoop.select_findings_to_surface`` deduped its one-shot
surfacing budget by a per-ID fingerprint (``surfaced:<id>``) that ignored
WHICH criterion made a row eligible. Because a ``bug-issue`` row is BOTH
low-confidence AND (after ``escape_ledger_encoding_age_days``, default 14)
aging-unencoded, surfacing it once for low-confidence permanently consumed the
row's single ``surfaced:<id>`` budget — so the 14-day aging surface could NEVER
fire for that row. An escape that ages past the encoding threshold without an
encoding was silently never re-raised.

Fix: scope the fingerprint per surfacing REASON —
``surfaced:low-confidence:<id>`` vs ``surfaced:aging:<id>`` — so each criterion
gets its own one-shot budget while still suppressing repeat noise from the SAME
criterion. ``eligible_findings`` now returns ``(record, reason)`` pairs so the
caller stores the correct reason-scoped fingerprint.

These tests assert the CORRECT (post-fix) behaviour and are GREEN once the fix
lands.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from escape.models import EscapeRecord
from escape_ledger_loop import (
    SURFACE_REASON_AGING,
    SURFACE_REASON_LOW_CONFIDENCE,
    apply_ask_budget,
    eligible_findings,
    surfacing_fingerprint,
)

# A row detected ~5 months before ``NOW`` — comfortably past the 14-day
# (24 * 14 h) aging threshold — with a ``low`` mechanical confidence and no
# encoding. This is the exact shape the bug hinges on: BOTH low-confidence AND
# aging-unencoded, so it is eligible under both criteria.
NOW = datetime(2026, 6, 1, tzinfo=UTC)
AGING_THRESHOLD_HOURS = 24 * 14


def _low_conf_aging_record(rid: str = "bug-issue:a") -> EscapeRecord:
    return EscapeRecord(
        id=rid,
        detected_at="2026-01-01T00:00:00+00:00",
        detection_source="bug-issue",
        detection_ref=rid.split(":", 1)[-1],
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain",
        attribution_confidence="low",
        encoded_as="none-yet",
        notes="",
    )


def _select(record: EscapeRecord, already_surfaced: set[str]):
    eligible = eligible_findings(
        [record],
        now=NOW,
        aging_threshold_hours=AGING_THRESHOLD_HOURS,
        already_surfaced=already_surfaced,
    )
    return apply_ask_budget(eligible, max_per_tick=10)


def test_fingerprint_is_reason_scoped() -> None:
    assert surfacing_fingerprint("a", SURFACE_REASON_LOW_CONFIDENCE) == (
        "surfaced:low-confidence:a"
    )
    assert surfacing_fingerprint("a", SURFACE_REASON_AGING) == "surfaced:aging:a"
    # The two reasons produce DISTINCT keys for the same id — the crux of the fix.
    assert surfacing_fingerprint("a", SURFACE_REASON_LOW_CONFIDENCE) != (
        surfacing_fingerprint("a", SURFACE_REASON_AGING)
    )


def test_aging_surface_still_fires_after_low_confidence_already_surfaced() -> None:
    # The bug: this row was already surfaced for low-confidence, so its aging
    # surface was permanently unreachable. Post-fix it is STILL selected — for
    # the distinct ``aging`` reason.
    record = _low_conf_aging_record()
    already = {surfacing_fingerprint(record.id, SURFACE_REASON_LOW_CONFIDENCE)}

    to_file, capped = _select(record, already)

    reasons = {reason for _rec, reason in to_file}
    assert reasons == {SURFACE_REASON_AGING}
    assert [rec.id for rec, _r in to_file] == [record.id]
    assert capped is False


def test_low_confidence_surface_still_fires_after_aging_already_surfaced() -> None:
    # Symmetric: consuming the aging budget must not consume the low-confidence
    # budget.
    record = _low_conf_aging_record()
    already = {surfacing_fingerprint(record.id, SURFACE_REASON_AGING)}

    to_file, _capped = _select(record, already)

    reasons = {reason for _rec, reason in to_file}
    assert reasons == {SURFACE_REASON_LOW_CONFIDENCE}


def test_same_reason_is_not_resurfaced() -> None:
    # Repeat noise from the SAME criterion is still suppressed: with BOTH
    # reason-scoped keys already stored, the row is not surfaced again at all.
    record = _low_conf_aging_record()
    already = {
        surfacing_fingerprint(record.id, SURFACE_REASON_LOW_CONFIDENCE),
        surfacing_fingerprint(record.id, SURFACE_REASON_AGING),
    }

    to_file, capped = _select(record, already)

    assert to_file == []
    assert capped is False


def test_both_reasons_selected_once_each_when_nothing_surfaced_yet() -> None:
    # A fresh row eligible under both criteria yields exactly one (record, reason)
    # pair per reason — never collapsed by id into a single one-shot budget.
    record = _low_conf_aging_record()

    to_file, _capped = _select(record, set())

    pairs = {(rec.id, reason) for rec, reason in to_file}
    assert pairs == {
        (record.id, SURFACE_REASON_LOW_CONFIDENCE),
        (record.id, SURFACE_REASON_AGING),
    }
