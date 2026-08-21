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
from dedup_store import DedupStore
from events import EventType, HydraFlowEvent
from merge_state_watcher import MergeStateWatcher
from pr_autorebase import PRAutoRebase

if TYPE_CHECKING:
    from ports import PRPort

logger = logging.getLogger("hydraflow.merge_state_watcher_loop")

_DEFAULT_INTERVAL_SECONDS = 600  # 10 minutes

# One SYSTEM_ALERT per capture-gap event (not per tick); a clean tick
# re-arms it so a future distinct gap alerts again.
_GAP_DEDUP_KEY = "approval_records_capture_gap"


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
        autorebase: PRAutoRebase | None = None,
    ) -> None:
        super().__init__(worker_name="merge_state_watcher", config=config, deps=deps)
        hitl_label = (config.hitl_label or ["hydraflow-hitl"])[0]
        # #11595: the auto-rebase actuator rides this loop (no new loop
        # wiring). Always constructed — arming is the LIVE
        # ``pr_autorebase_enabled`` flag (default OFF), read per attempt, so
        # the operator can flip it in the settings screen without a restart.
        self._watcher = MergeStateWatcher(
            prs=prs,
            hitl_label=hitl_label,
            autorebase=(
                autorebase
                if autorebase is not None
                else PRAutoRebase(config=config, prs=prs)
            ),
        )
        self._approvals = (
            approval_reconciler
            if approval_reconciler is not None
            else ApprovalRecordReconciler(config)
        )
        self._gap_dedup = DedupStore(
            "approval_capture_gap",
            config.data_root / "dedup" / "approval_capture_gap.json",
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
        await self._alert_on_capture_gap(approvals)
        return {**stats, "approvals": approvals}

    async def _alert_on_capture_gap(self, approvals: dict[str, Any]) -> None:
        """Surface a capture-gap tick loudly (one alert per gap event).

        The reconciler already chained the ``capture_gap`` marker — this is
        the operator-facing signal. Dedup keeps it to one SYSTEM_ALERT per
        gap event; a clean tick re-arms it.
        """
        if approvals.get("capture_gap_risk"):
            if _GAP_DEDUP_KEY in self._gap_dedup.get():
                return
            self._gap_dedup.add(_GAP_DEDUP_KEY)
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "kind": "approval_records_capture_gap",
                        "worker": self._worker_name,
                        "message": (
                            "Approval-record scan window has no overlap with "
                            "the recorded stream — merges may have passed the "
                            "horizon unrecorded; a capture_gap marker was "
                            "chained to the evidence stream."
                        ),
                    },
                )
            )
        elif _GAP_DEDUP_KEY in self._gap_dedup.get():
            self._gap_dedup.set_all(self._gap_dedup.get() - {_GAP_DEDUP_KEY})
