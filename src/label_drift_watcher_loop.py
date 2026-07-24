"""LabelDriftWatcherLoop — periodic detect-and-reconcile of cross-entity
issue/PR label drift.

Per ADR-0088. The loop scans for drift via :meth:`PRPort.find_label_drift`
and reconciles each pair by per-entity ``swap_pipeline_labels`` calls
(mirroring the Phase D split-call pattern: issue gets one label, PR gets
``hydraflow-review``).

Pattern reference: ``src/memory_backlog_loop.py`` (canonical caretaker
loop). Same shape: tick logic in ``_do_work``, kwargs-only constructor,
ADR-0049 in-body kill-switch gate via ``self._enabled_cb``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import (  # noqa: TCH001
    ClosedStageLabelDrift,
    LabelDrift,
    WorkCycleResult,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from ports import PRPort

logger = logging.getLogger("hydraflow.label_drift_watcher_loop")


class LabelDriftWatcherLoop(BaseBackgroundLoop):
    """Periodic scan for cross-entity label drift; reconcile via two
    ``swap_pipeline_labels`` calls (issue target may differ from PR target
    across stages).
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="label_drift_watcher",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._prs = pr_manager

    def _get_default_interval(self) -> int:
        return self._config.label_drift_watcher_interval

    async def _do_work(self) -> WorkCycleResult:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.label_drift_watcher_loop_enabled:
            return {"status": "config_disabled"}

        drift = await self._prs.find_label_drift()
        reconciled = 0
        for d in drift:
            try:
                await self._reconcile(d)
                reconciled += 1
            except Exception:
                logger.warning(
                    "label_drift_watcher: reconcile failed for issue #%d / PR #%d",
                    d.issue,
                    d.pr,
                    exc_info=True,
                )
        result: WorkCycleResult = {"detected": len(drift), "reconciled": reconciled}

        # Caretaker check (#10394): a CLOSED issue that still carries an
        # active pipeline-stage label would be re-dispatched by a label-scan
        # work-picker. PRManager.close_issue strips these on every
        # HydraFlow-initiated close, but a GitHub-native ``Closes #N``
        # auto-close bypasses that path — this is the belt-and-suspenders
        # backstop. Keys are added only when something is found so the
        # no-op tick shape (``{detected, reconciled}``) is unchanged.
        closed_stale = await self._prs.find_closed_stage_labeled_issues()
        if closed_stale:
            stripped = 0
            for cd in closed_stale:
                try:
                    await self._strip_closed_stage_labels(cd)
                    stripped += 1
                except Exception:
                    logger.warning(
                        "label_drift_watcher: failed to strip stale stage "
                        "labels from closed issue #%d",
                        cd.issue,
                        exc_info=True,
                    )
            result["closed_stale_detected"] = len(closed_stale)
            result["closed_stale_stripped"] = stripped
        return result

    async def _strip_closed_stage_labels(self, cd: ClosedStageLabelDrift) -> None:
        """Remove the stale pipeline-stage labels from a closed issue (#10394)."""
        for lbl in cd.stale_labels:
            await self._prs.remove_label(cd.issue, lbl)
        labels_md = ", ".join(f"`{lbl}`" for lbl in cd.stale_labels)
        await self._prs.post_comment(
            cd.issue,
            (
                f"**LabelDriftWatcher** stripped stale pipeline-stage "
                f"label(s) {labels_md} from this CLOSED issue — a leftover "
                f"stage label re-dispatches already-shipped work (#10394).\n\n"
                "---\n*Automated by HydraFlow Label Drift Watcher (ADR-0088)*"
            ),
        )
        logger.info(
            "label_drift_watcher: stripped %d stale stage label(s) from "
            "closed issue #%d",
            len(cd.stale_labels),
            cd.issue,
        )

    async def _reconcile(self, d: LabelDrift) -> None:
        """Apply per-stage labels mirroring Phase D's split-call pattern.

        - ``pr_ahead_of_issue``: issue lags at ready/plan; pull it forward
          to ``hydraflow-review`` to match the PR's stage. PR label stays.
        - ``pr_at_pre_pr_stage``: PR has commits but a pre-PR label
          (ready/plan/find); push the PR forward to ``hydraflow-review``.
          Issue label stays.
        - ``escalated_with_resolving_pr``: issue carries the diagnostic_loop
          escalation pair (``hitl-escalation`` + ``diagnose-failed``) while
          an open, CI-green PR already resolves it — clear the escalation
          labels so it stops re-triggering auto-agent dispatch (#10260).
          The issue keeps its ``hydraflow-hitl`` pipeline label, so it stays
          visible in the HITL queue. Scoped to this exact label pairing —
          see :class:`models.LabelDrift`.
        """
        if d.kind == "pr_ahead_of_issue":
            await self._prs.swap_pipeline_labels(d.issue, "hydraflow-review")
            moved_clause = (
                f"Issue #{d.issue} moved from `{d.issue_label}` to "
                f"`hydraflow-review` to match PR #{d.pr} (which was already "
                f"at `{d.pr_label}`)."
            )
        elif d.kind == "pr_at_pre_pr_stage":
            await self._prs.swap_pipeline_labels(d.pr, "hydraflow-review")
            moved_clause = (
                f"PR #{d.pr} moved from `{d.pr_label}` to `hydraflow-review` "
                f"to match issue #{d.issue} (which was already at "
                f"`{d.issue_label}`)."
            )
        else:  # escalated_with_resolving_pr
            await self._prs.remove_label(d.issue, "hitl-escalation")
            await self._prs.remove_label(d.issue, "diagnose-failed")
            moved_clause = (
                f"Issue #{d.issue} escalation labels (`{d.issue_label}`) "
                f"cleared — PR #{d.pr} already resolves it with passing CI."
            )

        await self._prs.post_comment(
            d.issue,
            (
                f"**LabelDriftWatcher** reconciled label drift "
                f"(kind=`{d.kind}`). {moved_clause}\n\n"
                "---\n*Automated by HydraFlow Label Drift Watcher (ADR-0088)*"
            ),
        )
        logger.info(
            "label_drift_watcher: reconciled issue #%d / PR #%d (kind=%s)",
            d.issue,
            d.pr,
            d.kind,
        )
