"""Unit tests for the escape-surfaces link store (#10577).

``escape.surfaces.SurfacedIssueLedger`` ties a filed HITL/``hydraflow-find``
issue back to the ledger row that produced it: one append-only row per
surfacing carrying the issue number, superseded last-row-wins per fingerprint so
a terminal ``closed`` row is idempotent across restarts.
"""

from __future__ import annotations

import json
from pathlib import Path

from escape.surfaces import SurfacedIssue, SurfacedIssueLedger


def _path(tmp_path: Path) -> Path:
    return tmp_path / "diagnostics" / "escape_surfaces.jsonl"


def test_append_then_read_back_returns_issue_number(tmp_path: Path) -> None:
    ledger = SurfacedIssueLedger(_path(tmp_path))
    ledger.append_surfaced(
        fingerprint="surfaced:aging:bug-issue:a",
        escape_id="bug-issue:a",
        reason="aging",
        issue_number=9012,
        filed_at="2026-07-24T00:00:00+00:00",
    )

    (link,) = ledger.open_links()
    assert link.escape_id == "bug-issue:a"
    assert link.reason == "aging"
    assert link.issue_number == 9012


def test_fingerprint_with_later_closed_row_is_absent_from_open_links(
    tmp_path: Path,
) -> None:
    ledger = SurfacedIssueLedger(_path(tmp_path))
    link = ledger.append_surfaced(
        fingerprint="surfaced:aging:bug-issue:a",
        escape_id="bug-issue:a",
        reason="aging",
        issue_number=9012,
        filed_at="2026-07-24T00:00:00+00:00",
    )

    ledger.append_closed(link, closed_at="2026-07-25T00:00:00+00:00")

    assert ledger.open_links() == []
    # The audit trail is preserved: both rows are still on disk, un-rewritten.
    assert len(ledger.read_all()) == 2


def test_open_links_keeps_other_fingerprints_when_one_is_closed(
    tmp_path: Path,
) -> None:
    ledger = SurfacedIssueLedger(_path(tmp_path))
    closed_me = ledger.append_surfaced(
        fingerprint="surfaced:aging:bug-issue:a",
        escape_id="bug-issue:a",
        reason="aging",
        issue_number=9012,
        filed_at="2026-07-24T00:00:00+00:00",
    )
    ledger.append_surfaced(
        fingerprint="surfaced:low-confidence:bug-issue:b",
        escape_id="bug-issue:b",
        reason="low-confidence",
        issue_number=9013,
        filed_at="2026-07-24T00:00:00+00:00",
    )

    ledger.append_closed(closed_me, closed_at="2026-07-25T00:00:00+00:00")

    open_numbers = {link.issue_number for link in ledger.open_links()}
    assert open_numbers == {9013}


def test_reading_a_missing_ledger_returns_no_links(tmp_path: Path) -> None:
    ledger = SurfacedIssueLedger(_path(tmp_path))
    assert ledger.open_links() == []
    assert ledger.read_all() == []


def test_malformed_line_is_skipped_not_raised(tmp_path: Path) -> None:
    path = _path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    good = SurfacedIssue(
        fingerprint="surfaced:aging:bug-issue:a",
        escape_id="bug-issue:a",
        reason="aging",
        issue_number=9012,
        filed_at="2026-07-24T00:00:00+00:00",
    )
    path.write_text(
        "not json at all\n" + json.dumps(good.to_json_dict()) + "\n",
        encoding="utf-8",
    )

    (link,) = SurfacedIssueLedger(path).open_links()
    assert link.issue_number == 9012


def test_last_row_wins_per_fingerprint(tmp_path: Path) -> None:
    # A later open row for the same fingerprint supersedes an earlier one.
    ledger = SurfacedIssueLedger(_path(tmp_path))
    ledger.append_surfaced(
        fingerprint="surfaced:aging:bug-issue:a",
        escape_id="bug-issue:a",
        reason="aging",
        issue_number=1,
        filed_at="2026-07-24T00:00:00+00:00",
    )
    ledger.append_surfaced(
        fingerprint="surfaced:aging:bug-issue:a",
        escape_id="bug-issue:a",
        reason="aging",
        issue_number=2,
        filed_at="2026-07-24T01:00:00+00:00",
    )

    (link,) = ledger.open_links()
    assert link.issue_number == 2
