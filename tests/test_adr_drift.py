"""Unit tests for `src/adr_drift.py` (ADR-0056 helper)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adr_drift import (
    AdrRollupEntry,
    DriftFinding,
    _adr_file_in_diff,
    compute_drift,
    compute_drift_by_adr,
)
from adr_index import ADR, ADRIndex


def _write_adr(
    adr_dir: Path,
    *,
    number: int,
    title: str,
    status: str,
    related_files: list[str],
) -> Path:
    """Drop a minimal ADR file with a `Related:` line citing the given files."""
    related = ", ".join(f"`{f}`" for f in related_files)
    body = (
        f"# ADR-{number:04d}: {title}\n\n"
        f"- **Status:** {status}\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** {related}\n\n"
        f"## Context\n\nFixture body.\n"
    )
    path = adr_dir / f"{number:04d}-{title.lower().replace(' ', '-')}.md"
    path.write_text(body)
    return path


@pytest.fixture
def adr_index(tmp_path: Path) -> ADRIndex:
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=1,
        title="alpha",
        status="Accepted",
        related_files=["src/alpha.py"],
    )
    _write_adr(
        adr_dir,
        number=2,
        title="beta",
        status="Accepted",
        related_files=["src/beta.py", "src/shared.py"],
    )
    _write_adr(
        adr_dir,
        number=3,
        title="gamma",
        status="Superseded",
        related_files=["src/gamma.py"],
    )
    return ADRIndex(adr_dir)


def test_no_drift_when_only_non_src_files_changed(adr_index: ADRIndex) -> None:
    findings = compute_drift(adr_index, pr_number=10, changed_files=["docs/x.md"])
    assert findings == []


def test_drift_when_cited_src_changed_without_adr_in_diff(adr_index: ADRIndex) -> None:
    findings = compute_drift(
        adr_index,
        pr_number=42,
        changed_files=["src/alpha.py", "tests/test_alpha.py"],
    )
    assert len(findings) == 1
    f = findings[0]
    assert f.adr.number == 1
    assert f.pr_number == 42
    assert f.changed_cited_files == ("src/alpha.py",)


def test_no_drift_when_adr_file_in_diff(adr_index: ADRIndex) -> None:
    findings = compute_drift(
        adr_index,
        pr_number=42,
        changed_files=["src/alpha.py", "docs/adr/0001-alpha.md"],
    )
    assert findings == []


def test_no_drift_when_adr_renamed_but_number_matches(adr_index: ADRIndex) -> None:
    """ADR-NNNN-* prefix match tolerates slug renames in the same diff."""
    findings = compute_drift(
        adr_index,
        pr_number=42,
        changed_files=["src/alpha.py", "docs/adr/0001-alpha-renamed-slug.md"],
    )
    assert findings == []


def test_one_finding_per_drifted_adr_with_multiple_files(adr_index: ADRIndex) -> None:
    findings = compute_drift(
        adr_index,
        pr_number=99,
        changed_files=["src/beta.py", "src/shared.py"],
    )
    assert len(findings) == 1
    assert findings[0].adr.number == 2
    assert findings[0].changed_cited_files == ("src/beta.py", "src/shared.py")


def test_findings_sorted_by_adr_number(adr_index: ADRIndex) -> None:
    findings = compute_drift(
        adr_index,
        pr_number=99,
        changed_files=["src/beta.py", "src/alpha.py"],
    )
    assert [f.adr.number for f in findings] == [1, 2]


def test_superseded_adr_does_not_drift(adr_index: ADRIndex) -> None:
    findings = compute_drift(
        adr_index,
        pr_number=99,
        changed_files=["src/gamma.py"],
    )
    assert findings == []


def test_bare_citation_of_shared_infra_module_does_not_drift(tmp_path: Path) -> None:
    # Cross-cutting infrastructure modules (config dataclass, shared models,
    # Port protocols, post-merge handler) are bare-cited by many ADRs as a
    # dependency. A file-level touch is implementation churn, not a semantic
    # change to any one ADR's decision — it must NOT drift (the dominant
    # ADR-drift false-positive source). Require a :Symbol citation to drift.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=50,
        title="depends on config",
        status="Accepted",
        related_files=["src/config.py"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir), pr_number=1, changed_files=["src/config.py"]
    )
    assert findings == []


def test_symbol_citation_of_shared_infra_module_still_drifts(tmp_path: Path) -> None:
    # An ADR that genuinely owns a shared-infra symbol cites it at :Symbol
    # granularity and still drifts when that symbol changes.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=51,
        title="owns config schema",
        status="Accepted",
        related_files=["src/config.py:HydraFlowConfig"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/config.py:HydraFlowConfig"],
    )
    assert len(findings) == 1
    assert findings[0].adr.number == 51


def test_bare_citation_of_non_infra_module_still_drifts(tmp_path: Path) -> None:
    # Regression guard: the shared-infra suppression must not change file-level
    # drift for ordinary (non-infra) cited modules.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=52,
        title="owns widget",
        status="Accepted",
        related_files=["src/widget.py"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir), pr_number=1, changed_files=["src/widget.py"]
    )
    assert len(findings) == 1
    assert findings[0].adr.number == 52


def test_adr_file_in_diff_helper(adr_index: ADRIndex) -> None:
    adr = next(a for a in adr_index.adrs() if a.number == 1)
    assert _adr_file_in_diff(adr, ["docs/adr/0001-alpha.md"])
    assert _adr_file_in_diff(adr, ["docs/adr/0001-renamed.md"])
    assert not _adr_file_in_diff(adr, ["docs/adr/0002-beta.md"])
    assert not _adr_file_in_diff(adr, ["src/alpha.py"])


def test_drift_finding_is_immutable() -> None:
    f = DriftFinding(
        adr=ADR(number=1, title="x", status="Accepted", summary=""),
        pr_number=1,
        changed_cited_files=("src/x.py",),
    )
    with pytest.raises(AttributeError):  # frozen dataclass
        f.pr_number = 2  # type: ignore[misc]


def test_compute_drift_by_adr_groups_multiple_prs(adr_index: ADRIndex) -> None:
    """#8987 — 3 PRs drifting the same ADR collapse into one rollup entry."""
    rollups = compute_drift_by_adr(
        adr_index,
        [
            (10, ["src/alpha.py"]),
            (11, ["src/alpha.py", "tests/x.py"]),
            (12, ["src/alpha.py"]),
        ],
    )
    assert len(rollups) == 1
    entry = rollups[0]
    assert entry.adr.number == 1
    assert entry.pr_numbers == (10, 11, 12)
    assert len(entry.contributors) == 3


