"""Regression for issue #10456 (epic child of #10454).

Churn-derived auto-suppression of bare-cited shared-infra modules. The manual
``adr_drift._SHARED_INFRA_MODULES`` allowlist grew by whack-a-mole: every time
a new high-churn module became the dominant ADR-drift false-positive source
(#9397, the dashboard cluster, the contract subsystem, the review path in
#10455) someone hand-edited the frozenset. #10456 derives the same suppression
from citation *fan-out*: a ``src/`` module bare-cited by at least
``config.adr_drift_shared_infra_fanout_threshold`` live (Accepted/Proposed)
ADRs is auto-treated as shared infra with no allowlist edit.

This test pins the systemic behaviour end-to-end over the real
``adr_index.ADRIndex`` + ``adr_drift.compute_drift`` on a module that is
deliberately NOT in ``_SHARED_INFRA_MODULES`` — so any suppression proves the
derived path, not the hand-maintained list:

  * A module bare-cited by >= threshold live ADRs does NOT drift (the fix).
  * Below the threshold, genuine drift STILL fires (no silent masking).
  * A ``:Symbol``-owning ADR still drifts on its symbol regardless of how many
    OTHER ADRs bare-cite the same high-fan-out file (suppression is bare-only).
  * With the derived path disabled (threshold=None, the default) behaviour is
    byte-identical to before — the high-fan-out bare citations all drift.
"""

from __future__ import annotations

from pathlib import Path

from adr_drift import _SHARED_INFRA_MODULES, compute_drift
from adr_index import ADRIndex

# A high-churn dependency-pointer module that is intentionally absent from the
# manual allowlist, so suppression here can only come from citation fan-out.
_HOT_MODULE = "src/churn_hot_module.py"
_THRESHOLD = 4


def _write_bare_citing_adrs(adr_dir: Path, *, count: int, module: str) -> None:
    """Write *count* Accepted ADRs that each bare-cite *module*."""
    for i in range(count):
        number = 700 + i
        (adr_dir / f"{number:04d}-fixture.md").write_text(
            f"# ADR-{number:04d}: fixture {i}\n\n"
            f"- **Status:** Accepted\n"
            f"- **Date:** 2026-01-01\n"
            f"- **Related:** `{module}`\n\n"
            f"## Context\n\nFixture body.\n"
        )


def test_hot_module_not_in_manual_allowlist() -> None:
    """Guard: the module must NOT be hand-listed, or the test proves nothing."""
    assert _HOT_MODULE not in _SHARED_INFRA_MODULES


def test_high_fanout_bare_citation_auto_suppressed(tmp_path: Path) -> None:
    """A module bare-cited by >= threshold live ADRs drifts nothing (the fix)."""
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_bare_citing_adrs(adr_dir, count=_THRESHOLD, module=_HOT_MODULE)

    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=10456,
        changed_files=[_HOT_MODULE],
        shared_infra_fanout_threshold=_THRESHOLD,
    )
    assert findings == [], (
        f"{_HOT_MODULE} bare-cited by {_THRESHOLD} live ADRs must be "
        f"churn-suppressed, got {[f.adr.number for f in findings]}"
    )


def test_below_threshold_bare_citation_still_drifts(tmp_path: Path) -> None:
    """Below the fan-out threshold, genuine drift is NOT masked."""
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_bare_citing_adrs(adr_dir, count=_THRESHOLD - 1, module=_HOT_MODULE)

    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=10456,
        changed_files=[_HOT_MODULE],
        shared_infra_fanout_threshold=_THRESHOLD,
    )
    assert sorted(f.adr.number for f in findings) == [700, 701, 702]


def test_symbol_owner_still_drifts_amid_high_fanout(tmp_path: Path) -> None:
    """A symbol-owning ADR still drifts even when the file is high-fan-out."""
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_bare_citing_adrs(adr_dir, count=_THRESHOLD, module=_HOT_MODULE)
    (adr_dir / "0799-owner.md").write_text(
        "# ADR-0799: owns a symbol\n\n"
        "- **Status:** Accepted\n"
        "- **Date:** 2026-01-01\n"
        f"- **Related:** `{_HOT_MODULE}:Owner`\n\n"
        "## Context\n\nFixture body.\n"
    )

    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=10456,
        changed_files=[f"{_HOT_MODULE}:Owner"],
        shared_infra_fanout_threshold=_THRESHOLD,
    )
    assert [f.adr.number for f in findings] == [799]


def test_no_threshold_preserves_prior_behaviour(tmp_path: Path) -> None:
    """Default (threshold=None): high-fan-out bare citations drift as before."""
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_bare_citing_adrs(adr_dir, count=_THRESHOLD, module=_HOT_MODULE)

    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=10456,
        changed_files=[_HOT_MODULE],
    )
    assert sorted(f.adr.number for f in findings) == [700, 701, 702, 703]
