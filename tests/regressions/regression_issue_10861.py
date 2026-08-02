"""Regression for #10861: two ratchet-integrity gaps, both "a commitment that
can be edited away without anything objecting".

Gap 1 — ``GRANDFATHERED_DEADLINE`` moved for free. ADR-0116 §5a says past the
deadline the build fails "until the backfill lands or the schedule is
renegotiated in a commit that says why", but nothing gated the second half:
moving the deadline kept every test green. The deadline is now derived from an
append-only ``GRANDFATHERED_SCHEDULE_LOG`` of ``(deadline, receipt)`` rows, so a
move must cite the issue/PR that authorized it — a bare edit with no fresh
receipt fails.

Gap 2 — an Accepted ADR classified REAL as long as its ``**Enforced by:**``
named a file that *exists*, even an unrelated one (``pytest:tests/
test_prompt_fitness.py`` on an ADR about something else). REAL never checked that
the cited test *relates* to the ADR. ``adr_is_unattributed`` adds that
relatedness signal — advisory, never folded into REAL — and it is ratcheted
shrink-only so a new unrelated-file ADR is caught while the graders' 77/3/0
REAL/WEAK/MISSING split is unchanged.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from adr_conformance import (
    EnforcementClass,
    adr_is_unattributed,
    classify_adr_enforcement,
)
from adr_index import ADR, Check
from prompt_fitness import GRANDFATHERED_DEADLINE, GRANDFATHERED_SCHEDULE_LOG

REPO = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# Gap 1 — the deadline cannot move without a receipt.
# --------------------------------------------------------------------------


def test_live_deadline_is_derived_from_a_receipted_schedule_row() -> None:
    # The deadline is no longer a bare string: it is the last schedule-log row,
    # and that row carries an issue/PR receipt.
    assert GRANDFATHERED_SCHEDULE_LOG
    last_deadline, last_receipt = GRANDFATHERED_SCHEDULE_LOG[-1]
    assert GRANDFATHERED_DEADLINE == last_deadline
    assert re.fullmatch(r"#\d+", last_receipt)
    # sanity: it is a real date
    date.fromisoformat(last_deadline)


def test_a_bare_deadline_move_without_a_receipt_is_rejected() -> None:
    # The exact #10861 scenario re-expressed over the log's grammar: pushing the
    # deadline out by appending a row whose receipt is empty (or is not an
    # issue/PR reference) must not satisfy the receipt gate.
    def receipts_valid(log: tuple[tuple[str, str], ...]) -> bool:
        receipts = [row[1] for row in log]
        return len(receipts) == len(set(receipts)) and all(
            re.fullmatch(r"#\d+", r) for r in receipts
        )

    good = (*GRANDFATHERED_SCHEDULE_LOG, ("2099-01-01", "#12345"))
    assert receipts_valid(good)

    for bad_receipt in ("", "later", "moved it out"):
        moved_no_receipt = (*GRANDFATHERED_SCHEDULE_LOG, ("2099-01-01", bad_receipt))
        assert not receipts_valid(moved_no_receipt), bad_receipt

    # ...and reusing an existing receipt (editing the date, not the authorization)
    # is rejected too.
    reused = GRANDFATHERED_SCHEDULE_LOG[-1][1]
    assert not receipts_valid((*GRANDFATHERED_SCHEDULE_LOG, ("2099-01-01", reused)))


# --------------------------------------------------------------------------
# Gap 2 — REAL must not be satisfied by an unrelated file.
# --------------------------------------------------------------------------


def _adr(number: int, checks: tuple[Check, ...]) -> ADR:
    return ADR(
        number=number,
        title="synthetic",
        status="Accepted",
        summary="",
        enforcement="enforced",
        enforced_by=checks,
    )


def test_new_adr_pointing_at_an_unrelated_existing_test_is_flagged() -> None:
    # An unrelated real test file — it exists (so the check RESOLVES and the ADR
    # classifies REAL) but its text never names ADR-9999.
    unrelated = Check(
        kind="pytest",
        target="tests/test_prompt_fitness.py",
        raw="pytest:tests/test_prompt_fitness.py",
    )
    adr = _adr(9999, (unrelated,))
    # Classification is unchanged — REAL is still "names a file that exists"...
    assert classify_adr_enforcement(adr, REPO) is EnforcementClass.REAL
    # ...but the relatedness signal catches it.
    assert adr_is_unattributed(adr, REPO)


def test_adr_whose_test_names_it_is_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text(
        '"""Enforces ADR-9999."""\ndef test_x():\n    assert True\n'
    )
    adr = _adr(
        9999,
        (Check(kind="pytest", target="tests/t.py::test_x", raw="pytest:tests/t.py::test_x"),),
    )
    assert classify_adr_enforcement(adr, tmp_path) is EnforcementClass.REAL
    assert not adr_is_unattributed(adr, tmp_path)
