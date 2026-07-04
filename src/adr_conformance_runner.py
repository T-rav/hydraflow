"""Subprocess adapter for executing ADR conformance checks (ADR-0100).

Read-only by contract: only check-mode targets are ever cited (the coverage
ratchet rejects mutating ones), so execution here does not mutate the repo.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from adr_conformance import CheckOutcome, CheckResult
from adr_index import Check

# pytest's exit code for "no tests were collected" (pytest.ExitCode
# .NO_TESTS_COLLECTED). Distinct from 1 (tests ran and failed): a cited node
# that collects nothing is a resolution problem, not a conformance failure.
_PYTEST_NO_TESTS_COLLECTED = 5

# Sandbox-tier scenarios (ADR-0052/0083) only run inside the docker Tier-C
# harness — they need its ``--confcutdir=/work/...`` layout and cannot execute
# as plain in-process pytest. They are enforced by the sandbox CI job, not by
# this loop, so citing one is legitimate; the runner must not misread its
# in-process usage error as conformance drift.
_SANDBOX_PREFIX = "tests/sandbox_scenarios/"


class SubprocessConformanceRunner:
    """Real adapter for ``ports.ConformanceRunnerPort``.

    Executes pytest node IDs and make targets as subprocesses; prose checks
    resolve to ``CheckOutcome.MANUAL`` without shelling out.
    """

    def run(
        self, check: Check, *, repo_root: Path, timeout_s: float = 300.0
    ) -> CheckResult:
        if check.kind == "prose":
            return CheckResult(check=check.raw, outcome=CheckOutcome.MANUAL)
        if check.kind == "pytest":
            if check.target.startswith(_SANDBOX_PREFIX):
                return CheckResult(
                    check=check.raw,
                    outcome=CheckOutcome.SKIPPED,
                    detail=(
                        "sandbox-tier scenario — enforced by the docker sandbox "
                        "job (ADR-0052/0083), not runnable as in-process pytest"
                    ),
                )
            # ``-m ''`` clears pyproject's default marker deselection
            # (``not soak and not docker and not evals and not scenario_loops
            # and not scenario_browser``). Without it, a cited scenario_loops/
            # scenario_browser test collects zero tests (exit 5) and is misread
            # as a failure; with it the cited test actually executes.
            cmd = ["python", "-m", "pytest", check.target, "-q", "-m", ""]
        else:  # make
            cmd = ["make", check.target]
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(
                check=check.raw,
                outcome=CheckOutcome.FAIL,
                duration_s=timeout_s,
                detail="timeout",
            )
        dur = time.perf_counter() - t0
        if proc.returncode == 0:
            outcome = CheckOutcome.PASS
        elif check.kind == "pytest" and proc.returncode == _PYTEST_NO_TESTS_COLLECTED:
            # Node resolved (the ratchet verified it exists via AST) but
            # collected no tests at runtime — the target likely moved or was
            # emptied. UNRESOLVED routes to rename-detection/repoint, not a
            # false "the architecture regressed" FAIL.
            outcome = CheckOutcome.UNRESOLVED
        else:
            outcome = CheckOutcome.FAIL
        detail = (
            None if outcome is CheckOutcome.PASS else (proc.stdout + proc.stderr)[-500:]
        )
        return CheckResult(
            check=check.raw, outcome=outcome, duration_s=dur, detail=detail
        )
