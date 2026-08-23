"""Bounded parameter auto-adjustment of ``HealthMonitorLoop``.

Extracted VERBATIM from ``src/health_monitor_loop.py`` (god-class
decomposition, Refs #11547) as a mixin.

One concern: the control action — applying an in-bounds session-scoped
adjustment from the rule table, and the delayed verification that decides
whether the adjustment helped, hurt, or did nothing.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import HydraFlowConfig

from ._common import (
    _FIRST_PASS_HIGH,
    _FIRST_PASS_LOW,
    ADJUSTMENT_RULES,
    TUNABLE_BOUNDS,
    PendingAdjustment,
    TrendMetrics,
)
from ._decisions import (
    _next_decision_id,
    _update_decision,
    _write_decision,
)

if TYPE_CHECKING:
    from ports import ObservabilityPort


logger = logging.getLogger("hydraflow.health_monitor_loop")


class HealthMonitorAdjustmentMixin:
    """Bounded parameter auto-adjustment of ``HealthMonitorLoop``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``HealthMonitorLoop.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _decisions_dir: Path
    _obs: ObservabilityPort | None
    _pending: list[PendingAdjustment]
    _verification_window: int

    if TYPE_CHECKING:

        @property
        def _outcomes_path(self) -> Path: ...  # provided by _loop

    def _apply_adjustments(self, metrics: TrendMetrics) -> int:
        """Apply ADJUSTMENT_RULES against active conditions. Returns count applied."""
        active = set(metrics.active_conditions())
        if not active:
            return 0

        applied = 0
        for condition_key, parameter, step in ADJUSTMENT_RULES:
            if condition_key not in active:
                continue
            try:
                current_val = int(getattr(self._config, parameter))
                lo, hi = TUNABLE_BOUNDS[parameter]
                new_val = current_val + step
                new_val = max(lo, min(hi, new_val))
                if new_val == current_val:
                    continue

                object.__setattr__(self._config, parameter, new_val)

                decision_id = _next_decision_id(self._decisions_dir)
                evidence = (
                    f"{metrics.total_outcomes - int(metrics.first_pass_rate * metrics.total_outcomes)}"
                    f"/{metrics.total_outcomes} issues needed retry"
                )
                record: dict[str, Any] = {
                    "decision_id": decision_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "type": "auto_adjust",
                    "parameter": parameter,
                    "before": current_val,
                    "after": new_val,
                    "reason": (
                        f"{condition_key.replace('_', ' ')} "
                        f"{metrics.first_pass_rate:.2f} "
                        f"{'below' if step > 0 else 'above'} "
                        f"{_FIRST_PASS_LOW if step > 0 else _FIRST_PASS_HIGH} threshold"
                    ),
                    "evidence_summary": evidence,
                    "outcome_verified": None,
                }
                _write_decision(self._decisions_dir, record)
                logger.info(
                    "Auto-adjusted %s: %d → %d (%s)",
                    parameter,
                    current_val,
                    new_val,
                    condition_key,
                )
                if self._obs is not None:
                    self._obs.breadcrumb(
                        "memory.auto_adjust",
                        f"Adjusted {parameter}: {current_val} → {new_val}",
                        level="warning",
                        parameter=parameter,
                        before=current_val,
                        after=new_val,
                        reason=record["reason"],
                    )

                self._pending.append(
                    PendingAdjustment(
                        decision_id=decision_id,
                        parameter=parameter,
                        before=current_val,
                        after=new_val,
                        metric_name="first_pass_rate",
                        metric_value=metrics.first_pass_rate,
                        outcomes_at_adjustment=metrics.total_outcomes,
                    )
                )
                applied += 1
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Auto-adjustment failed for parameter %s",
                    parameter,
                    exc_info=True,
                )

        return applied

    def _count_outcomes_since(self, since_count: int) -> int:
        """Return total outcomes accumulated since a prior snapshot count."""
        try:
            if not self._outcomes_path.exists():
                return 0
            lines = self._outcomes_path.read_text(encoding="utf-8").strip().splitlines()
            return max(0, len(lines) - since_count)
        except Exception:  # noqa: BLE001
            return 0

    def _verify_pending_adjustments(self, metrics: TrendMetrics) -> None:
        """Check if any pending adjustments have enough follow-on outcomes for verification."""
        still_pending: list[PendingAdjustment] = []
        for adj in self._pending:
            try:
                new_outcomes = self._count_outcomes_since(adj.outcomes_at_adjustment)
                if new_outcomes < self._verification_window:
                    still_pending.append(adj)
                    continue

                # Enough outcomes — evaluate
                new_metric_val = metrics.first_pass_rate
                old_metric_val = adj.metric_value
                improved_direction = adj.after > adj.before  # larger = more attempts

                if improved_direction:
                    # We increased attempts hoping to improve first_pass_rate
                    improved = new_metric_val > old_metric_val + 0.05
                    worsened = new_metric_val < old_metric_val - 0.05
                else:
                    # We reduced attempts hoping it stays high
                    improved = new_metric_val >= old_metric_val - 0.05
                    worsened = new_metric_val < old_metric_val - 0.1

                if worsened:
                    # Revert the adjustment
                    try:
                        object.__setattr__(self._config, adj.parameter, adj.before)
                        logger.warning(
                            "Reverting auto-adjustment %s for %s: metric worsened"
                            " (%.2f → %.2f)",
                            adj.decision_id,
                            adj.parameter,
                            old_metric_val,
                            new_metric_val,
                        )
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "Failed to revert %s for %s",
                            adj.decision_id,
                            adj.parameter,
                            exc_info=True,
                        )
                    outcome_verified = "reverted"
                elif improved:
                    outcome_verified = "improved"
                else:
                    outcome_verified = "neutral"

                _update_decision(
                    self._decisions_dir,
                    adj.decision_id,
                    {"outcome_verified": outcome_verified},
                )
                logger.info(
                    "Decision %s verified as %s",
                    adj.decision_id,
                    outcome_verified,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Verification check failed for decision %s",
                    adj.decision_id,
                    exc_info=True,
                )
                still_pending.append(adj)

        self._pending = still_pending
