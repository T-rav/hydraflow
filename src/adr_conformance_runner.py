"""Subprocess adapter for executing ADR conformance checks (ADR-0094).

Read-only by contract: only check-mode targets are ever cited (the coverage
ratchet rejects mutating ones), so execution here does not mutate the repo.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from adr_conformance import CheckOutcome, CheckResult
from adr_index import Check


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
            cmd = ["python", "-m", "pytest", check.target, "-q"]
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
        outcome = CheckOutcome.PASS if proc.returncode == 0 else CheckOutcome.FAIL
        detail = (
            None if outcome is CheckOutcome.PASS else (proc.stdout + proc.stderr)[-500:]
        )
        return CheckResult(
            check=check.raw, outcome=outcome, duration_s=dur, detail=detail
        )
