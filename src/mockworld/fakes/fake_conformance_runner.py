"""FakeConformanceRunner — ConformanceRunnerPort impl for scenario/unit tests.

Registered fake required by ADR-0047 (every Port needs a fake). Maps a
check's ``raw`` identity to a preset ``CheckOutcome`` so tests can drive
``AdrConformanceLoop`` and ``evaluate_adrs`` without shelling out. Records
the checks it was asked to run so tests can assert short-circuit behavior
(e.g. an unresolved check is never executed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from adr_conformance import CheckOutcome, CheckResult

if TYPE_CHECKING:
    from pathlib import Path

    from adr_index import Check


class FakeConformanceRunner:
    """In-memory ConformanceRunnerPort: ``check.raw`` -> preset outcome."""

    def __init__(
        self,
        outcomes: dict[str, CheckOutcome] | None = None,
        *,
        available: bool = True,
    ) -> None:
        self._outcomes = outcomes or {}
        self.calls: list[str] = []
        # Pre-flight probe result (#10243). Defaults True so existing scenarios
        # exercise the normal path; a test flips it to drive the broken-runner-
        # env short circuit (loop skips the tick, files nothing).
        self._available = available

    def available(self) -> bool:
        return self._available

    def run(
        self, check: Check, *, repo_root: Path, timeout_s: float = 300.0
    ) -> CheckResult:
        self.calls.append(check.raw)
        return CheckResult(
            check=check.raw,
            outcome=self._outcomes.get(check.raw, CheckOutcome.FAIL),
        )
