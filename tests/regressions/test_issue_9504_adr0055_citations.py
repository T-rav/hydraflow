"""Regression test for issue #9504's surviving risk: ADR-0055 bare citations.

Background:
    PR #9684 widened ``adr_index``'s parser to tolerate em-dash titles and
    ``## Status`` section-format status, which made previously-invisible
    ADRs — including ADR-0055 (section-format status) — live to the drift
    auditor (``adr_touchpoint_auditor_loop`` / ``adr_drift``) for the first
    time. ADR-0055 bare-cited ``src/base_runner.py``, ``src/events.py``, and
    ``src/workspace.py`` — high-churn files not in
    ``adr_drift._SHARED_INFRA_MODULES`` (unlike ``src/server.py``, which
    already has that exemption). Left bare, any unrelated touch of those
    files in a merged PR would drift ADR-0055 and risk re-introducing the
    #9176-class stuck-HITL drift escalations.

Fix:
    Symbol-qualify the three citations to the specific class each one
    actually decorates/modifies (mirrors the #9176 / #9419-9421
    right-sizing): ``src/base_runner.py:BaseRunner``,
    ``src/events.py:EventBus``, ``src/workspace.py:WorkspaceManager``.

These tests drive the real ``docs/adr`` directory and the production drift
logic — no stubs — so a green result genuinely means the drift no longer
reproduces.
"""

from __future__ import annotations

from pathlib import Path

from adr_drift import _SHARED_INFRA_MODULES, _citation_drifts, compute_drift
from adr_index import ADRIndex, parse_adr_file

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADR_DIR = _REPO_ROOT / "docs" / "adr"
_ADR_0055_PATH = _ADR_DIR / "0055-otel-honeycomb-instrumentation.md"

_RISK_FILES = ("src/base_runner.py", "src/events.py", "src/workspace.py")


def _adr_0055():
    index = ADRIndex(_ADR_DIR)
    return next(a for a in index.adrs() if a.number == 55)


def test_adr_0055_parses_as_accepted():
    """Sanity: the section-format ``## Status`` block parses (PR #9684)."""
    adr = parse_adr_file(_ADR_0055_PATH)
    assert adr.status == "Accepted"


def test_risk_files_are_symbol_qualified_not_shared_infra():
    """The three files are genuinely bare-cite risks: not shared-infra-exempt."""
    for path in _RISK_FILES:
        assert path not in _SHARED_INFRA_MODULES, (
            f"{path} is in _SHARED_INFRA_MODULES — the citation-qualification "
            f"fix on ADR-0055 would be unnecessary if so"
        )


def test_adr_0055_citations_are_symbol_qualified():
    adr = _adr_0055()
    for path in _RISK_FILES:
        symbols = adr.source_symbols.get(path, frozenset())
        assert symbols, (
            f"ADR-0055 still bare-cites {path} — must be symbol-qualified "
            f"(mirrors #9176 / #9419-9421 right-sizing)"
        )


def test_adr_0055_does_not_drift_on_file_level_churn_of_risk_files():
    """Worst case: a PR touches all three risk files without touching ADR-0055."""
    index = ADRIndex(_ADR_DIR)
    findings = compute_drift(index, pr_number=9504, changed_files=list(_RISK_FILES))
    own = [f for f in findings if f.adr.number == 55]
    assert not own, (
        f"ADR-0055 drifted on file-level touch of {_RISK_FILES} — "
        f"the bare-citation risk has regressed"
    )


def test_adr_0055_symbol_cites_are_inert_to_file_only_diff():
    """A bare-path (symbol-less) touch — what production's file-level diff
    supplies — must not drift a symbol-qualified citation (the #9176 design)."""
    adr = _adr_0055()
    for path in _RISK_FILES:
        assert not _citation_drifts(adr, path, frozenset()), (
            f"ADR-0055 citation {path} drifts on a file-only diff despite "
            f"being symbol-qualified"
        )
