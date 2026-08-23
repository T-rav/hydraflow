"""Fleet-vitals sensing of ``HealthMonitorLoop``.

Extracted VERBATIM from ``src/health_monitor_loop.py`` (god-class
decomposition, Refs #11547) as a mixin.

One concern: the ADR-0133 fleet reading — open-issue count, change ledger,
band evaluation and the Sentry metric emission that carries it off-box.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import HydraFlowConfig
from events import EventType, HydraFlowEvent
from fleet_vitals import (
    ChangeEvent,
    FleetBands,
    FleetReading,
    FleetVitalsState,
)
from fleet_vitals import (
    evaluate as evaluate_fleet_vitals,
)
from subprocess_util import run_subprocess

from ._common import (
    TrendMetrics,
)

if TYPE_CHECKING:
    from events import EventBus
    from ports import ObservabilityPort, PRPort


logger = logging.getLogger("hydraflow.health_monitor_loop")


class HealthMonitorFleetVitalsMixin:
    """Fleet-vitals sensing of ``HealthMonitorLoop``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``HealthMonitorLoop.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _bus: EventBus
    _config: HydraFlowConfig
    _obs: ObservabilityPort | None
    _prs: PRPort | None

    async def _run_fleet_vitals(self, metrics: Any) -> None:
        """#11391 rungs 1-3 in SHADOW: evaluate bands, attach the mechanical
        change-ledger diagnosis, log + SYSTEM_ALERT the shadow proposal.

        Never actuates. State (hysteresis, one-alarm-per-episode) persists
        under the data path so restarts don't re-alarm an active episode.
        """

        if not self._config.fleet_vitals_enabled:
            return
        state_path = self._config.data_root / "fleet_vitals_state.json"
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        state = FleetVitalsState.from_dict(raw)
        reading = FleetReading(
            ts=datetime.now(UTC),
            hitl_rate=float(metrics.hitl_escalation_rate),
            first_pass_rate=float(metrics.first_pass_rate),
            # Idle gate (review BLOCKING): zero-outcome windows read
            # first_pass_rate=0.0 — quiet, not sick.
            run_count=int(getattr(metrics, "total_outcomes", 0)),
            open_issues=await self._fleet_open_issue_count(),
        )
        alarms = evaluate_fleet_vitals(
            state,
            reading,
            bands=FleetBands(
                hitl_rate_alarm=self._config.fleet_hitl_rate_alarm,
                hitl_rate_rearm=self._config.fleet_hitl_rate_rearm,
                first_pass_floor=self._config.fleet_first_pass_floor,
                board_growth_alarm=self._config.fleet_board_growth_alarm,
                confirm_windows=self._config.fleet_alarm_confirm_windows,
            ),
            changes=await self._fleet_change_ledger(),
        )
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(state.to_dict(), indent=2), encoding="utf-8"
            )
        except OSError:
            logger.warning("fleet-vitals state save failed", exc_info=True)
        for alarm in alarms:
            logger.warning(
                "FLEET ALARM [%s]: hitl_rate=%.2f first_pass_rate=%.2f "
                "(confirmed over %d windows). Suspects: %s. %s",
                alarm.band,
                alarm.reading.hitl_rate,
                alarm.reading.first_pass_rate,
                alarm.consecutive_breaches,
                "; ".join(f"{s.kind}:{s.ref} ({s.description})" for s in alarm.suspects)
                or "none in lookback",
                alarm.shadow_proposal,
            )
            if self._bus is not None:
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SYSTEM_ALERT,
                        data={
                            "kind": "fleet_vitals_alarm",
                            "source": "health_monitor",
                            # Banner convention (#11306 gotcha): severity
                            # 'warning' = advisory styling; message is the
                            # rendered body. Omitting both renders a blank
                            # CRITICAL banner.
                            "severity": "warning",
                            "message": (
                                f"Fleet vitals [{alarm.band}]: "
                                f"hitl_rate={alarm.reading.hitl_rate:.2f} "
                                f"first_pass_rate="
                                f"{alarm.reading.first_pass_rate:.2f}. "
                                f"{alarm.shadow_proposal}"
                            ),
                            "band": alarm.band,
                            "hitl_rate": alarm.reading.hitl_rate,
                            "first_pass_rate": alarm.reading.first_pass_rate,
                            "suspects": [f"{s.kind}:{s.ref}" for s in alarm.suspects],
                            "shadow_proposal": alarm.shadow_proposal,
                        },
                    )
                )

    async def _fleet_open_issue_count(self) -> int | None:
        """Open-issue gauge for the board_growth band. Fail-soft to None
        (the band simply skips a cycle — it can only under-alarm)."""
        if self._prs is None:
            return None
        try:
            # Typed Port primitive (#9905's keep-set reader) — identity only,
            # no body/label projection, so the gauge stays cheap.
            numbers = await self._prs.list_open_issue_numbers()
        except (RuntimeError, ValueError, AttributeError) as exc:
            logger.debug("fleet open-issue gauge failed: %s", exc)
            return None
        return len(numbers) if isinstance(numbers, list) else None

    async def _fleet_change_ledger(self) -> list[Any]:
        """Mechanical suspect input: staging merges in the last 24h.

        Zero LLM tokens — `git log` on the repo root. Config flips and boot
        events join the ledger in a later rung; merges alone named the
        founding incident's culprit. Fail-soft to an empty ledger.
        """
        try:
            out = await run_subprocess(
                "git",
                "log",
                "--since=24 hours ago",
                "--format=%H|%ct|%s",
                "--no-merges",
                "-n",
                "40",
                cwd=Path(self._config.repo_root),
                timeout=30,
            )
        except RuntimeError as exc:
            # Includes SubprocessTimeoutError — degrade to an empty ledger;
            # the alarm still fires, just without a mechanical suspect.
            logger.debug("fleet change-ledger fetch failed: %s", exc)
            return []
        changes = []
        for line in (out or "").splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            sha, epoch, subject = parts
            try:
                ts = datetime.fromtimestamp(int(epoch), tz=UTC)
            except (TypeError, ValueError):
                continue
            changes.append(
                ChangeEvent(ts=ts, kind="merge", ref=sha[:9], description=subject[:80])
            )
        return changes

    def _emit_sentry_metrics(
        self,
        metrics: TrendMetrics,
        *,
        gap_count: int = 0,
        adjustment_count: int = 0,
        log_patterns_total: int = 0,
        log_patterns_novel: int = 0,
        log_patterns_escalating: int = 0,
        hitl_recommendations_count: int = 0,
    ) -> None:
        if self._obs is None:
            return
        self._obs.set_measurement("memory.avg_score", metrics.avg_memory_score)
        self._obs.set_measurement("memory.first_pass_rate", metrics.first_pass_rate)
        self._obs.set_measurement("memory.surprise_rate", metrics.surprise_rate)
        self._obs.set_measurement("memory.stale_items", float(metrics.stale_item_count))
        self._obs.set_measurement("memory.knowledge_gaps", float(gap_count))
        self._obs.set_measurement("memory.auto_adjustments", float(adjustment_count))
        self._obs.set_measurement(
            "memory.log_patterns_total", float(log_patterns_total)
        )
        self._obs.set_measurement(
            "memory.log_patterns_novel", float(log_patterns_novel)
        )
        self._obs.set_measurement(
            "memory.log_patterns_escalating", float(log_patterns_escalating)
        )
        self._obs.set_measurement(
            "memory.hitl_recommendations_unactioned",
            float(hitl_recommendations_count),
        )
