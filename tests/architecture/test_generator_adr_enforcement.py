"""Tests for the ADR enforcement-debt report generator (issue #10411)."""

from __future__ import annotations

from pathlib import Path

from adr_conformance import EnforcementClass, classify_adr_enforcement
from adr_index import ADR, Check, scan_adr_directory
from arch.generators.adr_enforcement import _parse_exemptions, render_adr_enforcement

_EXEMPTIONS_REL = "docs/standards/adr_enforcement/exemptions.md"


def _write_exemptions(root: Path, body: str) -> None:
    """Materialise an exemptions allow-list under a tmp repo root."""
    path = root / _EXEMPTIONS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


REPO = Path(__file__).resolve().parents[2]
ADR_DIR = REPO / "docs" / "adr"


def _pytest(target: str) -> Check:
    return Check(kind="pytest", target=target, raw=f"pytest:{target}")


def _adr(number: int, enforcement: str, checks: tuple[Check, ...]) -> ADR:
    return ADR(
        number=number,
        title="synthetic",
        status="Accepted",
        summary="",
        enforcement=enforcement,
        enforced_by=checks,
    )


def _fixture(tmp_path: Path) -> list[ADR]:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "real.py").write_text("def test_x():\n    assert True\n")
    (tmp_path / "tests" / "hollow.py").write_text("def test_y():\n    import os\n")
    return [
        _adr(1, "enforced", (_pytest("tests/real.py::test_x"),)),  # REAL
        _adr(2, "manual", (Check(kind="prose", target="checklist", raw="checklist"),)),
        _adr(3, "decision-of-record", ()),  # MISSING
        _adr(4, "enforced", (_pytest("tests/hollow.py::test_y"),)),  # REAL but hollow
        # A Proposed ADR must be excluded entirely.
        ADR(
            number=99,
            title="prop",
            status="Proposed",
            summary="",
            enforcement="enforced",
        ),
    ]


def test_headings_present(tmp_path: Path):
    out = render_adr_enforcement(_fixture(tmp_path), repo_root=tmp_path)
    assert out.startswith("# ADR Enforcement Debt")
    for heading in (
        "## Summary",
        "## Classification",
        "## Unenforced-decision debt",
        "## Weak / tautological enforcements",
    ):
        assert heading in out, f"missing section: {heading}"
    # The generator emits the unstamped footer sentinel; runner.emit() stamps it.
    assert "{{ARCH_FOOTER}}" in out


def test_summary_counts_and_debt_percentage(tmp_path: Path):
    out = render_adr_enforcement(_fixture(tmp_path), repo_root=tmp_path)
    # 4 accepted (99 is Proposed → excluded): 2 REAL (1,4), 1 WEAK (2), 1 MISSING (3).
    assert "**Accepted ADRs:** 4" in out
    assert "**REAL** (real asserting enforcement): 2" in out
    assert "**WEAK** (prose-only or tautological): 1" in out
    assert "**MISSING** (no `**Enforced by:**`): 1" in out
    # debt = WEAK + MISSING = 2 / 4 = 50.0%
    assert "2 / 4 = 50.0%" in out


def test_proposed_adr_excluded(tmp_path: Path):
    out = render_adr_enforcement(_fixture(tmp_path), repo_root=tmp_path)
    assert "ADR-0099" not in out


def test_hollow_check_surfaced_but_not_downgraded(tmp_path: Path):
    fixture = _fixture(tmp_path)
    out = render_adr_enforcement(fixture, repo_root=tmp_path)
    # ADR-4's hollow check is listed in the tautological section...
    assert "tests/hollow.py::test_y" in out
    # ...yet ADR-4 is still classified REAL (tautology is advisory only).
    assert classify_adr_enforcement(fixture[3], tmp_path) is EnforcementClass.REAL


def test_deterministic(tmp_path: Path):
    fixture = _fixture(tmp_path)
    a = render_adr_enforcement(fixture, repo_root=tmp_path)
    b = render_adr_enforcement(fixture, repo_root=tmp_path)
    assert a == b


def test_live_report_smoke(real_repo_root: Path):
    """The generator runs over the real ADR corpus and emits a coherent debt
    line whose headline reflects the live classifier minus justified,
    allow-listed process-only exemptions (the same set the ratchet gates on)."""
    adrs = scan_adr_directory(real_repo_root / "docs" / "adr")
    accepted = [a for a in adrs if a.status == "Accepted"]
    by_class = {a.number: classify_adr_enforcement(a, real_repo_root) for a in accepted}
    exempted = set(_parse_exemptions(real_repo_root))
    gross_debt = {
        a.number
        for a in accepted
        if by_class[a.number] in (EnforcementClass.WEAK, EnforcementClass.MISSING)
    }
    outstanding = gross_debt - exempted
    out = render_adr_enforcement(adrs, repo_root=real_repo_root)
    assert f"**Accepted ADRs:** {len(accepted)}" in out
    assert f"**{len(outstanding)} / {len(accepted)} =" in out, (
        "headline must reflect the live REAL/WEAK/MISSING split minus exemptions"
    )


