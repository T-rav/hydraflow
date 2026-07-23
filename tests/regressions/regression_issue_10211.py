"""Regression guard for #10211 — ADR conformance mass false-positive storm.

Root cause: ``SubprocessConformanceRunner.run()`` invoked pytest-kind checks
via a bare ``"python"`` on ``PATH`` rather than ``sys.executable``. Background
loop processes don't necessarily inherit an interactive shell's PATH, so
``python -m pytest`` resolved to a venv without pytest installed. Every single
pytest-kind conformance check across 27 unrelated ADRs failed simultaneously
with ``ModuleNotFoundError: No module named pytest`` (visible in each filed
issue's detail line), which the exit-code mapping misread as a genuine `FAIL`
— a mass false-positive drift storm that tripped
``TrustFleetSanityLoop``'s ``issues_per_hour`` anomaly detector (27 filed vs.
threshold 10) and escalated a HITL issue (#10211) for a problem that was
never real ADR drift.

Mirrors the identical fix already applied once in ``skill_prompt_eval_loop.py``
for the same bug class (see its ``sys.executable`` comment).
"""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

from adr_conformance import CheckOutcome
from adr_conformance_runner import SubprocessConformanceRunner
from adr_index import Check


def test_pytest_check_invokes_sys_executable(monkeypatch, tmp_path) -> None:
    """The pytest-kind subprocess command must pin ``sys.executable`` — never
    a bare "python" that can resolve to a different, dependency-incomplete
    interpreter on the loop process's PATH (#10211)."""
    seen = {}

    def _capture(cmd, **k):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _capture)
    runner = SubprocessConformanceRunner()
    runner.run(
        Check("pytest", "tests/test_x.py", "pytest:tests/test_x.py"),
        repo_root=tmp_path,
    )
    assert seen["cmd"][0] == sys.executable
    assert seen["cmd"][0] != "python", (
        "must be the resolved interpreter path, not the bare literal 'python' "
        "that PATH resolution could point anywhere (#10211)"
    )


def test_missing_pytest_module_does_not_silently_pass_as_something_else(
    monkeypatch, tmp_path
) -> None:
    """Documents the failure signature seen in production (#10211): a
    ``ModuleNotFoundError`` from a wrong interpreter exits nonzero (not
    pytest's exit-5 "no tests collected") and is correctly mapped to FAIL —
    proving the class of bug is fixed at the interpreter-selection layer, not
    by adding special-case exit-code handling that would mask other real
    failures."""

    def _module_not_found(cmd, **k):
        assert cmd[0] == sys.executable, (
            "must invoke the current interpreter, not a bare 'python' that "
            "could be missing pytest (#10211)"
        )
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=f"{sys.executable}: No module named pytest\n",
        )

    monkeypatch.setattr(subprocess, "run", _module_not_found)
    runner = SubprocessConformanceRunner()
    res = runner.run(
        Check("pytest", "tests/test_x.py", "pytest:tests/test_x.py"),
        repo_root=tmp_path,
    )
    # With the fix, this path is unreachable in practice (sys.executable
    # always has pytest, since it's the interpreter running this loop) — but
    # if the environment is ever misconfigured, a module-not-found error
    # correctly returns FAIL rather than being silently swallowed.
    assert res.outcome is CheckOutcome.FAIL
