"""Cost-budget alert helpers (spec §4.11 point 6).

Two free functions callable from their respective hook sites:

* :func:`check_daily_budget` — called from :class:`ReportIssueLoop._do_work`
  when the report queue is empty. Files one hydraflow-find issue per UTC
  calendar day when the last-24h total crosses ``config.daily_cost_budget_usd``.
* :func:`check_issue_cost` — called from :meth:`PRManager.merge_pr` on
  successful merge. Files one hydraflow-find issue per issue number when
  the issue's final total cost crosses ``config.issue_cost_alert_usd``.

Both functions:

- Return immediately if the corresponding config field is ``None``.
- Dedup via the injected :class:`DedupStore` (no write if key already present).
- Publish an accompanying ``EventType.SYSTEM_ALERT`` so dashboard banners
  surface the alert without waiting for find-triage to pick up the issue.
- Never raise. Errors are logged at WARNING and swallowed — a broken alert
  must not abort the calling loop tick or the merge call.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from events import EventBus
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.cost_budget_alerts")


async def check_daily_budget(
    config: HydraFlowConfig,
    *,
    pr_manager: PRManager,
    dedup: DedupStore,
    event_bus: EventBus,
    total_cost_24h: float,
    now: datetime | None = None,
) -> None:
    """File a hydraflow-find issue if the 24h cost exceeds the daily budget.

    No-op when ``config.daily_cost_budget_usd`` is ``None``. Dedupes per UTC
    calendar day so the alert fires at most once per day even if the loop
    sweeps multiple times.
    """
    threshold = config.daily_cost_budget_usd
    if threshold is None:
        return
    if total_cost_24h < threshold:
        return
    now = now or datetime.now(UTC)
    day_key = f"cost_budget:{now.strftime('%Y-%m-%d')}"
    try:
        if day_key in dedup.get():
            logger.info("Daily-budget alert already filed for %s", day_key)
            return
    except Exception:
        logger.warning("DedupStore.get failed in check_daily_budget", exc_info=True)
        return

    labels = list(config.find_label or ["hydraflow-find"])
    if "cost-budget-exceeded" not in labels:
        labels = [*labels, "cost-budget-exceeded"]

    title = (
        f"HITL: daily cost budget exceeded — "
        f"${total_cost_24h:.2f} on {now.strftime('%Y-%m-%d')}"
    )
    body = (
        f"The HydraFlow factory spent ${total_cost_24h:.2f} in the last 24h, "
        f"which exceeds the configured `daily_cost_budget_usd` of "
        f"${threshold:.2f}.\n\n"
        f"This issue was filed automatically by `ReportIssueLoop` via "
        f"`cost_budget_alerts.check_daily_budget` (spec §4.11 point 6).\n\n"
        f"**Next steps:** inspect `/api/diagnostics/cost/rolling-24h` + "
        f"`/api/diagnostics/loops/cost` in the Factory Cost sub-tab to "
        f"identify the driver, then decide whether to raise the budget, "
        f"disable a loop, or close this issue as acknowledged.\n\n"
        f"Dedup key: `{day_key}`."
    )
    try:
        issue_number = await pr_manager.create_issue(title, body, labels)
    except Exception:
        logger.warning("Failed to file daily-budget alert", exc_info=True)
        return
    if issue_number <= 0:
        logger.warning("create_issue returned %d; not marking dedup", issue_number)
        return
    try:
        dedup.add(day_key)
    except Exception:
        logger.warning("DedupStore.add failed after filing", exc_info=True)

    try:
        from events import EventType, HydraFlowEvent  # noqa: PLC0415

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                data={
                    "kind": "cost_budget_exceeded",
                    "threshold_usd": threshold,
                    "observed_usd": round(total_cost_24h, 2),
                    "issue_number": issue_number,
                    "dedup_key": day_key,
                },
            )
        )
    except Exception:
        logger.warning("SYSTEM_ALERT publish failed", exc_info=True)


async def check_issue_cost(
    config: HydraFlowConfig,
    *,
    pr_manager: PRManager,
    dedup: DedupStore,
    event_bus: EventBus,
    issue_number: int,
    cost_usd: float,
) -> None:
    """File a hydraflow-find issue if a merged issue's cost exceeds the budget.

    No-op when ``config.issue_cost_alert_usd`` is ``None``. Dedupes per
    issue number so the alert fires at most once per issue.
    """
    threshold = config.issue_cost_alert_usd
    if threshold is None:
        return
    if cost_usd < threshold:
        return
    key = f"issue_cost:{issue_number}"
    try:
        if key in dedup.get():
            logger.info("Issue-cost alert already filed for %s", key)
            return
    except Exception:
        logger.warning("DedupStore.get failed in check_issue_cost", exc_info=True)
        return

    labels = list(config.find_label or ["hydraflow-find"])
    if "issue-cost-spike" not in labels:
        labels = [*labels, "issue-cost-spike"]

    title = f"HITL: issue #{issue_number} cost spike — ${cost_usd:.2f}"
    body = (
        f"Issue #{issue_number} merged with a final cost of "
        f"${cost_usd:.2f}, which exceeds `issue_cost_alert_usd` of "
        f"${threshold:.2f}.\n\n"
        f"This issue was filed automatically by `PRManager.merge_pr` via "
        f"`cost_budget_alerts.check_issue_cost` (spec §4.11 point 6).\n\n"
        f"**Next steps:** inspect the per-issue waterfall at "
        f"`/api/diagnostics/issue/{issue_number}/waterfall` to identify "
        f"the expensive phase.\n\nDedup key: `{key}`."
    )
    try:
        filed = await pr_manager.create_issue(title, body, labels)
    except Exception:
        logger.warning("Failed to file issue-cost alert", exc_info=True)
        return
    if filed <= 0:
        return
    try:
        dedup.add(key)
    except Exception:
        logger.warning("DedupStore.add failed after filing", exc_info=True)

    try:
        from events import EventType, HydraFlowEvent  # noqa: PLC0415

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                data={
                    "kind": "issue_cost_spike",
                    "threshold_usd": threshold,
                    "observed_usd": round(cost_usd, 2),
                    "issue_number": issue_number,
                    "alert_issue": filed,
                    "dedup_key": key,
                },
            )
        )
    except Exception:
        logger.warning("SYSTEM_ALERT publish failed", exc_info=True)
