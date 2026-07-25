"""Regression pins for issue #10458 — nudge bare shared-infra citations to :Symbol.

A bare citation of a high-churn shared-infra module (``src/config.py`` et al.)
is *silently suppressed* from ADR drift detection: it is read as a dependency
pointer, not a decision anchor (#9397/#9176, churn-derived in #10456). #10458
adds a non-blocking authoring nudge that surfaces those suppressed citations and
suggests re-citing at ``:Symbol`` granularity so an ADR that genuinely owns a
symbol there keeps drifting on real changes.

The load-bearing contract these tests pin:

1. **The nudge surfaces exactly what suppression hides.** Nudge
   (``bare_infra_citation_nudges``) and drift suppression (``compute_drift`` via
   ``_citation_drifts``) both route through the one ``_is_shared_infra``
   predicate. On the SAME ADR corpus, every bare citation that produces no drift
   finding produces a nudge, and every bare citation that DOES drift produces no
   nudge. If a future change reintroduces a second, divergent suppression check,
   the two halves fall out of sync and this fails.

2. **The nudge is a pure authoring aid, never a gate.** It reads ADR citation
   data and returns records; it must not alter ``compute_drift`` output. A
   symbol-qualified owner both keeps drifting AND is left un-nudged.

3. **The cross-reference report always carries the section.** Its presence must
   not depend on whether any ADR currently qualifies (renders ``None.`` empty).
"""

from __future__ import annotations

from pathlib import Path

from adr_drift import bare_infra_citation_nudges, compute_drift
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
    _write_adr(adr_dir, number=2, related_files=[_ORDINARY])  # bare -> drifts
    _write_adr(
        adr_dir, number=3, related_files=[f"{_SHARED_INFRA}:HydraFlowConfig"]
    )  # symbol owner -> drifts on its symbol, not nudged
    return ADRIndex(adr_dir)


def test_nudge_surfaces_exactly_what_shared_infra_suppression_hides(
    tmp_path: Path,
) -> None:
    idx = _corpus(tmp_path)
    adrs = idx.adrs()

    nudged = {(n.adr_number, n.path) for n in bare_infra_citation_nudges(adrs)}

    # The bare shared-infra citation drifts nowhere (suppressed) ...
    assert compute_drift(idx, pr_number=1, changed_files=[_SHARED_INFRA]) == []
    # ... and that is exactly the (ADR, path) pair the nudge surfaces.
    assert (1, _SHARED_INFRA) in nudged

    # The ordinary bare citation DOES drift, so it is NOT nudged.
    ordinary = compute_drift(idx, pr_number=2, changed_files=[_ORDINARY])
    assert [f.adr.number for f in ordinary] == [2]
    assert (2, _ORDINARY) not in nudged


def test_symbol_owner_still_drifts_and_is_not_nudged(tmp_path: Path) -> None:
    idx = _corpus(tmp_path)
    # ADR-3 owns HydraFlowConfig in the shared-infra module: a symbol-level
    # change drifts it, proving the :Symbol re-cite the nudge recommends works.
    findings = compute_drift(
        idx, pr_number=3, changed_files=[f"{_SHARED_INFRA}:HydraFlowConfig"]
    )
    assert [f.adr.number for f in findings] == [3]
    # It already cites at symbol granularity, so nothing to nudge.
    nudged = {n.adr_number for n in bare_infra_citation_nudges(idx.adrs())}
    assert 3 not in nudged


def test_cross_reference_report_always_carries_nudge_section() -> None:
    # Empty corpus still emits the section header (renders "None.").
    md = render_adr_cross_reference(ADRRefIndex(adr_to_modules=[]), [])
    assert "## Symbol-Granularity Nudges" in md
    assert "None." in md.split("## Symbol-Granularity Nudges", 1)[1]
