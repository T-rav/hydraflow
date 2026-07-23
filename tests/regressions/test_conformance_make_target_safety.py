"""Regression: ADR-conformance make-target safety (beads advisor-xz82/w6zf).

xz82 — the MUTATING_MAKE_TARGETS denylist failed OPEN: a make target not on
the list was treated as side-effect-free and could be cited as an `enforced`
check, then executed by the loop. is_mutating now also scans the target's
Makefile recipe for high-confidence mutation commands, so an unlisted target
that pushes/commits/opens PRs is caught.

w6zf — make-target renames are intentionally NOT auto-repointed: a make
target's identity is its name (no content signal to match), so a guessed
REPOINT would be unsafe. classify_remediation routes an UNRESOLVED make
check (no rename match) to FILE_ISSUE, never REPOINT.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from adr_conformance import (
    AdrConformance,
    CheckOutcome,
    ConformanceKind,
    is_mutating,
)
from adr_conformance_remediation import RemediationAction, classify_remediation
from adr_index import Check


def test_unlisted_mutating_make_target_is_caught_by_recipe_scan(tmp_path: Path):
    (tmp_path / "Makefile").write_text(
        "release:\n\t@echo cutting release\n\tgh pr create --fill\n\tgit push --tags\n"
    )
    check = Check("make", "release", "make:release")
    # Not on the denylist, so denylist-only misses it...
    assert is_mutating(check) is False
    # ...but the recipe scan (with repo_root, as the ratchet passes) catches it.
    assert is_mutating(check, tmp_path) is True


def _unresolved_make_conf():
    # Minimal conformance object with the .outcome classify_remediation reads.
    return AdrConformance(
        adr_id="ADR-0099",
        kind=ConformanceKind.ENFORCED,
        outcome=CheckOutcome.UNRESOLVED,
        checks=[],
        timestamp=datetime(2026, 7, 4, tzinfo=UTC),
    )


def test_unresolved_make_target_never_repoints():
    # rename_match is None for make targets (the loop's _detect_rename only
    # inspects pytest checks) -> must route to FILE_ISSUE, never REPOINT.
    decision = classify_remediation(
        _unresolved_make_conf(), rename_match=None, attempts=0
    )
    assert decision.action is RemediationAction.FILE_ISSUE
    assert decision.action is not RemediationAction.REPOINT
