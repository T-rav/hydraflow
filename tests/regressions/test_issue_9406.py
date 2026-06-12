"""Regression test for issue #9406.

Bug: multiple ADR *numbers* were each claimed by two different ADR files under
``docs/adr/`` (at peak: 0043, 0056, 0057, 0059, 0064, and later 0084).

``scan_adr_directory`` parses both files in each pair, so the runtime index
ends up holding two distinct ``ADR`` objects sharing one ``.number``. This
corrupts the index:

  - ``adrs_touching`` / ``compute_drift`` merge both files' citations under
    one number (the "ADR-0056" drift in #9405 was the union of two unrelated
    ADRs), so the ``adr_touchpoint_auditor`` can never converge — it re-files
    the same drift and escalates to HITL (#9417/#9419/#9420/#9421/#9447).
  - ``adr.title`` / status are ambiguous; dict-keyed callers silently keep
    only one of the two.
  - ``_adr_file_in_diff`` matches on the zero-padded number prefix, so editing
    *either* file reads as "resolving" *both*.

The fix renumbers the later-authored file in each pair to a free number
(0087-0092). These tests assert the CORRECT (post-fix) invariant — ADR numbers
are unique across ``docs/adr/*.md``.

Surfaced during PR #9405 (ADR-drift citation right-sizing).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from adr_index import scan_adr_directory

_ADR_DIR = Path(__file__).resolve().parents[2] / "docs" / "adr"


def test_adr_numbers_are_unique_across_files() -> None:
    adrs = scan_adr_directory(_ADR_DIR)

    counts = Counter(a.number for a in adrs)
    duplicates = {number: count for number, count in counts.items() if count > 1}

    assert duplicates == {}, (
        "Duplicate ADR numbers parsed from docs/adr/ — each number must map to "
        f"exactly one ADR file. Collisions (number -> file count): {duplicates}"
    )


def test_no_two_adr_files_claim_the_same_number_in_their_title() -> None:
    title_numbers: dict[int, list[str]] = {}
    for adr in scan_adr_directory(_ADR_DIR):
        title_numbers.setdefault(adr.number, []).append(adr.title)

    colliding = {
        number: titles for number, titles in title_numbers.items() if len(titles) > 1
    }

    assert colliding == {}, (
        "Two different ADRs share one number, making adr.title ambiguous and "
        f"merging their citations under a single index entry: {colliding}"
    )
