"""Background worker loop — FailOpenMonitorLoop (#10371).

A caretaker (ADR-0029, **Pattern B**) that watches the fail-visible dispatch
ledger written by ``PostVerifyAdvisor`` (``judge_independence`` module,
``<data_root>/diagnostics/fail_open_ledger.jsonl``). Each tick it reads the
ledger, buckets fail-open events per day, and applies a Shewhart c-chart
control limit (``cbar + 3*sqrt(cbar)``) to the daily count series. When the
latest day breaches the control limit it files ONE ``hydraflow-find`` issue for
human triage — "sampling effort follows observed variation": a spike in silent
fail-opens is a signal that the evidence path is degrading and a human should
look.

Pattern B, deliberately unlike a fix-PR actuator: this loop senses and reports,
it never reverts, never blocks a merge, never opens a fix PR (the ledger + the
advisor's own fail-closed logic already handle the per-event disposition;
ADR-0101's ``DisturbanceDampenerLoop`` is the Pattern-A contrast). It mirrors
``ErosionMetricsLoop``'s bounded-per-tick filing discipline.

**No cursor state.** The control-limit computation is a pure function of the
whole (bounded) ledger, so there is no per-tick range to advance — a
``DedupStore`` keyed by the breach day is the only persistence, guarding
against re-filing the same day's breach after a retry or process restart.

**Conservative by default.** ``fail_open_rate_breach`` requires several days of
history before a control limit can fire (a limit computed from one or two
points is noise), so a fresh install is quiet until enough ledger accrues.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import judge_independence as ji
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from exception_classify import reraise_on_credit_or_bug
from loop_fitness import FitnessContext, FitnessKind, LoopFitness

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dedup_store import DedupStore
    from ports import PRPort

logger = logging.getLogger("hydraflow.fail_open_monitor")

_ISSUE_LABELS = ["hydraflow-find", "judge-independence"]


def breach_fingerprint(day: str) -> str:
    """Stable dedup key for one day's fail-open control-limit breach."""
    return f"fail_open_rate_breach:{day}"


def _latest_day(records: list[dict[str, Any]]) -> str | None:
    counts = ji.daily_fail_open_counts(records)
    return max(counts) if counts else None


def _render_breach(
    *, day: str, ucl: float, latest_count: int, metrics: dict[str, Any]
) -> tuple[str, str]:
    """Render (title, body) for a fail-open rate control-limit breach."""
    title = (
        f"Fail-open rate breach: {latest_count} judge fail-opens on {day} "
        f"exceeds control limit {ucl:.1f}"
    )
    by_family = metrics.get("disagreement_by_family", {}) or {}
    fam_rows = (
        "\n".join(
            f"| {fam} | {v.get('verdicts', 0)} | {v.get('dissents', 0)} |"
            for fam, v in sorted(by_family.items())
        )
        or "| (none) | 0 | 0 |"
    )
    body = (
        "## Evidence (FailOpenMonitorLoop, automated — #10371)\n\n"
        "A Shewhart c-chart control limit on the post-verification fail-open "
        "ledger has been breached: the latest day's count of judge-unavailable "
        "→ work-passed events is above ``cbar + 3*sqrt(cbar)`` computed over the "
        "prior days. A fail-open is not an error in itself, but a *spike* in "
        "silent fail-opens means the evidence path is degrading — the reviews "
        "that did happen carried less independent scrutiny than the dashboards "
        "imply.\n\n"
        f"| metric | value |\n|---|---|\n"
        f"| breach day | `{day}` |\n"
        f"| fail-opens (day) | {latest_count} |\n"
        f"| control limit (UCL) | {ucl:.2f} |\n"
        f"| fail-open total (all time) | {metrics.get('fail_open_total', 0)} |\n"
        f"| independence-unavailable total | "
        f"{metrics.get('independence_unavailable_total', 0)} |\n"
        f"| classed verdicts | {metrics.get('classed_verdicts', 0)} |\n"
        f"| % carrying independent verdict | {metrics.get('pct_independent', 0)} |\n\n"
        "### Disagreement by family\n\n"
        "| family | independent verdicts | dissents |\n|---|---|---|\n"
        f"{fam_rows}\n\n"
        "Pattern B outer-loop finding: filed for human triage. Look at the "
        "recent fail-open ledger rows (`diagnostics/fail_open_ledger.jsonl`) to "
        "see which lens/surface degraded and why (infra flake vs. a real "
        "judge-availability regression).\n"
    )
    return title, body


class FailOpenMonitorLoop(BaseBackgroundLoop):
    """Files a hydraflow-find when the fail-open ledger's rate breaches its limit.

    Read + issue-filing only — never edits code, never opens a PR, never blocks
    a merge (the per-event disposition lives in the advisor, #10371).
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="fail_open_monitor", config=config, deps=deps)
        self._prs = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.fail_open_monitor_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Read-only sensor: files evidence issues, owns no proposal/acceptance
        # lifecycle to score — HOUSEKEEPING per ADR-0093, mirrors
        # erosion_metrics_loop.py / gate_health_loop.py.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.fail_open_monitor_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None

        ledger = ji.ledger_path_for(self._config)
        records = ji.read_records(ledger)
        breached, ucl, latest_count = ji.fail_open_rate_breach(records)
        if not breached:
            return {"status": "ok", "breached": False, "records": len(records)}

        day = _latest_day(records)
        if day is None:  # pragma: no cover - breach implies a latest day exists
            return {"status": "ok", "breached": False, "records": len(records)}

        filed = await self._file_breach(day, ucl, latest_count, records)
        return {
            "status": "ok",
            "breached": True,
            "day": day,
            "ucl": round(ucl, 2),
            "latest_count": latest_count,
            "filed": filed,
        }

    async def _file_breach(
        self,
        day: str,
        ucl: float,
        latest_count: int,
        records: list[dict[str, Any]],
    ) -> int:
        """File one deduped hydraflow-find for a breach day; return filed count."""
        fingerprint = breach_fingerprint(day)
        seen = self._dedup.get()
        if fingerprint in seen:
            return 0
        metrics = ji.calibration_metrics(records)
        title, body = _render_breach(
            day=day, ucl=ucl, latest_count=latest_count, metrics=metrics
        )
        try:
            await self._prs.create_issue(title, body, labels=_ISSUE_LABELS)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "FailOpenMonitor: failed to file breach finding %s",
                fingerprint,
                exc_info=True,
            )
            return 0
        self._dedup.set_all(seen | {fingerprint})
        logger.info("FailOpenMonitor: filed fail-open rate breach %s", fingerprint)
        return 1
