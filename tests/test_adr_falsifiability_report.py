"""Tests for the ADR falsifiability baseline generator (#10830 wiring)."""

from __future__ import annotations

from pathlib import Path

from adr_index import ADR
from arch.generators.adr_falsifiability_report import render_adr_falsifiability


def _adr(number: int, status: str = "Accepted") -> ADR:
    return ADR(number=number, title="t", status=status, summary="s")


def _write_adr(adr_dir: Path, number: int, body: str) -> None:
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / f"{number:04d}-x.md").write_text(body, encoding="utf-8")


def test_baseline_reports_density_over_accepted_adrs(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    # A checkable ADR: every statement carries a marker.
    _write_adr(
        adr_dir,
        1,
        "The loop MUST poll every 60 seconds. It reads `state.json` on boot. "
        "Enforced by src/config.py behaviour.",
    )
    # A mushy ADR: hedges with nothing checkable.
    _write_adr(
        adr_dir,
        2,
        "It should generally be clean. Things ought to be reasonable. "
        "Nice and simple where possible.",
    )
    out = render_adr_falsifiability([_adr(1), _adr(2)], repo_root=tmp_path)

    assert "# ADR Falsifiability Baseline" in out
    assert "Accepted (2 ADRs)" in out
    assert "ADR-0001" in out and "ADR-0002" in out
    # The mushy ADR (density 0% < the 25% floor) is flagged below the floor.
    assert "ADR-0002" in out.split("Below the mush floor")[1].split("\n")[0]
    assert out.rstrip().endswith("{{ARCH_FOOTER}}")


def test_non_accepted_adrs_are_excluded(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    _write_adr(adr_dir, 1, "The loop MUST poll every 60 seconds.")
    _write_adr(adr_dir, 2, "The gate SHALL block on src/x.py failures.")
    out = render_adr_falsifiability(
        [_adr(1, status="Accepted"), _adr(2, status="Proposed")], repo_root=tmp_path
    )
    assert "Accepted (1 ADRs)" in out
    assert "ADR-0001" in out
    assert "ADR-0002" not in out


def test_missing_or_empty_corpus_is_calm(tmp_path: Path) -> None:
    out = render_adr_falsifiability([_adr(1)], repo_root=tmp_path)  # no files on disk
    assert "no Accepted ADRs with prose to measure" in out
