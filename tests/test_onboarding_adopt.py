"""Tests for the adopt flow (#11060 slice 3) — brownfield audit, read-only."""

from __future__ import annotations

from pathlib import Path

from onboarding.adopt import (
    AdoptAction,
    adoption_report,
    render_adopt,
)
from onboarding.kernel_writer import KernelSpec, Ownership, stamp_kernel

_SPEC = KernelSpec(name="brown-field", package_name="brownfield")

_PLAN: list[tuple[str, str, Ownership]] = [
    ("Makefile", "template content\n", Ownership.TEMPLATE),
    ("CLAUDE.md", "product seed\n", Ownership.PRODUCT),
    ("scripts/prep.py", "prep\n", Ownership.TEMPLATE),
]


def test_empty_directory_is_all_new_and_safe(tmp_path: Path) -> None:
    report = adoption_report(_SPEC, tmp_path, plan=_PLAN)
    assert all(state is AdoptAction.NEW for state in report.files.values())
    assert report.safe_to_stamp


def test_matching_files_are_identical(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("template content\n")
    report = adoption_report(_SPEC, tmp_path, plan=_PLAN)
    assert report.files["Makefile"] is AdoptAction.IDENTICAL
    assert report.safe_to_stamp


def test_divergent_template_file_blocks_safe_verdict(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("their own makefile\n")
    report = adoption_report(_SPEC, tmp_path, plan=_PLAN)
    assert report.files["Makefile"] is AdoptAction.DIFFERS_TEMPLATE
    assert not report.safe_to_stamp


def test_divergent_product_file_is_informational_only(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("their own rules\n")
    report = adoption_report(_SPEC, tmp_path, plan=_PLAN)
    assert report.files["CLAUDE.md"] is AdoptAction.DIFFERS_PRODUCT
    assert report.safe_to_stamp  # product divergence never blocks — never touched


def test_audit_writes_nothing(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("their own makefile\n")
    before = sorted(p.name for p in tmp_path.iterdir())
    adoption_report(_SPEC, tmp_path, plan=_PLAN)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert (tmp_path / "Makefile").read_text() == "their own makefile\n"


def test_render_carries_verdict_and_next_steps(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("their own makefile\n")
    report = adoption_report(_SPEC, tmp_path, plan=_PLAN)
    out = render_adopt(report, tmp_path)
    assert "DIFFERS(template) Makefile" in out
    assert "FORCE=1" in out
    assert "kernel-staleness" in out

    safe = render_adopt(
        adoption_report(_SPEC, tmp_path / "fresh", plan=_PLAN), tmp_path
    )
    assert "plain stamp touches only NEW files" in safe


def test_against_the_real_prescription_round_trip(tmp_path: Path) -> None:
    """Stamp a repo for real, then adopt-audit it: everything IDENTICAL."""
    target = tmp_path / "repo"
    stamp_kernel(_SPEC, target)
    report = adoption_report(_SPEC, target)
    assert report.files  # the real prescription is non-trivial
    assert all(
        state in (AdoptAction.IDENTICAL, AdoptAction.NEW)
        for state in report.files.values()
    )
    # A freshly stamped repo diverges nowhere.
    assert report.count(AdoptAction.IDENTICAL) > 20
    assert report.safe_to_stamp
