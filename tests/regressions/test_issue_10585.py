"""Regression test for issue #10585.

Bug: ``EscapeLedgerLoop._surface_findings`` recorded the reason-scoped
surfacing fingerprint (``surfaced:<reason>:<id>``) into the
``escape_ledger_recorded`` DedupStore whenever ``create_issue`` did not RAISE.
But ``PRPort.create_issue`` returns ``0`` on a filing failure WITHOUT raising
(see ``src/ports.py`` — "Returns the new issue number (0 on failure)"). A
failed filing therefore permanently consumed the escape/reason pair's one-shot
surfacing budget, so the escape was never re-surfaced even though no GitHub
issue existed.

Fix: only spend the fingerprint AFTER ``create_issue`` reports success (issue
number > 0). On the ``0``-sentinel, log it and leave the fingerprint unspent so
the next tick retries — mirroring ``adr_touchpoint_auditor_loop``'s
"create_issue returned 0 → don't record" guard.

These tests assert the CORRECT (post-fix) behaviour and are GREEN once the fix
lands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from escape.ledger import EscapeLedger
from escape.models import EscapeRecord
from escape_ledger_loop import (
    SURFACE_REASON_LOW_CONFIDENCE,
    EscapeLedgerLoop,
    surfacing_fingerprint,
)
from tests.helpers import make_bg_loop_deps


def _make_state() -> MagicMock:
    state = MagicMock()
    cursor: dict[str, str] = {"sha": ""}
    state.get_escape_ledger_last_processed_sha.side_effect = lambda: cursor["sha"]
    state.set_escape_ledger_last_processed_sha.side_effect = (
        lambda sha: cursor.__setitem__("sha", sha)
    )
    return state


def _make_dedup() -> MagicMock:
    dedup = MagicMock()
    store: set[str] = set()
    dedup.get.side_effect = lambda: set(store)

    def _set_all(values: set[str]) -> None:
        store.clear()
        store.update(values)

    dedup.set_all.side_effect = _set_all
    dedup._store = store
    return dedup


def _make_loop(tmp_path: Path, pr_manager: Any) -> EscapeLedgerLoop:
    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=pr_manager,
        state=_make_state(),
        dedup=_make_dedup(),
        deps=bg.loop_deps,
    )


def _low_conf_record(rid: str = "bug-issue:x") -> EscapeRecord:
    # Low-confidence but ENCODED (not none-yet) => eligible for the
    # low-confidence surface ONLY, never the aging surface. Isolating to a
    # single reason keeps the assertions on ``filed`` exact (an unencoded row
    # would surface once per reason and double the count).
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
        encoded_as="regression-test",
        notes="",
    )


async def test_failed_filing_zero_sentinel_leaves_fingerprint_unspent(
    tmp_path: Path,
) -> None:
    # create_issue returns the 0-sentinel (filing failed) WITHOUT raising.
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=0)
    loop = _make_loop(tmp_path, pr)
    record = _low_conf_record()
    EscapeLedger(loop._ledger_path).append(record)

    filed, capped = await loop._surface_findings()

    # Nothing was actually filed, and the one-shot budget is NOT consumed.
    assert filed == 0
    assert capped is False
    fp = surfacing_fingerprint(record.id, SURFACE_REASON_LOW_CONFIDENCE)
    assert fp not in loop._dedup._store


async def test_next_tick_resurfaces_after_zero_sentinel_failure(
    tmp_path: Path,
) -> None:
    # After a failed filing (0), a subsequent tick whose create_issue succeeds
    # MUST surface the same escape — the budget was left unspent.
    pr = MagicMock()
    pr.create_issue = AsyncMock(side_effect=[0, 7])
    loop = _make_loop(tmp_path, pr)
    record = _low_conf_record()
    EscapeLedger(loop._ledger_path).append(record)

    first_filed, _ = await loop._surface_findings()
    assert first_filed == 0

    second_filed, _ = await loop._surface_findings()

    assert second_filed == 1
    fp = surfacing_fingerprint(record.id, SURFACE_REASON_LOW_CONFIDENCE)
    assert fp in loop._dedup._store


async def test_successful_filing_spends_fingerprint_and_suppresses_repeat(
    tmp_path: Path,
) -> None:
    # A real issue number (> 0) IS a successful filing: the fingerprint is spent
    # so the same escape/reason is not re-surfaced next tick (no repeat noise).
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=42)
    loop = _make_loop(tmp_path, pr)
    record = _low_conf_record()
    EscapeLedger(loop._ledger_path).append(record)

    filed, _ = await loop._surface_findings()
    assert filed == 1
    fp = surfacing_fingerprint(record.id, SURFACE_REASON_LOW_CONFIDENCE)
    assert fp in loop._dedup._store

    # Second tick: budget spent → nothing re-filed.
    filed_again, _ = await loop._surface_findings()
    assert filed_again == 0
    assert pr.create_issue.await_count == 1
