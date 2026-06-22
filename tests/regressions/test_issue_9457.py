"""Regression test for issue #9457.

Bug: ``adr_index.scan_adr_directory`` parses every ``docs/adr/*.md`` and
returns a ``list[ADR]`` with *no* detection of duplicate ``.number`` values.
Downstream dict-keyed callers (``adrs_touching``, ``compute_drift``, the
``adr_xref`` generator) then silently keep/merge one of the duplicates.

The #9406 ADR-number collisions went unnoticed for weeks precisely because
nothing on the *runtime* path emits a signal when two ADRs share a number —
they only surfaced via an offline guard test
(``tests/regressions/test_issue_9406.py``).

The fix asked for: have ``scan_adr_directory`` (or ``ADRIndex.adrs``) emit a
``logger.warning`` when it observes two parsed ADRs with the same number, so
future accidental duplicates show up in logs / Sentry immediately.

These tests assert the CORRECT (post-fix) invariant — scanning a directory
containing a duplicate ADR number emits a WARNING-level log record naming the
colliding number. They are RED today because the module emits no signal at all.
"""

from __future__ import annotations

import logging
from pathlib import Path

from adr_index import ADRIndex, scan_adr_directory


def _write_adr(adr_dir: Path, number: int, slug: str, title: str) -> Path:
    """Write a minimal-but-valid ADR file. ``slug`` keeps filenames distinct
    so two files can legitimately claim the same ADR ``number`` in their title.
    """
    p = adr_dir / f"{number:04d}-{slug}.md"
    p.write_text(
        f"# ADR-{number:04d}: {title}\n\n"
        f"**Status:** Accepted\n"
        f"**Date:** 2026-01-01\n\n"
        f"## Context\n\n{title} context.\n"
    )
    return p


def test_scan_adr_directory_warns_on_duplicate_number(tmp_path, caplog) -> None:
    # Two distinct files both claim ADR-0099 in their title.
    _write_adr(tmp_path, 99, "first-decision", "First Decision")
    _write_adr(tmp_path, 99, "second-decision", "Second Decision")
    _write_adr(tmp_path, 7, "unrelated", "Unrelated Decision")

    with caplog.at_level(logging.WARNING):
        adrs = scan_adr_directory(tmp_path)

    # The duplicate is parsed into two ADR objects (the collision is real)...
    assert sum(1 for a in adrs if a.number == 99) == 2

    # ...and the runtime path MUST emit a WARNING naming the colliding number.
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, (
        "scan_adr_directory observed two ADRs sharing number 0099 but emitted "
        "no WARNING — duplicate ADR numbers stay invisible at runtime (the "
        "#9406 collisions went unnoticed for weeks for exactly this reason)."
    )
    assert any("99" in r.getMessage() for r in warnings), (
        "Expected a WARNING log mentioning the duplicated ADR number 99; got: "
        f"{[r.getMessage() for r in warnings]}"
    )


def test_adr_index_warns_on_duplicate_number(tmp_path, caplog) -> None:
    _write_adr(tmp_path, 42, "alpha", "Alpha")
    _write_adr(tmp_path, 42, "beta", "Beta")

    index = ADRIndex(tmp_path)
    with caplog.at_level(logging.WARNING):
        index.adrs()

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("42" in r.getMessage() for r in warnings), (
        "ADRIndex.adrs() loaded two ADRs sharing number 0042 without emitting a "
        f"WARNING; got: {[r.getMessage() for r in warnings]}"
    )
