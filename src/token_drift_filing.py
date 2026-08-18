"""Token-drift filing actuator (#11442).

Turns the read-only drift verdict — produced by :mod:`token_drift` (the
minimal, contract-conforming stand-in for #11441's salvage engine) — into
ONE ``hydraflow-find`` issue per drifting source per ISO week. Mirrors
``cost_budget_alerts.check_daily_budget`` exactly: a free async function with
a calendar-period dedup key, injected ``pr_manager``/``dedup``/``event_bus``,
never raising, called from an existing loop's ``_do_work``
(``ErosionMetricsLoop`` — see its module docstring for the shared cadence).

Dedup key = ``source`` + ISO week (``datetime.isocalendar()``, NOT
``.year``/``.isoweek()`` by hand — a Dec 31/Jan 1 boundary can fall in the
same ISO week of a DIFFERENT calendar year). A sustained drift on one source
files once per ISO week; a second source drifting the same week files its
own issue; the same source drifting again the FOLLOWING ISO week files again.

No automatic prompt pruning, no config changes — filing IS the actuator
(stillness principles, ADR-0120): a human decides what to do about a drifting
source, this module only makes sure they hear about it once.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from token_drift import TokenDriftVerdict, compute_token_drift

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from events import EventBus
    from ports import PRPort

logger = logging.getLogger("hydraflow.token_drift_filing")

_DRIFT_LABEL = "token-drift"


def weekly_dedup_key(source: str, when: datetime) -> str:
    """Dedup key ``token_drift:<source>:<ISO year>-W<ISO week>``.

    Uses ``when.isocalendar()`` end to end — never ``when.year`` — so a
    timestamp that falls in ISO week 53 spanning a Dec 31 / Jan 1 calendar
    boundary keys to the SAME week regardless of which side of midnight it
    lands on.
    """
    iso_year, iso_week, _ = when.isocalendar()
    return f"token_drift:{source}:{iso_year}-W{iso_week:02d}"


def render_drift_issue(
    verdict: TokenDriftVerdict, *, dedup_key: str
) -> tuple[str, str]:
    """Render (title, body) for one token-drift verdict, citing the evidence."""
    title = (
        f"HITL: token-share drift on `{verdict.source}` — "
        f"{verdict.before_share:.1%} -> {verdict.after_share:.1%} "
        f"({verdict.sigma:.1f}sigma)"
    )
    body = (
        f"`{verdict.source}`'s share of fleet token spend moved from "
        f"{verdict.before_share:.1%} to {verdict.after_share:.1%} "
        f"({verdict.sigma:.2f} standard errors above its ADR-0133 widened "
        "control band) within one trailing measurement window.\n\n"
        "| metric | value |\n|---|---|\n"
        f"| source | `{verdict.source}` |\n"
        f"| before share | {verdict.before_share:.1%} |\n"
        f"| after share | {verdict.after_share:.1%} |\n"
        f"| sigma | {verdict.sigma:.2f} |\n\n"
        "This issue was filed automatically by `ErosionMetricsLoop` via "
        "`token_drift_filing.check_token_drift` (#11442). Filing is the "
        "actuator — no automatic prompt pruning or config change was made; "
        "a human decides whether this growth is intentional.\n\n"
        f"**Next steps:** inspect `/api/diagnostics/token-report` to see the "
        "current per-source token report and confirm whether this is a "
        "genuine regression or expected (e.g. a new phase source).\n\n"
        f"Dedup key: `{dedup_key}`."
    )
    return title, body


async def check_token_drift(
    config: HydraFlowConfig,
    *,
    pr_manager: PRPort,
    dedup: DedupStore,
    event_bus: EventBus,
    verdicts: list[TokenDriftVerdict],
    now: datetime | None = None,
) -> int:
    """File one hydraflow-find issue per drifting source, deduped per ISO week.

    Returns the number of issues filed this call. Never raises: every port
    failure (dedup read/write, ``create_issue``, event publish) is logged at
    WARNING and swallowed, mirroring ``cost_budget_alerts`` — a broken alert
    must not abort the caller's tick.
    """
    now = now or datetime.now(UTC)
    filed = 0
    for verdict in verdicts:
        if not verdict.is_drift:
            continue
        key = weekly_dedup_key(verdict.source, now)
        try:
            seen = dedup.get()
        except Exception:
            logger.warning("DedupStore.get failed in check_token_drift", exc_info=True)
            continue
        if key in seen:
            logger.info("Token-drift alert already filed for %s", key)
            continue

        labels = list(config.find_label or ["hydraflow-find"])
        if _DRIFT_LABEL not in labels:
            labels = [*labels, _DRIFT_LABEL]
        title, body = render_drift_issue(verdict, dedup_key=key)
        try:
            issue_number = await pr_manager.create_issue(title, body, labels=labels)
        except Exception:
            logger.warning(
                "Failed to file token-drift alert for %s", key, exc_info=True
            )
            continue
        if issue_number <= 0:
            logger.warning(
                "create_issue returned %d for %s; not marking dedup",
                issue_number,
                key,
            )
            continue
        try:
            dedup.add(key)
        except Exception:
            logger.warning("DedupStore.add failed after filing %s", key, exc_info=True)
        filed += 1
        logger.info("token_drift_filing: filed %s", key)

        try:
            from events import EventType, HydraFlowEvent  # noqa: PLC0415

            await event_bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "kind": "token_drift_detected",
                        "source": verdict.source,
                        "before_share": verdict.before_share,
                        "after_share": verdict.after_share,
                        "sigma": verdict.sigma,
                        "issue_number": issue_number,
                        "dedup_key": key,
                    },
                )
            )
        except Exception:
            logger.warning("SYSTEM_ALERT publish failed for %s", key, exc_info=True)
    return filed


async def run_token_drift_check(
    config: HydraFlowConfig,
    *,
    pr_manager: PRPort,
    dedup: DedupStore,
    event_bus: EventBus,
    now: datetime | None = None,
) -> int:
    """Load recent inference rows, compute drift verdicts, and file findings.

    The full telemetry -> engine -> actuator pipeline ``ErosionMetricsLoop``
    calls once per daily tick. Never raises: a telemetry load failure is
    logged and treated as "nothing to check" (returns 0) rather than
    propagating into the host loop's tick.
    """
    from prompt_telemetry import PromptTelemetry  # noqa: PLC0415

    try:
        rows = PromptTelemetry(config).load_inferences(limit=5000)
    except Exception:
        logger.warning(
            "Failed to load prompt telemetry for token-drift check", exc_info=True
        )
        return 0

    verdicts = compute_token_drift(rows)
    return await check_token_drift(
        config,
        pr_manager=pr_manager,
        dedup=dedup,
        event_bus=event_bus,
        verdicts=verdicts,
        now=now,
    )