def test_live_exemptions_excluded_from_outstanding_debt(real_repo_root: Path):
    """The three process-only ADRs named in issue #10868 (0025/0035/0051) are
    active exemptions and are dropped from the outstanding-debt headline — the
    exemption-blindness that re-fired the issue is gone."""
    adrs = scan_adr_directory(real_repo_root / "docs" / "adr")
    accepted = [a for a in adrs if a.status == "Accepted"]
    by_class = {a.number: classify_adr_enforcement(a, real_repo_root) for a in accepted}
    exemptions = _parse_exemptions(real_repo_root)
    gross_debt = {
        a.number
        for a in accepted
        if by_class[a.number] in (EnforcementClass.WEAK, EnforcementClass.MISSING)
    }

    # The three ADRs the issue is about are exempt and are genuinely WEAK/MISSING
    # (so excluding them actually moves the number — the test is not vacuous).
    for number in (25, 35, 51):
        assert number in exemptions, f"ADR-{number:04d} must be an active exemption"
        assert number in gross_debt, f"ADR-{number:04d} must be WEAK/MISSING debt"

    outstanding = gross_debt - set(exemptions)
    assert not (outstanding & {25, 35, 51}), (
        "exempted ADRs must not count toward outstanding debt"
    )
    assert len(outstanding) < len(gross_debt), (
        "exemptions must strictly reduce the debt headline"
    )

    out = render_adr_enforcement(adrs, repo_root=real_repo_root)
    assert f"**{len(outstanding)} / {len(accepted)} =" in out
    assert "### Justified exemptions (process-only, allow-listed)" in out
    # Each exempted debt ADR is surfaced with its recorded justification.
    for number in (25, 35, 51):
        assert f"ADR-{number:04d}" in out


def test_exempted_weak_adr_excluded_from_outstanding_debt(tmp_path: Path):
    """A WEAK ADR listed in exemptions.md is marked exempt and left out of the
    outstanding-debt count, while its justification is rendered."""
    fixture = _fixture(tmp_path)  # ADR-2 is WEAK (manual prose), ADR-3 MISSING.
    _write_exemptions(
        tmp_path,
        "## Active exemptions\n\n"
        "- ADR-0002: prose-only review checklist, no on-disk invariant\n",
    )
    out = render_adr_enforcement(fixture, repo_root=tmp_path)

    # 2 debt ADRs (2 WEAK, 3 MISSING); one exempt → outstanding = 1.
    assert "**Justified exemptions** (process-only, allow-listed): 1" in out
    assert "**1 / 4 = 25.0%**" in out
    # The exempt ADR is marked in the classification table and its justification
    # appears under the exemptions subsection.
    assert "| ADR-0002 | WEAK | exempt |" in out
    assert "prose-only review checklist, no on-disk invariant" in out


def test_non_exempt_weak_adr_still_counts_as_debt(tmp_path: Path):
    """An exemptions file that does not name a WEAK ADR leaves it in the
    outstanding-debt headline — exemptions are opt-in, not blanket amnesty."""
    fixture = _fixture(tmp_path)
    _write_exemptions(
        tmp_path,
        "## Active exemptions\n\n- ADR-0777: some unrelated decision\n",
    )
    out = render_adr_enforcement(fixture, repo_root=tmp_path)
    # None of the fixture's debt ADRs are exempt → outstanding = gross = 2.
    assert "**Justified exemptions** (process-only, allow-listed): 0" in out
    assert "**2 / 4 = 50.0%**" in out
    assert "| ADR-0002 | WEAK | — |" in out


def _attribution_fixture(tmp_path: Path, *, named: bool) -> list[ADR]:
    (tmp_path / "tests").mkdir(exist_ok=True)
    header = '"""Enforces ADR-0007."""\n' if named else ""
    (tmp_path / "tests" / "e.py").write_text(
        header + "def test_x():\n    assert True\n"
    )
    return [_adr(7, "enforced", (_pytest("tests/e.py::test_x"),))]


def test_unattributed_section_lists_the_offender(tmp_path: Path):
    """A REAL ADR whose test never names it is surfaced in the section (#10861)."""
    out = render_adr_enforcement(
        _attribution_fixture(tmp_path, named=False), repo_root=tmp_path
    )
    section = out.split("## Unattributed enforcements", 1)[1]
    assert "| ADR-0007 |" in section
    assert "tests/e.py::test_x" in section


def test_unattributed_section_none_when_all_named(tmp_path: Path):
    out = render_adr_enforcement(
        _attribution_fixture(tmp_path, named=True), repo_root=tmp_path
    )
    assert "## Unattributed enforcements\n\n_(none)_" in out


def test_missing_exemptions_file_degrades_gracefully(tmp_path: Path):
    """With no exemptions.md present the report renders exactly as before —
    full WEAK+MISSING debt, no exemptions, no crash."""
    fixture = _fixture(tmp_path)
    assert not (tmp_path / _EXEMPTIONS_REL).exists()
    out = render_adr_enforcement(fixture, repo_root=tmp_path)
    assert "**Justified exemptions** (process-only, allow-listed): 0" in out
    assert "**2 / 4 = 50.0%**" in out
    assert "### Justified exemptions (process-only, allow-listed)\n\n_(none)_" in out
