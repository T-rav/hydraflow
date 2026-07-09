"""Background loop wrapping :class:`MergeStateWatcher` (ADR-0029).

Also hosts the CH-2 (#9730) approval-record reconciler tick: this loop is
the source-agnostic merge-state caretaker (RC, dependabot, agent, and manual
PRs alike) and is not gated by ``staging_enabled``, so it sees every merge
lane — see :mod:`approval_records` for the capture-point rationale.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from approval_records import ApprovalRecordReconciler
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from merge_state_watcher import MergeStateWatcher

if TYPE_CHECKING:
    from ports import PRPort

logger = logging.getLogger("hydraflow.merge_state_watcher_loop")

_DEFAULT_INTERVAL_SECONDS = 600  # 10 minutes


class MergeStateWatcherLoop(BaseBackgroundLoop):
    """Periodically scan open PRs for conflicts and rebase/escalate them.

    Filter is broad on purpose — RC promotion PRs, dependabot bumps, agent
    PRs, and manual PRs all benefit from auto-rebase when they go DIRTY
    against ``main``. PRs already labeled ``hydraflow-hitl`` (PRUnsticker
    on it) or ``hydraflow-review`` (active reviewer worktree) are skipped
    to avoid stepping on toes.

    Each tick additionally reconciles merge-approval evidence: every
    recently merged PR gets one hash-chained approval record (CH-2, #9730).
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
        approval_reconciler: ApprovalRecordReconciler | None = None,
    ) -> None:
        super().__init__(worker_name="merge_state_watcher", config=config, deps=deps)
        hitl_label = (config.hitl_label or ["hydraflow-hitl"])[0]
        self._watcher = MergeStateWatcher(prs=prs, hitl_label=hitl_label)
        self._approvals = (
            approval_reconciler
            if approval_reconciler is not None
            else ApprovalRecordReconciler(config)
        )

    def _get_default_interval(self) -> int:
        return _DEFAULT_INTERVAL_SECONDS

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.merge_state_watcher_loop_enabled:
            return {"status": "config_disabled"}
        stats = await self._watcher.unstick_conflicts()
        # After unsticking (order matters: a reconciler gh outage propagates
        # to the cycle handler and must not starve conflict handling).
        approvals = await self._approvals.reconcile()
        return {**stats, "approvals": approvals}
