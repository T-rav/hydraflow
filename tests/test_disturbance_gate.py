"""Unit tests for the registry + gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from disturbance.baseline import save_baseline
from disturbance.gate import DeadRatchetArmError, dead_ratchet_arms, run_gate
from disturbance.models import Finding
from disturbance.registry import DimensionSpec


class _FakeDetector:
    name = "fake"

    def __init__(
        self, findings: list[Finding], ceilings: dict[str, int] | None = None
    ) -> None:
        self._findings = findings
        self._ceilings = ceilings or {}

    def detect(self, repo_root: Path) -> list[Finding]:
        return self._findings

    def reachable_ceilings(self) -> dict[str, int]:
        return self._ceilings


def _spec(
    tmp_path: Path, findings: list[Finding], ceilings: dict[str, int] | None = None
) -> DimensionSpec:
    return DimensionSpec(
        name="fake",
        detector=_FakeDetector(findings, ceilings),
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


# ---------------------------------------------------------------------------
# The reachable-range precondition: a gate whose failing region is empty is
# not a passing gate. Asserted on the PREDICATE, on known-dead and known-live
# configurations — a sweep of today's live baselines cannot tell a working
# check from a blind one, because today they all pass.
# ---------------------------------------------------------------------------

_SIG = "src/a.py::x"


def _finding() -> Finding:
    return Finding(dimension="fake", path="src/a.py", signature=_SIG, message="m")


@pytest.mark.parametrize(
    ("ceilings", "baseline_count", "is_dead"),
    [
        # The exact shape traceability shipped in: clamp 100, baseline 100.
        ({_SIG: 100}, 100, True),
        ({_SIG: 100}, 101, True),
        # Ceiling 0: the detector can never emit this signature at all, so
        # even a baseline of 0 has nothing above it. Iterating the baseline
        # alone would never look at it.
        ({_SIG: 0}, 0, True),
        # The known-negatives. Without them the check could refuse
        # everything and every assertion above would still pass.
        ({_SIG: 100}, 99, False),
        # No declared ceiling means unbounded: some reachable count always
        # exceeds the baseline, however large it is.
        ({}, 10**9, False),
    ],
    ids=["at-ceiling", "above-ceiling", "zero-ceiling", "below-ceiling", "unbounded"],
)
def test_dead_ratchet_arms_reports_exactly_the_unreachable_baselines(
    tmp_path: Path,
    ceilings: dict[str, int],
    baseline_count: int,
    is_dead: bool,
) -> None:
    spec = _spec(tmp_path, [], ceilings)

    assert bool(dead_ratchet_arms(spec, {_SIG: baseline_count})) is is_dead


def test_a_ceiling_of_zero_is_reported_even_with_no_baseline_entry(
    tmp_path: Path,
) -> None:
    """The declared set is swept too, not only what the baseline records."""
    spec = _spec(tmp_path, [], {_SIG: 0})

    assert dead_ratchet_arms(spec, {})


def test_the_gate_refuses_to_run_a_dimension_whose_arm_cannot_fire(
    tmp_path: Path,
) -> None:
    """Refusal, not a report: a dead arm must not be runnable past."""
    save_baseline(tmp_path / "fake.yaml", [_finding()] * 100, comment="c")
    spec = _spec(tmp_path, [_finding()] * 100, {_SIG: 100})

    with pytest.raises(DeadRatchetArmError) as excinfo:
        run_gate(tmp_path, [spec])

    assert _SIG in str(excinfo.value)
    assert "failing region is empty" in str(excinfo.value)


def test_the_gate_runs_when_every_arm_has_room_to_fire(tmp_path: Path) -> None:
    """The other direction: a live configuration must still be measured."""
    save_baseline(tmp_path / "fake.yaml", [_finding()] * 99, comment="c")
    spec = _spec(tmp_path, [_finding()] * 100, {_SIG: 100})

    assert run_gate(tmp_path, [spec])["fake"].new == {_SIG: 1}


def test_every_shipped_dimension_declares_reachable_ceilings() -> None:
    """Anti-vacuity for the check above: it needs detectors that answer.

    A detector missing the method would AttributeError inside ``run_gate``
    rather than silently skipping, but the registry is the population this
    precondition is meant to cover and an empty one would prove nothing.
    """
    from disturbance.registry import DIMENSIONS  # noqa: PLC0415

    assert len(DIMENSIONS) >= 3
    for spec in DIMENSIONS:
        assert isinstance(spec.detector.reachable_ceilings(), dict)
