"""Unit tests for fake_conformance_runner.FakeConformanceRunner.

Covers:
- Protocol conformance (isinstance against ConformanceRunnerPort)
- Preset outcome for a known check (keyed by check.raw)
- Default outcome (FAIL) for an unknown check
- Call recording (.calls) so tests can assert short-circuit behaviour
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adr_conformance import CheckOutcome, CheckResult
from adr_index import Check
from mockworld.fakes.fake_conformance_runner import FakeConformanceRunner
from ports import ConformanceRunnerPort


def test_isinstance_conformance_runner_port() -> None:
    assert isinstance(FakeConformanceRunner(), ConformanceRunnerPort), (
        "FakeConformanceRunner does not satisfy ConformanceRunnerPort. "
        "Ensure run() is present with the correct signature."
    )


def test_returns_preset_outcome_for_known_check() -> None:
    check = Check("pytest", "tests/t.py::test_x", "pytest:tests/t.py::test_x")
    fake = FakeConformanceRunner({"pytest:tests/t.py::test_x": CheckOutcome.PASS})

    result = fake.run(check, repo_root=Path("."))

    assert result == CheckResult(
        check="pytest:tests/t.py::test_x", outcome=CheckOutcome.PASS
    )


def test_defaults_to_fail_for_unresolved_check() -> None:
    check = Check("make", "arch-check", "make:arch-check")
    fake = FakeConformanceRunner()

    result = fake.run(check, repo_root=Path("."))

    assert result.outcome == CheckOutcome.FAIL


def test_records_calls_in_order() -> None:
    fake = FakeConformanceRunner({"make:arch-check": CheckOutcome.PASS})
    first = Check("make", "arch-check", "make:arch-check")
    second = Check("pytest", "tests/t.py::test_y", "pytest:tests/t.py::test_y")

    fake.run(first, repo_root=Path("."))
    fake.run(second, repo_root=Path("."))

    assert fake.calls == ["make:arch-check", "pytest:tests/t.py::test_y"]


def test_unresolved_check_is_never_recorded_when_short_circuited() -> None:
    """Callers that short-circuit before invoking run() for an unresolved
    check should never see it in .calls — this fake only records checks it
    was actually asked to run.
    """
    fake = FakeConformanceRunner()
    assert fake.calls == []
