"""Unit tests for burn-down unit selection (pure)."""

from __future__ import annotations

from disturbance.burndown import BurndownUnit, select_units
from disturbance.models import Finding


def _f(dim: str, path: str, code: str) -> Finding:
    return Finding(dimension=dim, path=path, signature=f"{path}::{code}", message="m")


def test_selects_backlog_files_smallest_first_and_caps() -> None:
    findings = [
        _f("suppressions", "src/big.py", "noqa"),
        _f("suppressions", "src/big.py", "type-ignore"),
        _f("suppressions", "src/small.py", "noqa"),
    ]
    baseline = {
        "src/big.py::noqa": 1,
        "src/big.py::type-ignore": 1,
        "src/small.py::noqa": 1,
    }
    units = select_units(
        [("suppressions", "fix it", findings, baseline)], deduped=set(), cap=1
    )
    assert len(units) == 1
    assert isinstance(units[0], BurndownUnit)
    # smallest file (fewest baseline-present findings) first
    assert units[0].path == "src/small.py"
    assert units[0].dedup_key == "disturbance:suppressions:src/small.py"
    assert units[0].signatures == ("src/small.py::noqa",)


def test_excludes_deduped_and_non_baseline_findings() -> None:
    findings = [
        _f("suppressions", "src/a.py", "noqa"),  # in baseline, but deduped
        _f(
            "suppressions", "src/b.py", "noqa"
        ),  # NOT in baseline (newly clean) -> excluded
    ]
    baseline = {"src/a.py::noqa": 1}
    units = select_units(
        [("suppressions", "fix it", findings, baseline)],
        deduped={"disturbance:suppressions:src/a.py"},
        cap=5,
    )
    assert units == []
