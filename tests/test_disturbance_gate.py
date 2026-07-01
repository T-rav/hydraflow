"""Unit tests for the registry + gate."""

from __future__ import annotations

from pathlib import Path

from disturbance.baseline import save_baseline
from disturbance.gate import run_gate
from disturbance.models import Finding
from disturbance.registry import DimensionSpec


class _FakeDetector:
    name = "fake"

    def __init__(self, findings: list[Finding]) -> None:
        self._findings = findings

    def detect(self, repo_root: Path) -> list[Finding]:
        return self._findings


def _spec(tmp_path: Path, findings: list[Finding]) -> DimensionSpec:
    return DimensionSpec(
        name="fake",
        detector=_FakeDetector(findings),
        baseline_path=tmp_path / "fake.yaml",
        fix_prompt="fix it",
    )


def test_gate_passes_when_current_matches_baseline(tmp_path: Path) -> None:
    f = Finding(dimension="fake", path="src/a.py", signature="src/a.py::x", message="m")
    save_baseline(tmp_path / "fake.yaml", [f], comment="c")
    results = run_gate(tmp_path, [_spec(tmp_path, [f])])
    assert results["fake"].new == {} and results["fake"].resolved == {}


def test_gate_reports_new_when_count_grows(tmp_path: Path) -> None:
    f = Finding(dimension="fake", path="src/a.py", signature="src/a.py::x", message="m")
    save_baseline(tmp_path / "fake.yaml", [], comment="c")  # empty baseline
    results = run_gate(tmp_path, [_spec(tmp_path, [f])])
    assert results["fake"].new == {"src/a.py::x": 1}