def test_compute_drift_by_adr_one_pr_n_adrs(adr_index: ADRIndex) -> None:
    """#8987 — one PR drifting two ADRs yields two rollup entries."""
    rollups = compute_drift_by_adr(
        adr_index,
        [(99, ["src/alpha.py", "src/beta.py"])],
    )
    assert [e.adr.number for e in rollups] == [1, 2]
    for entry in rollups:
        assert entry.pr_numbers == (99,)


def test_compute_drift_by_adr_skips_prs_with_adr_in_diff(adr_index: ADRIndex) -> None:
    """A PR whose diff includes the ADR file is silently skipped for that ADR."""
    rollups = compute_drift_by_adr(
        adr_index,
        [
            (10, ["src/alpha.py"]),
            (11, ["src/alpha.py", "docs/adr/0001-alpha.md"]),
        ],
    )
    assert len(rollups) == 1
    assert rollups[0].pr_numbers == (10,)


def test_compute_drift_by_adr_empty_input(adr_index: ADRIndex) -> None:
    assert compute_drift_by_adr(adr_index, []) == []


def test_adr_rollup_entry_is_immutable(adr_index: ADRIndex) -> None:
    adr = next(a for a in adr_index.adrs() if a.number == 1)
    entry = AdrRollupEntry(
        adr=adr,
        contributors=(
            DriftFinding(adr=adr, pr_number=1, changed_cited_files=("src/alpha.py",)),
        ),
    )
    with pytest.raises(AttributeError):  # frozen dataclass
        entry.adr = adr  # type: ignore[misc]
