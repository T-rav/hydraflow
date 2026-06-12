"""Regression test for the ADR-drift right-sizing of 5 stuck-HITL ADRs.

Closes #9417 (ADR-0024) / #9419 (ADR-0045) / #9420 (ADR-0050) /
#9421 (ADR-0064) / #9447 (ADR-0044).

Background — the mechanism in ``src/adr_drift.py`` + ``src/adr_index.py``:
an ADR that *bare*-cites a ``src/foo.py`` (no ``:Symbol`` tail) drifts on
*any* file-level touch of that file in a merged PR that does not also edit
the ADR markdown. A *symbol-qualified* citation (``src/foo.py:Bar``) only
drifts when that symbol changes — and because the production auditor passes
FILE-level diffs (bare paths, no symbol evidence), a symbol-qualified
citation never auto-drifts in prod (the #9176 design). ``_SHARED_INFRA_MODULES``
(config/models/ports/post_merge_handler/pr_manager) are additionally exempt
even when bare.

These 5 ADRs each carried bare, high-churn, non-infra citations that
re-drifted on incidental code churn and produced the stuck-HITL drift
escalations. The right-sizing converted those bare citations to
symbol-qualified form (mirroring PR #9405). This test drives the *real*
``adr_index.parse_adr_file`` + ``adr_drift.compute_drift`` exactly the way
production does — a FILE-LEVEL changed-set (bare paths, no symbol tails) of
each ADR's own cited source files — and asserts the ADR no longer drifts.

The only files that may still drift an ADR under a file-only diff are:

  * genuinely-bare ``_SHARED_INFRA_MODULES`` — exempt, never drift; and
  * a small, deliberately-left-bare set of pure-data / prompt-constant
    modules in ADR-0064 (``adversarial_labels.py``,
    ``plan_council_prompts.py``, ``discovery_council_prompts.py``) which
    are low-churn label/prompt tables with no single public entry symbol.

The test pins both halves: symbol-qualified cited files are inert to
file-only churn (the fix), and the deliberately-bare data modules still
drift by design (so a future blanket-qualify does not silently change
intent).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adr_drift import _SHARED_INFRA_MODULES, _citation_drifts, compute_drift
from adr_index import ADR, ADRIndex, parse_adr_file

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADR_DIR = _REPO_ROOT / "docs" / "adr"

# ADR number -> markdown filename for the 5 right-sized ADRs.
_RIGHT_SIZED = {
    24: "0024-implementation-retry-recovery-architecture.md",
    44: "0044-hydraflow-principles.md",
    45: "0045-trust-architecture-hardening.md",
    50: "0050-auto-agent-hitl-preflight.md",
    64: "0064-earlier-adversarial-pipeline.md",
}

# Deliberately-left-bare, non-infra, low-churn data/prompt modules. A
# file-only touch of these still drifts the citing ADR by design — they
# are pure label/prompt-constant tables with no single public entry symbol
# to qualify against. Pinned so a future blanket-qualify is a conscious
# decision, not an accident.
_DELIBERATELY_BARE = {
    "src/adversarial_labels.py",
    "src/plan_council_prompts.py",
    "src/discovery_council_prompts.py",
}


def _real_source_files(adr: ADR) -> list[str]:
    """The ADR's cited ``src/*.py`` files that name a real on-disk file.

    Drops glob/placeholder citations (``src/*_loop.py``,
    ``src/<domain>/*.py``) that the citation regex picks up from prose —
    no real PR diff path ever equals a glob string, so they cannot drift
    in production.
    """
    return sorted(f for f in adr.source_files if (_REPO_ROOT / f).is_file())


def _single_adr_index(number: int) -> tuple[ADRIndex, ADR]:
    """Build an ADRIndex over the real adr dir and return (index, the ADR)."""
    index = ADRIndex(_ADR_DIR)
    adr = next(a for a in index.adrs() if a.number == number)
    return index, adr


@pytest.mark.parametrize("number", sorted(_RIGHT_SIZED))
def test_right_sized_adr_does_not_drift_on_file_level_churn(number: int) -> None:
    index, adr = _single_adr_index(number)

    real_files = _real_source_files(adr)
    assert real_files, f"ADR-{number:04d} should cite at least one real src file"

    # Production passes bare file paths (file-level diff, no :Symbol tails).
    # A PR that touches every cited file of this ADR, without editing the
    # ADR markdown, is the worst case for a false-positive drift.
    findings = compute_drift(index, pr_number=9999, changed_files=real_files)

    # Only the ADR under test matters — compute_drift returns findings for
    # every ADR that also cites these files (a shared file may be owned by a
    # different, out-of-scope ADR), so filter to this ADR's own drift.
    own = [find for find in findings if find.adr.number == number]
    drifted_files = {f for find in own for f in find.changed_cited_files}
    # Anything that drifts must be a deliberately-bare data/prompt module;
    # nothing symbol-qualified and nothing shared-infra may drift.
    unexpected = drifted_files - _DELIBERATELY_BARE
    assert not unexpected, (
        f"ADR-{number:04d} still drifts on file-level churn of {sorted(unexpected)} "
        f"— these should be symbol-qualified (or shared-infra exempt)"
    )

    # Shared-infra bare cites must never drift (sanity on the exemption).
    for find in own:
        for f in find.changed_cited_files:
            assert f not in _SHARED_INFRA_MODULES


@pytest.mark.parametrize("number", sorted(_RIGHT_SIZED))
def test_right_sized_adr_symbol_cites_are_inert_to_file_only_diff(number: int) -> None:
    """Every symbol-qualified cited file is provably inert to a file-only diff.

    This is the heart of the right-sizing: a bare-path (symbol-less) touch
    of a symbol-qualified citation must NOT drift — the #9176 design that
    stops incidental churn re-firing the escalation.
    """
    _, adr = _single_adr_index(number)
    qualified = {f for f, syms in adr.source_symbols.items() if syms}
    assert qualified, f"ADR-{number:04d} should have ≥1 symbol-qualified citation"

    for path in qualified:
        # Empty changed-symbol set == what production's file-level diff supplies.
        assert not _citation_drifts(adr, path, frozenset()), (
            f"ADR-{number:04d} citation {path} drifts on a file-only diff "
            f"despite being symbol-qualified"
        )


def test_adr_0064_data_modules_still_drift_by_design() -> None:
    """The deliberately-bare data/prompt modules in ADR-0064 still drift.

    Pins the conscious decision to leave these low-churn pure-data modules
    bare: a file-only touch DOES drift ADR-0064. If a future change qualifies
    them, that should be intentional and this guard should be updated.
    """
    index, adr = _single_adr_index(64)
    bare_data = sorted(_DELIBERATELY_BARE & adr.source_files)
    assert bare_data, "expected ADR-0064 to bare-cite its data/prompt modules"

    findings = compute_drift(index, pr_number=9998, changed_files=bare_data)
    own = [find for find in findings if find.adr.number == 64]
    drifted = {f for find in own for f in find.changed_cited_files}
    assert set(bare_data) <= drifted


def test_parse_picks_up_qualified_symbols_for_each_right_sized_adr() -> None:
    """Smoke: the real parser records the symbol tails we wrote into the ADRs."""
    expected_symbol_owner = {
        24: ("src/implement_phase.py", "ImplementPhase"),
        44: ("src/orchestrator.py", "HydraFlowOrchestrator"),
        45: ("src/trust_fleet_sanity_loop.py", "TrustFleetSanityLoop"),
        50: ("src/preflight/auto_agent_runner.py", "AutoAgentRunner"),
        64: ("src/adversarial_retry_loop.py", "AdversarialRetryLoop"),
    }
    for number, (path, symbol) in expected_symbol_owner.items():
        adr = parse_adr_file(_ADR_DIR / _RIGHT_SIZED[number])
        assert symbol in adr.source_symbols.get(path, frozenset()), (
            f"ADR-{number:04d} should symbol-qualify {path}:{symbol}"
        )
