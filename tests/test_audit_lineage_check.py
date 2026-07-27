"""Tests for the ADR lineage fields + the P1.17 STRUCTURAL audit check (ADR-0113).

Covers the pure parser (`scripts/hydraflow_audit/lineage.py`) and the registered
`P1.17` check (`scripts/hydraflow_audit/checks/p1_docs.py`): a control-plane ADR
missing both lines FAILs, one with a valid `Precedent:` and/or a receipt-bearing
`Divergence:` is clean, and a `Divergence:` without a receipt is flagged. Also
pins that the check is STRUCTURAL (no longer advisory) — its FAIL flips the audit
exit code, since the seed pass (#10674) backfilled the control-plane corpus.
"""

from __future__ import annotations

from pathlib import Path

from scripts.hydraflow_audit import registry  # noqa: F401 — import side effect
from scripts.hydraflow_audit.checks import p1_docs  # noqa: F401 — registers P1.17
from scripts.hydraflow_audit.lineage import (
    CONTROL_PLANE_ADRS,
    extract_lineage_table,
    find_lineage_gaps,
    parse_lineage,
)
from scripts.hydraflow_audit.models import CheckContext, Finding, Severity, Status
from scripts.hydraflow_audit.runner import (
    ADVISORY_CHECKS,
    overall_exit_code,
)

# A control-plane number and a non-control-plane number for fixtures.
_CP = 2  # ADR-0002, labels-as-state-machine (control-plane)
_NON_CP = 500  # not in the control-plane set


def _adr(adr_dir: Path, number: int, *body_lines: str) -> None:
    adr_dir.mkdir(parents=True, exist_ok=True)
    header = f"# ADR-{number:04d}: Fixture\n\n**Status:** Accepted\n"
    body = "\n".join(body_lines)
    (adr_dir / f"{number:04d}-fixture.md").write_text(
        f"{header}{body}\n\n## Context\n\nx\n", encoding="utf-8"
    )


def _ctx(root: Path) -> CheckContext:
    return CheckContext(root=root)


def _run_p117(root: Path) -> Finding:
    fn = registry.get("P1.17")
    assert fn is not None, "P1.17 is not registered"
    return fn(_ctx(root))


# ---------------------------------------------------------------------------
# Pure parser (lineage.py)
# ---------------------------------------------------------------------------


def test_parses_bold_and_plain_field_forms_identically() -> None:
    bold = parse_lineage("**Precedent:** SPC (Shewhart 1931)\n")
    plain = parse_lineage("Precedent: SPC (Shewhart 1931)\n")
    assert bold.precedent == plain.precedent == "SPC (Shewhart 1931)"


def test_prose_mention_is_not_read_as_the_field() -> None:
    fields = parse_lineage("The `Precedent:` field is optional here.\n")
    assert fields.precedent is None
    assert not fields.has_any


def test_divergence_with_receipt_is_recognised() -> None:
    fields = parse_lineage(
        "**Divergence:** assumption, forcing condition, rule (receipt: ADR-0004)\n"
    )
    assert fields.divergence is not None
    assert fields.divergence_has_receipt


def test_divergence_without_receipt_is_flagged() -> None:
    fields = parse_lineage("**Divergence:** an assumption breaks, so a new rule\n")
    assert fields.divergence is not None
    assert not fields.divergence_has_receipt


def test_issue_number_counts_as_a_receipt() -> None:
    fields = parse_lineage("Divergence: a, b, c (receipt: #10674)\n")
    assert fields.divergence_has_receipt


def test_extract_lineage_table_maps_numbers_to_fields(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    _adr(adr_dir, _CP, "**Precedent:** SPC (Shewhart 1931)")
    _adr(adr_dir, _NON_CP)  # no lineage lines
    table = extract_lineage_table(adr_dir)
    assert table[_CP].precedent == "SPC (Shewhart 1931)"
    assert not table[_NON_CP].has_any


# ---------------------------------------------------------------------------
# find_lineage_gaps
# ---------------------------------------------------------------------------


def test_gaps_report_control_plane_adr_missing_both_lines(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    _adr(adr_dir, _CP)  # control-plane, no lineage
    gaps = find_lineage_gaps(adr_dir)
    assert gaps.control_plane_missing_both == [_CP]
    assert not gaps.clean


def test_gaps_ignore_non_control_plane_adr_without_lines(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    _adr(adr_dir, _NON_CP)  # not control-plane, no lineage → not a gap
    gaps = find_lineage_gaps(adr_dir)
    assert gaps.control_plane_missing_both == []
    assert gaps.clean


def test_gaps_flag_receiptless_divergence_even_off_control_plane(
    tmp_path: Path,
) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    _adr(adr_dir, _NON_CP, "**Divergence:** an assumption breaks, so a new rule")
    gaps = find_lineage_gaps(adr_dir)
    assert gaps.divergence_without_receipt == [_NON_CP]


# ---------------------------------------------------------------------------
# P1.17 check
# ---------------------------------------------------------------------------


def test_control_plane_adr_missing_both_lines_fails(tmp_path: Path) -> None:
    """The check cited by ADR-0113's Enforced-by: a control-plane ADR carrying
    neither a Precedent: nor a Divergence: line FAILs (STRUCTURAL, #10674)."""
    adr_dir = tmp_path / "docs" / "adr"
    _adr(adr_dir, _CP)  # control-plane, no lineage
    result = _run_p117(tmp_path)
    assert result.status is Status.FAIL
    assert f"ADR-{_CP:04d}" in result.message


def test_control_plane_adr_with_precedent_is_clean(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    _adr(adr_dir, _CP, "**Precedent:** SPC (Shewhart 1931)")
    assert _run_p117(tmp_path).status is Status.PASS


def test_control_plane_adr_with_receipt_bearing_divergence_is_clean(
    tmp_path: Path,
) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    _adr(
        adr_dir,
        _CP,
        "**Divergence:** assumption, forcing condition, rule (receipt: ADR-0004)",
    )
    assert _run_p117(tmp_path).status is Status.PASS


def test_divergence_without_a_receipt_is_flagged_by_the_check(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    _adr(adr_dir, _CP, "**Divergence:** an assumption breaks, so a new rule")
    result = _run_p117(tmp_path)
    assert result.status is Status.FAIL
    assert "receipt" in result.message


def test_check_is_na_without_an_adr_directory(tmp_path: Path) -> None:
    assert _run_p117(tmp_path).status is Status.NA


# ---------------------------------------------------------------------------
# STRUCTURAL: a P1.17 FAIL now flips the audit gate (escalated, #10674 child 5)
# ---------------------------------------------------------------------------


def test_p117_is_no_longer_advisory() -> None:
    assert "P1.17" not in ADVISORY_CHECKS


def test_p117_fail_flips_the_exit_code() -> None:
    fail = Finding(
        check_id="P1.17",
        status=Status.FAIL,
        severity=Severity.STRUCTURAL,
        principle="P1",
        source="ADR-0113",
        what="lineage",
        remediation="add a line",
    )
    assert overall_exit_code([fail]) == 1


def test_the_real_control_plane_set_covers_the_proposal_seed_list() -> None:
    # The proposal's control-plane list must be a subset of what the check scans.
    for number in (2, 29, 44, 49, 51, 99, 100, 101, 103, 104):
        assert number in CONTROL_PLANE_ADRS
