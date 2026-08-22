"""Regression for issue #10455 (epic child of #10454).

The review-path + base-loop modules ``src/review_advisor.py``,
``src/review_phase/_phase.py`` and ``src/base_background_loop.py`` are
high-churn dependency-pointer citations: many ADRs bare-cite them as "the
review pipeline / base loop lives here", not "this exact decision *is* this
file". Ordinary implementation churn in them fired a batch of ADR-drift false
positives (~15 FPs across #10388 / #10405 / #10406, plus the
``base_background_loop`` FP class consolidated in #10441 / #10443).

The original fix added the three modules to ``adr_drift._SHARED_INFRA_MODULES``
so a *bare* citation was read as a dependency mention and did not drift.

**Re-anchored for ADR-0136.** The drift half these pins asserted against
(``compute_drift`` / ``_citation_drifts``) was deleted with
``AdrTouchpointAuditorLoop``, so there is no longer any drift for the
allowlist to suppress — the false-positive class this issue reported cannot
recur at all. The allowlist itself survives as the input to the
``#10458`` authoring nudge, which now carries the same three modules'
meaning forward: a bare citation of one of them is *unenforceable* by the
ADR-0136 citation gate and is surfaced for re-citing at ``:Symbol``
granularity, while an ADR that genuinely owns a symbol there is left alone.
These pins assert exactly that, over the real ``adr_index.parse_adr_file``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adr_drift import _SHARED_INFRA_MODULES, bare_infra_citation_nudges
from adr_index import parse_adr_file

# The three modules this child adds, each with a representative owning symbol
# used to prove the :Symbol-cited case is left alone.
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
    """Membership pin: each module is still read as a dependency pointer."""
    assert module in _SHARED_INFRA_MODULES


@pytest.mark.parametrize("module", sorted(_REVIEW_PATH_SHARED_INFRA))
def test_bare_cite_of_review_path_module_is_nudged(tmp_path: Path, module: str) -> None:
    """A bare citation of one of these modules is unenforceable → nudged.

    The successor to the original "does not drift" pin: the same bare
    citation the auditor used to flag on every implementation-only touch is
    now surfaced once, as an authoring suggestion, instead of as N issues.
    """
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    adr = parse_adr_file(_write_adr(adr_dir, number=1234, related=module))

    nudges = bare_infra_citation_nudges([adr])

    assert [(n.adr_number, n.path, n.suggestion) for n in nudges] == [
        (1234, module, f"{module}:<Symbol>")
    ]


@pytest.mark.parametrize("module", sorted(_REVIEW_PATH_SHARED_INFRA))
def test_symbol_cite_of_review_path_module_is_not_nudged(
    tmp_path: Path, module: str
) -> None:
    """The rule is bare-only: a ``:Symbol`` citation is already enforceable.

    An ADR that genuinely OWNS a symbol in one of these modules is held to it
    by the ADR-0136 citation gate, so it has nothing to be nudged about.
    """
    symbol = _REVIEW_PATH_SHARED_INFRA[module]
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    adr = parse_adr_file(
        _write_adr(adr_dir, number=1234, related=f"{module}:{symbol}")
    )

    # Sanity: the real parser recorded the symbol-qualified citation.
    assert symbol in adr.source_symbols.get(module, frozenset())

    assert bare_infra_citation_nudges([adr]) == []
