"""Regression test for #10565.

``bare_infra_citation_nudges`` (src/adr_drift.py) had no ADR-status filter,
while the drift-suppression path it claims to exactly mirror
(``compute_drift`` via ``ADRIndex.adrs_touching``) restricts everything to
live (Accepted/Proposed) ADRs — non-live ADRs never enter the suppression
computation at all. That broke the PR's own stated single-source-of-truth
invariant ("the nudge fires on exactly the bare citations suppression
covers") and was directly observable in the shipped
``docs/arch/generated/adr_xref.md``: it nudged ADR-0013 to re-cite
``src/models.py``/``src/pr_manager.py`` at ``:Symbol`` granularity even
though ADR-0013's own status is ``Superseded`` — drift-suppression never
touches it, so there was nothing for the nudge to be "exactly" mirroring.

The regression/unit test meant to pin this coupling
(``test_nudges_couple_exactly_to_shared_infra_suppression`` in
``tests/test_adr_drift.py``) only built fixture ADRs via a helper that
hardcoded ``status="Accepted"``, so it never exercised the status-mismatch
case and passed despite the bug shipping. This test drives the real ADR
corpus through ``bare_infra_citation_nudges`` the same way
``arch.runner``/``adr_cross_reference`` do in production
(``scan_adr_directory`` returns every status, unfiltered).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adr_drift import bare_infra_citation_nudges
from adr_index import scan_adr_directory

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADR_DIR = _REPO_ROOT / "docs" / "adr"


def test_adr_0013_superseded_is_never_nudged() -> None:
    # Self-retiring per #11195: skip (never explode) once ADR-0013 is
    # renumbered or removed — see tests/regressions/test_issue_11195.py.
    adrs = scan_adr_directory(_ADR_DIR)
    adr_0013 = next((a for a in adrs if a.number == 13), None)
    if adr_0013 is None:
        pytest.skip("ADR-0013 not present in this corpus; pin self-retires")
    assert adr_0013.status == "Superseded", (
        "this test pins the exact shipped false positive against ADR-0013 — "
        "if its status changed, update the fixture ADR used here instead"
    )

    nudged_numbers = {n.adr_number for n in bare_infra_citation_nudges(adrs)}
    assert 13 not in nudged_numbers


def test_no_non_live_adr_ever_appears_in_nudges() -> None:
    adrs = scan_adr_directory(_ADR_DIR)
    non_live = {a.number for a in adrs if not a.is_live}
    assert non_live, "expected at least one non-live ADR in the real corpus"

    nudged_numbers = {n.adr_number for n in bare_infra_citation_nudges(adrs)}
    leaked = nudged_numbers & non_live
    assert not leaked, f"non-live ADRs {sorted(leaked)} were nudged"
