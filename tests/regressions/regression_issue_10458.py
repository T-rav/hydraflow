"""Regression pins for issue #10458 — nudge bare shared-infra citations to :Symbol.

A bare citation of a high-churn shared-infra module (``src/config.py`` et al.)
is a *dependency pointer*, not a decision anchor (#9397/#9176). #10458 added a
non-blocking authoring nudge that surfaces those citations and suggests
re-citing at ``:Symbol`` granularity.

**Re-anchored for ADR-0136.** The nudge originally mirrored ADR-drift
*suppression*: it fired on exactly the bare citations ``compute_drift``
declined to flag. That drift engine was deleted with
``AdrTouchpointAuditorLoop``, and the nudge's meaning moved one step over
without changing its output: a bare citation is the form the deterministic
citation gate (`tests/test_adr_citation_conformance.py`) **cannot enforce**, so
the nudge is now the on-ramp from an unenforceable citation to an enforceable
one. The load-bearing contract these tests pin:

1. **The nudge surfaces exactly the unenforceable bare shared-infra citations.**
   One predicate (``_is_shared_infra``) decides; a symbol-qualified owner — the
   citation the gate DOES enforce — is left un-nudged.

2. **The nudge is a pure authoring aid, never a gate.** It reads ADR citation
   data and returns records; nothing it emits changes what CI enforces.

3. **The cross-reference report always carries the section.** Its presence must
   not depend on whether any ADR currently qualifies (renders ``None.`` empty).
"""

from __future__ import annotations

from pathlib import Path

from adr_citation_resolve import unresolved_citations
from adr_drift import bare_infra_citation_nudges
from adr_index import ADRIndex
from arch._models import ADRRefIndex
from arch.generators.adr_cross_reference import render_adr_cross_reference

# A module on the manual shared-infra allowlist and an ordinary module.
_SHARED_INFRA = "src/config.py"
_ORDINARY = "src/some_ordinary_feature.py"


def _write_adr(adr_dir: Path, *, number: int, related_files: list[str]) -> None:
    related = ", ".join(f"`{f}`" for f in related_files)
    (adr_dir / f"{number:04d}-fixture.md").write_text(
        f"# ADR-{number:04d}: fixture {number}\n\n"
        f"- **Status:** Accepted\n"
        f"- **Related:** {related}\n\n"
        f"## Context\n\nFixture body.\n"
    )


def _corpus(tmp_path: Path) -> ADRIndex:
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(adr_dir, number=1, related_files=[_SHARED_INFRA])  # bare -> nudged
    _write_adr(adr_dir, number=2, related_files=[_ORDINARY])  # bare, not infra
    _write_adr(
        adr_dir, number=3, related_files=[f"{_SHARED_INFRA}:HydraFlowConfig"]
    )  # symbol owner -> enforced by the gate, not nudged
    return ADRIndex(adr_dir)


def test_nudge_surfaces_exactly_the_unenforceable_shared_infra_citations(
    tmp_path: Path,
) -> None:
    idx = _corpus(tmp_path)

    nudged = {(n.adr_number, n.path) for n in bare_infra_citation_nudges(idx.adrs())}

    # The bare shared-infra citation is the one that gets the nudge ...
    assert (1, _SHARED_INFRA) in nudged
    # ... and it is the ONLY one: an ordinary bare citation is not a
    # dependency-pointer module, and the symbol owner is already enforceable.
    assert nudged == {(1, _SHARED_INFRA)}


def test_symbol_owner_is_enforced_by_the_gate_and_not_nudged(tmp_path: Path) -> None:
    """ADR-3 owns ``HydraFlowConfig``: the citation the gate holds it to.

    Proves the ``:Symbol`` re-cite the nudge recommends actually buys
    enforcement — the resolver reports no violation while the symbol exists,
    and the ADR is not nudged because there is nothing left to upgrade.
    """
    idx = _corpus(tmp_path)
    repo_root = Path(__file__).resolve().parents[2]

    # The cited symbol resolves against the real tree -> no violation.
    violations = unresolved_citations(idx, repo_root=repo_root)
    assert (3, _SHARED_INFRA, "HydraFlowConfig") not in violations

    assert 3 not in {n.adr_number for n in bare_infra_citation_nudges(idx.adrs())}


def test_cross_reference_report_always_carries_nudge_section() -> None:
    # Empty corpus still emits the section header (renders "None.").
    md = render_adr_cross_reference(ADRRefIndex(adr_to_modules=[]), [])
    assert "## Symbol-Granularity Nudges" in md
    assert "None." in md.split("## Symbol-Granularity Nudges", 1)[1]
