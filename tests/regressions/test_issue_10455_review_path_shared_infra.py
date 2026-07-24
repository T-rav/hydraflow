"""Regression for issue #10455 (epic child of #10454).

The review-path + base-loop modules ``src/review_advisor.py``,
``src/review_phase/_phase.py`` and ``src/base_background_loop.py`` are
high-churn dependency-pointer citations: many ADRs bare-cite them as "the
review pipeline / base loop lives here", not "this exact decision *is* this
file". Ordinary implementation churn in them therefore fired a batch of
ADR-drift false positives (~15 FPs across #10388 / #10405 / #10406, plus the
``base_background_loop`` FP class consolidated in #10441 / #10443).

Fix (the tactical layer of epic #10454): add the three modules to
``adr_drift._SHARED_INFRA_MODULES`` so a *bare* citation is read as a
dependency mention and does NOT drift — while an ADR that genuinely owns a
symbol in one of them still drifts by citing it at ``:Symbol`` granularity.

This test pins both halves the way production does: it drives the real
``adr_index.parse_adr_file`` + ``adr_drift.compute_drift`` over fixture ADRs.

  * A bare citation + a file-level (symbol-less) diff — the production case —
    does NOT drift (the fix).
  * A ``:Symbol`` citation + a diff that supplies that symbol still DOES
    drift (the exemption is bare-only, not a blanket mute).

The systemic churn-derived replacement for this hand-maintained allowlist is
tracked in epic #10454 (child #10456) and is intentionally NOT built here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adr_drift import _SHARED_INFRA_MODULES, _citation_drifts, compute_drift
from adr_index import ADRIndex, parse_adr_file

# The three modules this child adds, each with a representative owning symbol
# used to prove the :Symbol-cited case still drifts.
_REVIEW_PATH_SHARED_INFRA = {
    "src/review_advisor.py": "ReviewAdvisor",
    "src/review_phase/_phase.py": "ReviewPhase",
    "src/base_background_loop.py": "BaseBackgroundLoop",
}


def _write_adr(adr_dir: Path, *, number: int, related: str) -> Path:
    """Write a minimal Accepted ADR whose Related block cites ``related``."""
    path = adr_dir / f"{number:04d}-fixture.md"
    path.write_text(
        f"# ADR-{number:04d}: fixture\n\n"
        f"- **Status:** Accepted\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** `{related}`\n\n"
        f"## Context\n\nFixture body.\n"
    )
    return path


@pytest.mark.parametrize("module", sorted(_REVIEW_PATH_SHARED_INFRA))
def test_review_path_modules_are_shared_infra(module: str) -> None:
    """Membership pin: each module is exempt from bare-citation drift."""
    assert module in _SHARED_INFRA_MODULES


@pytest.mark.parametrize("module", sorted(_REVIEW_PATH_SHARED_INFRA))
def test_bare_cite_of_review_path_module_does_not_drift(
    tmp_path: Path, module: str
) -> None:
    """An implementation-only (file-level, symbol-less) touch does NOT drift.

    This is the production case that fired the #10388 / #10405 / #10406 and
    #10441 / #10443 false positives: a merged PR touches the module, no ADR
    markdown changes, and the bare citation used to flag every citing ADR.
    """
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_adr(adr_dir, number=1234, related=module)
    index = ADRIndex(adr_dir)

    # Bare path == the file-level diff production supplies (no :Symbol tail).
    findings = compute_drift(index, pr_number=10455, changed_files=[module])

    assert findings == [], (
        f"bare citation of shared-infra {module} must not drift, "
        f"got {[(f.adr.number, f.changed_cited_files) for f in findings]}"
    )


@pytest.mark.parametrize("module", sorted(_REVIEW_PATH_SHARED_INFRA))
def test_symbol_cite_of_review_path_module_still_drifts(
    tmp_path: Path, module: str
) -> None:
    """The exemption is bare-only: a ``:Symbol`` citation still drifts.

    An ADR that genuinely OWNS a symbol in one of these modules keeps its
    drift signal by citing it at ``src/foo.py:Symbol`` granularity and
    supplying matching symbol evidence in the diff.
    """
    symbol = _REVIEW_PATH_SHARED_INFRA[module]
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    adr_path = _write_adr(adr_dir, number=1234, related=f"{module}:{symbol}")

    # Sanity: the real parser recorded the symbol-qualified citation.
    adr = parse_adr_file(adr_path)
    assert symbol in adr.source_symbols.get(module, frozenset())

    # A file-only diff (no symbol evidence) must NOT drift a :Symbol cite...
    assert not _citation_drifts(adr, module, frozenset())

    # ...but a diff that reports the owned symbol changed DOES drift it.
    index = ADRIndex(adr_dir)
    findings = compute_drift(
        index, pr_number=10455, changed_files=[f"{module}:{symbol}"]
    )
    drifted = {f for find in findings for f in find.changed_cited_files}
    assert module in drifted, (
        f"symbol-qualified citation {module}:{symbol} must still drift on a "
        f"matching symbol change (exemption is bare-only)"
    )
