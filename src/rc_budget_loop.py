"""RCBudgetLoop — 4h RC CI wall-clock regression detector (spec §4.8).

Reads the last 30 days of ``rc-promotion-scenario.yml`` runs via ``gh
run list``, extracts per-run wall-clock duration, and emits a
``hydraflow-find`` + ``rc-duration-regression`` issue when the newest
run trips either:

- *Gradual bloat*: ``current_s >= rc_budget_threshold_ratio *
  rolling_median`` (default ratio ``1.5``).
- *Sudden spike*: ``current_s >= rc_budget_spike_ratio * max(recent-5,
  excluding current)`` (default ratio ``2.0``).

Signals are independent; both may fire on the same tick (two distinct
dedup keys). After 3 unresolved attempts per signal the loop files a
``hitl-escalation`` + ``rc-duration-stuck`` issue. Dedup keys clear on
escalation-close per spec §3.2.

Kill-switch: ``LoopDeps.enabled_cb("rc_budget")`` — **no
``rc_budget_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.rc_budget_loop")

_MAX_ATTEMPTS = 3
_WINDOW_DAYS = 30
_HISTORY_CAP = 60
_RECENT_N = 5
_MIN_HISTORY = 5
_WORKFLOW = "rc-promotion-scenario.yml"


class RCBudgetLoop(BaseBackgroundLoop):
    """Detects RC wall-clock bloat via median + spike signals (spec §4.8)."""

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
            worker_name="rc_budget",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.rc_budget_interval

    async def _do_work(self) -> WorkCycleResult:
        """Skeleton — Task 5 replaces with the full tick."""
        await self._reconcile_closed_escalations()
        runs = await self._fetch_recent_runs()
        if len(runs) < _MIN_HISTORY:
            return {"status": "warmup", "runs_seen": len(runs)}
        return {"status": "noop", "runs_seen": len(runs)}

    async def _fetch_recent_runs(self) -> list[dict[str, Any]]:
        """Task 4."""
        return []

    async def _reconcile_closed_escalations(self) -> None:
        """Task 5."""
        return None
