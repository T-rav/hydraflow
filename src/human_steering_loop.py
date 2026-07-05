"""Sensor loop for continuous human-on-the-loop steering (ADR-0099 #4).

Each tick, for every active issue, fetch its GitHub comments, parse steering
directives, and persist the resulting SteeringState. Pure sensing — the
orchestrator (Actuator) applies the state at phase boundaries.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from exception_classify import reraise_on_credit_or_bug
from human_steering import parse_directives
from loop_fitness import FitnessContext, LoopFitness, proposal_acceptance_fitness
from models import SteeringState

logger = logging.getLogger("hydraflow.human_steering")

_STEERING_LABEL = "human-steering"


class HumanSteeringLoop(BaseBackgroundLoop):
    def __init__(
        self,
        *,
        config: Any,
        state: Any,
        prs: Any,
        deps: LoopDeps,
        active_issues_cb: Callable[[], list[int]],
    ) -> None:
        super().__init__(
            worker_name="human_steering", config=config, deps=deps, run_on_startup=False
        )
        self._state = state
        self._prs = prs
        self._active_issues_cb = active_issues_cb

    def _get_default_interval(self) -> int:
        return int(self._config.human_steering_interval_seconds)

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        return proposal_acceptance_fitness(
            ctx, worker_name=self._worker_name, label=_STEERING_LABEL
        )

    async def _do_work(self) -> dict[str, Any]:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.human_steering_enabled:
            return {"status": "config_disabled"}
        if self._prs is None:
            return {"status": "ok", "updated": 0}
        updated = 0
        for issue_number in self._active_issues_cb():
            key = str(issue_number)
            try:
                comments = await self._prs.list_issue_comments(issue_number)
            except Exception as exc:  # noqa: BLE001
                reraise_on_credit_or_bug(exc)
                logger.warning("steering: comment fetch failed for #%s: %s", key, exc)
                continue
            prev = self._state.get_human_steering(key)
            d = parse_directives(
                comments,
                prev.last_applied_ts,
                frozenset(self._config.human_steering_authorized_users),
            )
            self._state.set_human_steering(
                key,
                SteeringState(
                    guidance=d.guidance,
                    flow=d.flow,
                    # Preserve an unconsumed redo: parse only emits redo_phase once
                    # (high-water-mark), so if the actuator hasn't cleared prev's
                    # redo yet, don't clobber it to None on a re-tick.
                    redo_phase=d.redo_phase or prev.redo_phase,
                    redo_count=prev.redo_count,
                    last_applied_ts=d.new_last_applied_ts,
                ),
            )
            updated += 1
        return {"status": "ok", "updated": updated}
