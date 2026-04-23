"""FlakeTrackerLoop — 4h detector for persistently flaky tests.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.5. Reads JUnit XML from the last 20 RC runs (uploaded by
`rc-promotion-scenario.yml`), counts mixed pass/fail occurrences per
test, and files a `hydraflow-find` + `flaky-test` issue when a test's
flake count crosses `flake_threshold` (default 3, comparison `>=`).

After 3 repair attempts for the same test_name the loop files a
second issue labeled `hitl-escalation` + `flaky-test-stuck`. The
dedup key clears when the escalation issue is closed (spec §3.2).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.flake_tracker_loop")

_MAX_ATTEMPTS = 3
_RUN_WINDOW = 20


def parse_junit_xml(xml_bytes: bytes) -> dict[str, str]:
    """Return ``{test_id: "pass"|"fail"}`` per test case in a JUnit XML doc.

    ``test_id`` is ``{classname}.{name}``. A testcase is ``fail`` if it
    has any ``<failure>`` or ``<error>`` child element; ``skip`` is
    treated as ``pass`` (skipped tests are not flakes).
    """
    results: dict[str, str] = {}
    root = ET.fromstring(xml_bytes)  # nosec B314 — JUnit XML from trusted CI artifacts
    for case in root.iter("testcase"):
        cls = case.get("classname") or ""
        name = case.get("name") or ""
        test_id = f"{cls}.{name}".lstrip(".")
        failed = any(c.tag in ("failure", "error") for c in case)
        results[test_id] = "fail" if failed else "pass"
    return results


class FlakeTrackerLoop(BaseBackgroundLoop):
    """Detects persistently flaky tests in the RC window (spec §4.5)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="flake_tracker",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.flake_tracker_interval

    async def _do_work(self) -> WorkCycleResult:
        """Skeleton — subsequent tasks fill in the tick."""
        return {"status": "noop"}
