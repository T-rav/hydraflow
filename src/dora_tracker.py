"""DORA metrics tracker — computes the five DORA metrics as rolling windows.

Reads from StateTracker and EventBus history to compute deployment frequency,
lead time, change failure rate, recovery time, and rework rate.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from events import EventBus, HydraFlowEvent
    from release_decision import ReleasePolicy
    from state import StateTracker

logger = logging.getLogger("hydraflow.dora")


class DORASnapshot(BaseModel):
    """Point-in-time DORA metrics snapshot."""

    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    deployment_frequency: float = Field(
        default=0.0, description="Merges per day (rolling 7d)"
    )
    lead_time_seconds: float = Field(
        default=0.0, description="Median issue-open to PR-merged seconds (rolling 7d)"
    )
    change_failure_rate: float = Field(
        default=0.0, description="% of merges causing HITL/revert (rolling 30d)"
    )
    recovery_time_seconds: float = Field(
        default=0.0, description="Median failure-to-fix seconds (rolling 30d)"
    )
    rework_rate: float = Field(
        default=0.0, description="% of issues re-opened after merge (rolling 30d)"
    )


class DORATracker:
    """Computes DORA metrics from state and event history."""

    def __init__(
        self,
        state: StateTracker,
        event_bus: EventBus,
        *,
        short_window_days: int = 7,
        long_window_days: int = 30,
    ) -> None:
        self._state = state
        self._bus = event_bus
        self._short_window = timedelta(days=short_window_days)
        self._long_window = timedelta(days=long_window_days)

    def snapshot(self) -> DORASnapshot:
        """Compute current DORA metrics from event history."""
        now = datetime.now(UTC)
        history = self._bus.get_history()

        merge_events = self._filter_events(
            history, "merge_update", now - self._short_window
        )
        hitl_events = self._filter_events(
            history, "hitl_escalation", now - self._long_window
        )
        all_merges_long = self._filter_events(
            history, "merge_update", now - self._long_window
        )

        # Deployment frequency: merges per day over short window
        merge_count = sum(1 for e in merge_events if e.data.get("status") == "merged")
        deploy_freq = merge_count / max(self._short_window.days, 1)

        # Lead time: median of issue-open to merge timestamps
        lead_times = self._compute_lead_times(merge_events)
        lead_time = _median(lead_times) if lead_times else 0.0

        # Change failure rate: HITL escalations / total merges (long window)
        total_merges_long = sum(
            1 for e in all_merges_long if e.data.get("status") == "merged"
        )
        hitl_count = len(hitl_events)
        cfr = hitl_count / max(total_merges_long, 1)

        # Recovery time: median of HITL escalation to resolution
        recovery_times = self._compute_recovery_times(hitl_events, history)
        recovery = _median(recovery_times) if recovery_times else 0.0

        # Rework rate: issues re-labeled after merge / total merges
        rework_count = self._count_rework_events(history, now - self._long_window)
        rework_rate = rework_count / max(total_merges_long, 1)

        return DORASnapshot(
            deployment_frequency=round(deploy_freq, 3),
            lead_time_seconds=round(lead_time, 1),
            change_failure_rate=round(min(cfr, 1.0), 3),
            recovery_time_seconds=round(recovery, 1),
            rework_rate=round(min(rework_rate, 1.0), 3),
        )

    def is_healthy(self, policy: ReleasePolicy) -> bool:
        """Check whether current DORA metrics are within healthy bounds."""
        snap = self.snapshot()
        return (
            snap.rework_rate <= policy.max_rework_rate
            and snap.change_failure_rate <= policy.max_change_failure_rate
        )

    def health_dict(self) -> dict[str, float]:
        """Return DORA metrics as a plain dict for the decision engine."""
        snap = self.snapshot()
        return {
            "deployment_frequency": snap.deployment_frequency,
            "lead_time_seconds": snap.lead_time_seconds,
            "change_failure_rate": snap.change_failure_rate,
            "recovery_time_seconds": snap.recovery_time_seconds,
            "rework_rate": snap.rework_rate,
        }

    # --- Internal helpers ---

    @staticmethod
    def _filter_events(
        history: list[HydraFlowEvent],
        event_type: str,
        since: datetime,
    ) -> list[HydraFlowEvent]:
        result: list[HydraFlowEvent] = []
        for e in history:
            if e.type.value != event_type:
                continue
            try:
                ts = datetime.fromisoformat(e.timestamp)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts >= since:
                    result.append(e)
            except (ValueError, TypeError):
                continue
        return result

    @staticmethod
    def _compute_lead_times(
        merge_events: list[HydraFlowEvent],
    ) -> list[float]:
        times: list[float] = []
        for e in merge_events:
            if e.data.get("status") != "merged":
                continue
            created = e.data.get("issue_created_at")
            if not created:
                continue
            try:
                ts_created = datetime.fromisoformat(str(created))
                ts_merged = datetime.fromisoformat(e.timestamp)
                if ts_created.tzinfo is None:
                    ts_created = ts_created.replace(tzinfo=UTC)
                if ts_merged.tzinfo is None:
                    ts_merged = ts_merged.replace(tzinfo=UTC)
                delta = (ts_merged - ts_created).total_seconds()
                if delta > 0:
                    times.append(delta)
            except (ValueError, TypeError):
                continue
        return times

    @staticmethod
    def _compute_recovery_times(
        hitl_events: list[HydraFlowEvent],
        all_history: list[HydraFlowEvent],
    ) -> list[float]:
        times: list[float] = []
        resolved_issues: dict[int, str] = {}
        for e in all_history:
            if e.data.get("status") == "hitl_resolved":
                issue = e.data.get("issue")
                if isinstance(issue, int):
                    resolved_issues[issue] = e.timestamp

        for e in hitl_events:
            issue = e.data.get("issue")
            if not isinstance(issue, int):
                continue
            resolved_ts = resolved_issues.get(issue)
            if not resolved_ts:
                continue
            try:
                ts_escalation = datetime.fromisoformat(e.timestamp)
                ts_resolved = datetime.fromisoformat(resolved_ts)
                if ts_escalation.tzinfo is None:
                    ts_escalation = ts_escalation.replace(tzinfo=UTC)
                if ts_resolved.tzinfo is None:
                    ts_resolved = ts_resolved.replace(tzinfo=UTC)
                delta = (ts_resolved - ts_escalation).total_seconds()
                if delta > 0:
                    times.append(delta)
            except (ValueError, TypeError):
                continue
        return times

    @staticmethod
    def _count_rework_events(
        history: list[HydraFlowEvent],
        since: datetime,
    ) -> int:
        count = 0
        for e in history:
            try:
                ts = datetime.fromisoformat(e.timestamp)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < since:
                    continue
            except (ValueError, TypeError):
                continue
            if (
                e.data.get("rework") is True
                or e.data.get("relabeled_after_merge") is True
            ):
                count += 1
        return count


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return s[mid]
