"""Tests for the ADR enforcement-debt report generator (issue #10411)."""

from __future__ import annotations

from pathlib import Path

from adr_conformance import EnforcementClass, classify_adr_enforcement
from adr_index import ADR, Check, scan_adr_directory
from arch.generators.adr_enforcement import render_adr_enforcement

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
    line whose numbers agree with the live classifier."""
    adrs = scan_adr_directory(real_repo_root / "docs" / "adr")
    accepted = [a for a in adrs if a.status == "Accepted"]
    out = render_adr_enforcement(adrs, repo_root=real_repo_root)
    real = sum(
        1
        for a in accepted
        if classify_adr_enforcement(a, real_repo_root) is EnforcementClass.REAL
    )
    debt = len(accepted) - real
    assert f"**Accepted ADRs:** {len(accepted)}" in out
    assert f"{debt} / {len(accepted)} =" in out, (
        "debt line must reflect the live REAL/WEAK/MISSING split"
    )
