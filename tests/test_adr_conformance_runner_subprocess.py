"""SubprocessConformanceRunner exit-code + citation-type handling (ADR-0100).

Regression coverage for bead advisor-qqyo: a dry-run of the loop against the
real ADR corpus filed 3 false-positive drift issues because the runner mapped
every non-zero pytest exit to FAIL. Two cases were misread:

* scenario_loops/scenario_browser citations were deselected by pyproject's
  default ``-m`` filter → 0 tests collected → pytest exit 5 → FAIL;
* sandbox-tier citations can't run in-process (they need the docker harness)
  → usage error → FAIL.
"""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from adr_conformance import CheckOutcome
from adr_conformance_runner import SubprocessConformanceRunner
from adr_index import Check


def _fake_proc(returncode: int, out: str = "", err: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=out, stderr=err)


def test_sandbox_citation_is_skipped_without_running(monkeypatch, tmp_path):
    called = {"ran": False}

    def _never(*a, **k):
        called["ran"] = True
        raise AssertionError("sandbox check must not shell out")

    monkeypatch.setattr(subprocess, "run", _never)
    runner = SubprocessConformanceRunner()
    res = runner.run(
        Check(
            "pytest",
            "tests/sandbox_scenarios/scenarios/s50_x.py",
            "pytest:tests/sandbox_scenarios/scenarios/s50_x.py",
        ),
        repo_root=tmp_path,
    )
    assert res.outcome is CheckOutcome.SKIPPED
    assert called["ran"] is False
    assert "sandbox" in (res.detail or "").lower()


def test_pytest_command_clears_marker_deselection(monkeypatch, tmp_path):
    seen = {}

    def _capture(cmd, **k):
        seen["cmd"] = cmd
        return _fake_proc(0)

    monkeypatch.setattr(subprocess, "run", _capture)
    runner = SubprocessConformanceRunner()
    runner.run(
        Check(
            "pytest", "tests/scenarios/test_x.py", "pytest:tests/scenarios/test_x.py"
        ),
        repo_root=tmp_path,
    )
    # The trailing `-m ""` (not the `python -m pytest` one) clears the marker
    # deselection so scenario_loops/browser tests aren't skipped.
    assert seen["cmd"][-2:] == ["-m", ""]


def test_pytest_command_uses_sys_executable_not_bare_python(monkeypatch, tmp_path):
    """#10211: a bare "python" can resolve to a pytest-less venv on the
    background loop's PATH, misreading every pytest check as FAIL. The
    invocation must pin the exact interpreter running this process."""
    seen = {}

    def _capture(cmd, **k):
        seen["cmd"] = cmd
        return _fake_proc(0)

    monkeypatch.setattr(subprocess, "run", _capture)
    runner = SubprocessConformanceRunner()
    runner.run(
        Check("pytest", "tests/test_x.py", "pytest:tests/test_x.py"),
        repo_root=tmp_path,
    )
    assert seen["cmd"][0] == sys.executable
    assert seen["cmd"][0] != "python"


@pytest.mark.parametrize(
    ("rc", "expected"),
    [
        (0, CheckOutcome.PASS),
        (1, CheckOutcome.FAIL),
        (5, CheckOutcome.UNRESOLVED),  # no tests collected, not a failure
        (4, CheckOutcome.FAIL),  # genuine usage/collection error
    ],
)
def test_pytest_exit_code_mapping(monkeypatch, tmp_path, rc, expected):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_proc(rc, "out", "err"))
    runner = SubprocessConformanceRunner()
    res = runner.run(
        Check("pytest", "tests/test_x.py::t", "pytest:tests/test_x.py::t"),
        repo_root=tmp_path,
    )
    assert res.outcome is expected


def test_make_check_still_binary_pass_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_proc(5))
    runner = SubprocessConformanceRunner()
    # exit 5 is pytest-specific; a make target returning 5 is still a failure.
    res = runner.run(Check("make", "arch-check", "make:arch-check"), repo_root=tmp_path)
    assert res.outcome is CheckOutcome.FAIL
