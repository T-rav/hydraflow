"""Read-only caretaker for the LLM gateway spend-coverage gauge."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from gateway_coverage import (
    GatewayCoverageSnapshot,
    build_coverage_for_configs,
    gateway_ledger_path,
    persist_snapshot,
)
from loop_fitness import Confidence, FitnessContext, FitnessKind, LoopFitness

logger = logging.getLogger("hydraflow.gateway_coverage")

_COVERAGE_WINDOW = timedelta(hours=24)


def _utcnow() -> datetime:
    """Injectable wall clock for deterministic caretaker tests."""
    return datetime.now(UTC)


class GatewayCoverageLoop(BaseBackgroundLoop):
    """Measures the share of LLM spend transiting the gateway."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: Any,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="gateway_coverage",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.gateway_coverage_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        """HOUSEKEEPING fitness (no normalized objective yet).

        Required override — new loops are NOT grandfathered by
        tests/test_loop_fitness_completeness.py. When this loop gains a
        measurable objective, switch to FitnessKind.SCORED with real
        components. Must stay PURE over ``ctx`` — no network, no clock,
        no mutable ``self`` state (the deferred optimizer replays history
        through it).
        """
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            components={},
            sample_count=0,
            confidence=Confidence.INSUFFICIENT_DATA,
            timestamp=ctx.window_end,
        )

    async def _do_work(self) -> dict[str, Any] | None:
        # ADR-0049 in-body kill-switch (universal mandate).
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        # Static config gate (defense-in-depth: deploy-time disable).
        if not self._config.gateway_coverage_enabled:
            return {"status": "config_disabled"}

        window_end = _utcnow()
        window_start = window_end - _COVERAGE_WINDOW

        def _build() -> tuple[GatewayCoverageSnapshot, bool]:
            expected_sources = (
                gateway_ledger_path(self._config),
                self._config.cost_inferences_path,
            )
            try:
                source_missing = any(not path.is_file() for path in expected_sources)
            except OSError:
                source_missing = True
            return (
                build_coverage_for_configs(
                    [self._config],
                    since=window_start,
                    until=window_end,
                    window_label="24h",
                    scope="repo",
                    repo_slug=self._config.repo_slug,
                ),
                source_missing,
            )

        snapshot_model, source_missing = await asyncio.to_thread(_build)
        snapshot = snapshot_model.to_json_dict()
        coverage_percent = snapshot["coverage_percent"]
        reached_ceiling = (
            snapshot["status"] == "complete"
            and coverage_percent == 100.0
            and snapshot["gateway_requests"] > 0
        )
        ceiling_was_achieved = self._state.gateway_coverage_ceiling_achieved() is True
        if reached_ceiling and not ceiling_was_achieved:
            self._state.mark_gateway_coverage_ceiling_achieved()
        # Once a 100% ceiling has been proven, an empty observation window can
        # no longer silently reset the contract to "no data": disappearance or
        # truncation of both append-only sources is itself lost evidence.
        lost_evidence = snapshot["status"] in {"partial", "no_data"}
        measured_below_ceiling = (
            snapshot["status"] == "complete" and coverage_percent != 100.0
        )
        regression_detected = ceiling_was_achieved and (
            snapshot["bypass_requests"] > 0
            or lost_evidence
            or measured_below_ceiling
            or source_missing
        )
        if regression_detected:
            count = self._state.record_gateway_coverage_regression()
            logger.error(
                "Gateway fleet regression after the 100%% ceiling: status=%s, "
                "coverage=%s, direct-provider requests=%s, source_missing=%s "
                "(occurrence=%s)",
                snapshot["status"],
                coverage_percent,
                snapshot["bypass_requests"],
                source_missing,
                count,
            )
        snapshot_model = replace(
            snapshot_model,
            ceiling_achieved=reached_ceiling or ceiling_was_achieved,
            regression_detected=regression_detected,
        )
        snapshot_path = str(
            await asyncio.to_thread(persist_snapshot, self._config, snapshot_model)
        )
        return {
            "status": "ok",
            "coverage_status": snapshot["status"],
            "coverage_percent": coverage_percent,
            "gateway_requests": snapshot["gateway_requests"],
            "bypass_requests": snapshot["bypass_requests"],
            "snapshot_path": snapshot_path,
            "ceiling_achieved": reached_ceiling or ceiling_was_achieved,
            "regression_detected": regression_detected,
        }
