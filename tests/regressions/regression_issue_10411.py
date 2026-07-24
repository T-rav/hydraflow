"""Regression test for #10411 — review_advisor/_phase shared-infra allowlist gap.

``src/review_advisor.py`` and ``src/review_phase/_phase.py`` are high-churn
review-pipeline files bare-cited (no ``:Symbol`` tail) by 5 of the 11 ADRs
that reference them at all (ADR-0059/0094/0095/0102/0103) — the other 6
(0012/0014/0015/0031/0063/0099) already cite a ``:Symbol`` on these files and
were never affected. Because these two files were missing from
``_SHARED_INFRA_MODULES``, every PR touching the review path drifted a batch
of those 5 ADRs (the false-positive shape behind #10388/#10405/#10406).

This mirrors the existing ``test_recurring_fp_module_bare_citation_does_not_drift``
/ ``test_real_adrs_do_not_drift_on_dependency_only_touches`` guards in
``tests/test_adr_drift.py`` for the modules added in earlier rounds
(config/pr_manager/dashboard/server/repo_runtime/contract_*).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adr_drift import _SHARED_INFRA_MODULES, compute_drift
from adr_index import ADRIndex

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADR_DIR = _REPO_ROOT / "docs" / "adr"

# The 5 ADRs with an actual bare (unqualified) citation of one of these files
# — the ones that were false-firing before this fix.
_BARE_CITING_ADRS = {59, 94, 95, 102, 103}


@pytest.mark.parametrize(
    "module", ["src/review_advisor.py", "src/review_phase/_phase.py"]
)
def test_review_pipeline_module_is_shared_infra(module: str) -> None:
    assert module in _SHARED_INFRA_MODULES


@pytest.mark.parametrize(
    "module", ["src/review_advisor.py", "src/review_phase/_phase.py"]
)
def test_bare_citation_of_review_pipeline_module_does_not_drift(
    tmp_path: Path, module: str
) -> None:
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    body = (
        "# ADR-0900: depends on review pipeline\n\n"
        "- **Status:** Accepted\n"
        "- **Date:** 2026-01-01\n"
        f"- **Related:** `{module}`\n\n"
        "## Context\n\nFixture body.\n"
    )
    (adr_dir / "0900-depends-on-review-pipeline.md").write_text(body)

    findings = compute_drift(
        ADRIndex(adr_dir), pr_number=1, changed_files=[module]
    )
    assert findings == []


def test_real_bare_citing_adrs_do_not_drift_on_review_pipeline_touch() -> None:
    """End-to-end: the actual ADRs affected by #10411 no longer drift.

    Production passes bare file-level diffs (no :Symbol evidence). Touching
    both review-pipeline files without editing any ADR markdown must not
    drift ADR-0059/0094/0095/0102/0103.
    """
    idx = ADRIndex(_ADR_DIR)
    touches = ["src/review_advisor.py", "src/review_phase/_phase.py"]
    findings = compute_drift(idx, pr_number=9999, changed_files=touches)
    drifted = sorted({f.adr.number for f in findings} & _BARE_CITING_ADRS)
    assert drifted == [], (
        f"dependency-only touches of {touches} drifted ADRs {drifted}; "
        "review_advisor.py / review_phase/_phase.py must be shared-infra"
    )
