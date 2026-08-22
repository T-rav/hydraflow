"""Unit tests for `src/adr_drift.py` — the symbol-granularity authoring nudge.

The drift half of this module (`compute_drift`, `compute_drift_by_adr`,
`partition_fleet_drift` and their `DriftFinding` / `AdrRollupEntry` /
`FleetDriftBatch` shapes, plus the `_citation_drifts` / `_bare_citation_fanout`
suppression path) was the pure engine behind `AdrTouchpointAuditorLoop` and was
deleted with it by ADR-0136; its tests went with it. What survives is the
`#10458` authoring nudge and the shared-infra allowlist it reads — see
`tests/test_adr_citation_conformance.py` for the deterministic gate that
replaced drift detection.
"""

from __future__ import annotations

import pytest

from adr_drift import (
    CitationNudge,
    _is_shared_infra,
    bare_infra_citation_nudges,
)
from adr_index import ADR


def _adr_with_symbols(
    number: int,
    source_symbols: dict[str, frozenset[str]],
    *,
    status: str = "Accepted",
) -> ADR:
    """Build a minimal ADR carrying only the citation data the nudge reads."""
    return ADR(
        number=number,
        title=f"adr-{number}",
        status=status,
        summary="",
        source_files=frozenset(source_symbols),
        source_symbols=source_symbols,
    )


# --- _is_shared_infra ---------------------------------------------------------


def test_allowlisted_module_is_shared_infra() -> None:
    assert _is_shared_infra("src/config.py")


def test_ordinary_module_is_not_shared_infra() -> None:
    assert not _is_shared_infra("src/some_feature.py")


# --- bare_infra_citation_nudges ----------------------------------------------


def test_bare_shared_infra_citation_yields_one_nudge() -> None:
    # #10458 — an ADR bare-citing a known shared-infra module gets nudged to
    # re-cite at :Symbol granularity, which is the only form the ADR-0136
    # citation gate can enforce.
    adr = _adr_with_symbols(500, {"src/config.py": frozenset()})
    assert bare_infra_citation_nudges([adr]) == [
        CitationNudge(
            adr_number=500,
            path="src/config.py",
            suggestion="src/config.py:<Symbol>",
        )
    ]


def test_symbol_qualified_shared_infra_citation_yields_no_nudge() -> None:
    # Already enforceable by the citation gate — nothing to nudge.
    adr = _adr_with_symbols(501, {"src/config.py": frozenset({"HydraFlowConfig"})})
    assert bare_infra_citation_nudges([adr]) == []


def test_bare_non_shared_infra_citation_yields_no_nudge() -> None:
    # The nudge targets the high-churn dependency-pointer modules only; an
    # ordinary module's bare citation is left alone.
    adr = _adr_with_symbols(502, {"src/some_feature.py": frozenset()})
    assert bare_infra_citation_nudges([adr]) == []


def test_non_src_bare_citation_yields_no_nudge() -> None:
    # The shared-infra rule is scoped to src/ modules; a docs/ citation is out
    # of scope even if bare.
    adr = _adr_with_symbols(503, {"docs/whatever.md": frozenset()})
    assert bare_infra_citation_nudges([adr]) == []


@pytest.mark.parametrize("status", ["Superseded", "Deprecated", "Unknown"])
def test_non_live_adr_bare_citation_yields_no_nudge(status: str) -> None:
    # #10565 — a non-live ADR's citations are frozen history the citation gate
    # deliberately does not enforce, so nudging its author is noise.
    adr = _adr_with_symbols(504, {"src/config.py": frozenset()}, status=status)
    assert bare_infra_citation_nudges([adr]) == []


def test_nudges_sorted_by_adr_number_then_path() -> None:
    adrs = [
        _adr_with_symbols(
            700, {"src/pr_manager.py": frozenset(), "src/config.py": frozenset()}
        ),
        _adr_with_symbols(699, {"src/models.py": frozenset()}),
    ]
    result = [(n.adr_number, n.path) for n in bare_infra_citation_nudges(adrs)]
    assert result == [
        (699, "src/models.py"),
        (700, "src/config.py"),
        (700, "src/pr_manager.py"),
    ]


def test_empty_input_yields_empty_nudge_list() -> None:
    assert bare_infra_citation_nudges([]) == []


def test_nudge_fires_on_exactly_the_shared_infra_bare_citations() -> None:
    """Single-source-of-truth invariant (#10458), re-anchored for ADR-0136.

    The nudge fires on exactly the bare ``src/`` citations of live ADRs that
    :func:`_is_shared_infra` accepts — no second, divergent predicate.
    """
    adrs = [
        _adr_with_symbols(800, {"src/config.py": frozenset()}),  # bare allowlist
        _adr_with_symbols(801, {"src/lonely.py": frozenset()}),  # bare ordinary
        _adr_with_symbols(802, {"src/config.py": frozenset({"HydraFlowConfig"})}),
        _adr_with_symbols(803, {"docs/adr/README.md": frozenset()}),  # non-src
        _adr_with_symbols(
            820, {"src/config.py": frozenset()}, status="Superseded"
        ),  # non-live
    ]

    nudged = {(n.adr_number, n.path) for n in bare_infra_citation_nudges(adrs)}

    expected = {
        (adr.number, path)
        for adr in adrs
        if adr.is_live
        for path, cited in adr.source_symbols.items()
        if not cited and path.startswith("src/") and _is_shared_infra(path)
    }
    assert nudged == expected
    # Sanity: the invariant is non-trivial — it actually caught a pair.
    assert nudged == {(800, "src/config.py")}
