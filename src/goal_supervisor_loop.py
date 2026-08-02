"""GoalSupervisorLoop — the Tier-2 goal supervisor (ADR-0124).

A boring deterministic Tier-1 liveness kernel repairs *mechanism*; this Tier-2
"mini-me" redirects *mission* it can and surfaces the rest to the human. It ticks
on a cadence, assembles a read-only health snapshot from the EXISTING Tier-1
signals (per-loop heartbeats, credit-failover state, boot-SHA staleness, the
event-loop watchdog marker, the second-order vitals verdict), hands it to a
**Fable** agent under the standing goal *"keep the factory alive & healthy"*,
and records a :class:`SupervisorObservation` (assessment · insights ·
nudges-taken · escalations · deferred) to an append-only thread + the event bus.

Authority (ADR-0124): **watch + surface + NUDGE** only. The nudge/escalate,
classify, and give-up-window logic — the load-bearing safety — lives in
:mod:`supervisor_observation` as pure functions; this loop is a thin actuator
over that core (assemble signals → consult agent → route decisions → execute the
small reversible allowlist → record honestly). Follows ADR-0029 (caretaker
pattern) and ADR-0049 (kill-switch convention).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from events import EventType, HydraFlowEvent
from exception_classify import reraise_on_credit_or_bug
from loop_fitness import FitnessContext, FitnessKind, LoopFitness
from supervisor_observation import (
    NUDGE_FLAG_BOOT_SHA_STALENESS,
    NUDGE_POKE_WEDGED_PROMOTION,
    NUDGE_REARM_CREDIT_PROBE,
    NUDGE_RERUN_FLAKY_CHECK,
    NUDGE_RESTART_STALLED_LOOP,
    HealthSnapshot,
    Incident,
    SupervisorObservation,
    SupervisorVerdict,
    append_observation,
    build_health_snapshot,
    decide,
    derive_incidents,
    load_attempts,
    reconcile_ledger,
    save_attempts,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from bg_worker_manager import BGWorkerManager
    from goal_supervisor_runner import GoalSupervisorRunner
    from state import StateTracker

logger = logging.getLogger("hydraflow.goal_supervisor")

#: The staging-promotion loop a "poke wedged promotion" nudge restarts.
_PROMOTION_LOOP_NAME = "staging_promotion"

#: Short, compressed operating contract handed to the Fable agent. The
#: load-bearing safety (give-up window, classify, allowlist) is enforced in code
#: — the prompt only asks for an honest, root-caused verdict.
_STANDING_GOAL_PROMPT = """\
STANDING GOAL: keep the HydraFlow factory alive & healthy.

You are the Tier-2 goal supervisor. You WATCH, SURFACE, and NUDGE — you never
self-do anything with blast radius. Given the read-only health snapshot below,
return a JSON verdict following this operating contract, applied in order:

1. CLASSIFY each anomaly transient vs real. Transient (a flaky/one-off check,
   a CDN/NodeSource 403, an xdist worker-contamination test, a stray file) →
   wait/re-run, do NOT propose a nudge. Real degradations → act or escalate.
2. TRACTABLE + REVERSIBLE → propose a nudge from the allowlist: restart a
   stalled loop, poke a wedged promotion, re-run a flaky required check, re-arm
   a stuck credit-pause probe, flag boot-SHA staleness. BLAST RADIUS → escalate
   (blast="high"): force-push, deletes, config/gate flips, RC→main promotion,
   repeated failed heals. Never dress a blast-radius action as a nudge.
3. ROOT-CAUSE FIRST — every action carries a one-line diagnosis pulled from the
   signal. No cause = do not propose it.
4. Prefer KNOWN remedies for known incidents (stale-boot, wedged loop, stuck
   credit-pause, event-loop freeze, diverging vitals, NodeSource flake).
5. Be HONEST: transient vs real, actionable vs escalate. Never invent a
   resolution.

Return ONLY a JSON object, no prose:
{"assessment": "<one sentence>",
 "insights": ["<short>", ...],
 "actions": [{"kind": "restart_stalled_loop|poke_wedged_promotion|rerun_flaky_check|rearm_credit_probe|flag_boot_sha_staleness|<escalate-kind>",
              "target": "<loop-name or null>",
              "reason": "<one-line diagnosis>",
              "signal_class": "transient|real",
              "blast": "low|high"}]}

SNAPSHOT:
"""


@dataclass(frozen=True)
class NudgeResult:
    """Outcome of executing one nudge (kept honest for the thread, rule 6)."""

    executed: bool
    note: str


class DefaultSupervisorNudger:
    """Executes the reversible nudge allowlist against the live factory.

    Injectable so unit tests substitute a fake and never touch bg_workers /
    credit_failover. ``bg_workers`` is resolved lazily because it is wired
    post-registry (``set_bg_workers``).
    """

    def __init__(
        self, *, bg_workers_getter: Callable[[], BGWorkerManager | None]
    ) -> None:
        self._bg_workers_getter = bg_workers_getter

    async def execute(self, inc: Incident) -> NudgeResult:
        if inc.kind == NUDGE_RESTART_STALLED_LOOP:
            return await self._restart(inc.target)
        if inc.kind == NUDGE_POKE_WEDGED_PROMOTION:
            return await self._restart(_PROMOTION_LOOP_NAME)
        if inc.kind == NUDGE_REARM_CREDIT_PROBE:
            import credit_failover  # noqa: PLC0415

            armed = credit_failover.rearm_probe(now=datetime.now(UTC))
            return NudgeResult(
                armed,
                "re-armed the credit switch-back probe"
                if armed
                else "no active credit failover to re-arm",
            )
        if inc.kind == NUDGE_FLAG_BOOT_SHA_STALENESS:
            # Informational surface only — the observation + event carry it.
            return NudgeResult(True, "surfaced boot-SHA staleness")
        if inc.kind == NUDGE_RERUN_FLAKY_CHECK:
            # v1: no CI re-run seam is wired, so this defers to CI's own retry
            # rather than fabricating a resolution (honest-thread contract).
            return NudgeResult(
                False, "no CI re-run seam wired; deferred to CI auto-retry"
            )
        return NudgeResult(False, f"no executor for nudge kind '{inc.kind}'")

    async def _restart(self, name: str | None) -> NudgeResult:
        bg = self._bg_workers_getter()
        if bg is None or not name:
            return NudgeResult(False, "bg_workers unavailable")
        ok = await bg.restart(name)
        return NudgeResult(
            ok,
            f"restarted loop '{name}'"
            if ok
            else f"restart of '{name}' failed or is unwired",
        )


def build_supervisor_prompt(snapshot: HealthSnapshot) -> str:
    """Short Fable prompt: the standing-goal contract + the snapshot JSON."""
    return _STANDING_GOAL_PROMPT + json.dumps(snapshot.summary(), sort_keys=True)


def _incident_line(inc: Incident, suffix: str) -> str:
    target = f" [{inc.target}]" if inc.target else ""
    return f"{inc.kind}{target} — {inc.diagnosis}{suffix}"


class GoalSupervisorLoop(BaseBackgroundLoop):
    """Tier-2 goal supervisor: reads Tier-1 signals, nudges the reversible,
    escalates the rest (ADR-0124).
    """

    # Spawns a Fable agent — earns the longer watchdog cycle bound.
    LONG_LLM_CYCLE = True

    def __init__(
        self,
        config: HydraFlowConfig,
        deps: LoopDeps,
        *,
        state: StateTracker | None = None,
        runner: GoalSupervisorRunner | None = None,
        bg_workers: BGWorkerManager | None = None,
        nudger: DefaultSupervisorNudger | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(worker_name="goal_supervisor", config=config, deps=deps)
        self._state = state
        self._runner = runner
        self._bg_workers = bg_workers
        self._nudger = nudger or DefaultSupervisorNudger(
            bg_workers_getter=lambda: self._bg_workers
        )
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    def _get_default_interval(self) -> int:
        return self._config.goal_supervisor_interval

    def set_bg_workers(self, bg_workers: BGWorkerManager) -> None:
        """Late-binding for the post-ctor BGWorkerManager wiring."""
        self._bg_workers = bg_workers

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Read-diagnose-surface supervisor with no proposal/acceptance lifecycle
        # of its own to score — HOUSEKEEPING per ADR-0093's fitness contract.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.goal_supervisor_loop_enabled:
            return {"status": "config_disabled"}
        if self._config.dry_run:
            return None
        try:
            return await self._supervise()
        except Exception as exc:
            # Credit/bug signals must propagate so the loop suspends rather than
            # burning budget against an exhausted billing signal (dark-factory).
            reraise_on_credit_or_bug(exc)
            logger.warning("goal supervisor cycle failed", exc_info=True)
            return {"error": True}

    async def _supervise(self) -> dict[str, Any]:
        now = self._now_fn()
        snapshot = self._build_snapshot(now)

        # Verify + re-arm the give-up ledger against this tick (rule 8): any
        # tracked incident that is no longer active has cleared.
        attempts = load_attempts(self._config)
        active_keys = {inc.key for inc in derive_incidents(snapshot)}
        attempts, cleared = reconcile_ledger(attempts, active_keys)
        verified = [f"verified: {key} cleared since last tick" for key in cleared]

        if snapshot.healthy:
            # Healthy → no-op (no Fable spawn). Persist the pruned ledger; record
            # a lightweight verified observation only when something cleared.
            if cleared:
                save_attempts(self._config, attempts)
                obs = SupervisorObservation(
                    ts=now.isoformat(),
                    snapshot=snapshot.summary(),
                    assessment="factory healthy",
                    insights=verified,
                )
                append_observation(self._config, obs)
                await self._emit(obs)
                return {"status": "healthy_verified", "cleared": len(cleared)}
            return {"status": "healthy"}

        # Degraded → consult the Fable agent, then route deterministically.
        verdict = await self._consult_agent(snapshot)
        decisions = decide(
            snapshot=snapshot, agent_actions=verdict.actions, attempts=attempts
        )

        nudges_taken: list[str] = []
        for inc in decisions.nudges:
            result = await self._nudger.execute(inc)
            attempts[inc.key] = attempts.get(inc.key, 0) + 1
            verb = "nudged" if result.executed else "attempted"
            nudges_taken.append(
                _incident_line(inc, f" ({verb}: {result.note}; pending verify)")
            )

        escalations: list[str] = []
        for inc in decisions.escalations:
            why = (
                f" (escalated: {inc.escalate_reason})"
                if inc.escalate_reason
                else " (blast-radius: surfaced, not self-done)"
            )
            escalations.append(_incident_line(inc, why))

        deferred: list[str] = []
        for inc in decisions.deferred:
            deferred.append(
                _incident_line(inc, " (transient/no-cause: waiting, no nudge spent)")
            )

        obs = SupervisorObservation(
            ts=now.isoformat(),
            snapshot=snapshot.summary(),
            assessment=verdict.assessment,
            insights=[*verdict.insights, *verified],
            nudges_taken=nudges_taken,
            escalations=escalations,
            deferred=deferred,
        )
        save_attempts(self._config, attempts)
        append_observation(self._config, obs)
        await self._emit(obs)
        return {
            "status": "acted",
            "nudges": len(nudges_taken),
            "escalations": len(escalations),
            "deferred": len(deferred),
        }

    async def _consult_agent(self, snapshot: HealthSnapshot) -> SupervisorVerdict:
        runner = self._get_runner()
        if runner is None:
            return SupervisorVerdict(assessment="(no supervisor runner wired)")
        prompt = build_supervisor_prompt(snapshot)
        # run() never raises for ordinary failures (crashed transcript →
        # "(no parseable verdict)"); credit/auth-terminal propagates to _do_work.
        return await runner.run(
            prompt=prompt, worktree_path=str(self._config.repo_root), issue_number=0
        )

    def _get_runner(self) -> GoalSupervisorRunner | None:
        if self._runner is None:
            from goal_supervisor_runner import GoalSupervisorRunner  # noqa: PLC0415

            self._runner = GoalSupervisorRunner(
                config=self._config, event_bus=self._bus
            )
        return self._runner

    def _build_snapshot(self, now: datetime) -> HealthSnapshot:
        import credit_failover  # noqa: PLC0415
        import git_revision  # noqa: PLC0415
        from event_loop_watchdog import (  # noqa: PLC0415
            event_loop_stall_marker_path,
            read_stall_marker,
        )

        heartbeats: dict[str, dict[str, Any]] = {}
        vitals_verdict: str | None = None
        if self._state is not None:
            # Snapshot assembly is best-effort read-only — a failed signal read
            # degrades the snapshot, it must never crash the supervisor tick.
            try:
                heartbeats = {
                    name: {
                        "status": hb.get("status"),
                        "last_run": hb.get("last_run"),
                    }
                    for name, hb in self._state.get_worker_heartbeats().items()
                }
            except Exception:  # noqa: BLE001
                logger.warning("goal supervisor: heartbeat read failed", exc_info=True)
            try:
                vitals_verdict = self._state.get_second_order_vitals_last_verdict()
            except Exception:  # noqa: BLE001
                vitals_verdict = None

        intervals = self._interval_map(heartbeats.keys())

        commits_behind = None
        boot_sha = None
        try:
            boot_sha = git_revision.get_boot_sha()
            commits_behind = git_revision.get_commits_behind()
        except Exception:  # noqa: BLE001
            logger.debug("goal supervisor: git revision read failed", exc_info=True)

        marker = None
        try:
            marker = read_stall_marker(event_loop_stall_marker_path(self._config))
        except Exception:  # noqa: BLE001
            marker = None

        return build_health_snapshot(
            heartbeats=heartbeats,
            intervals=intervals,
            now=now,
            credit_failover_active=credit_failover.is_active(),
            credit_probe_overdue=credit_failover.probe_due(now),
            zai_key_present=credit_failover.zai_key_present(),
            boot_sha=boot_sha,
            commits_behind=commits_behind,
            event_loop_stall_marker=marker,
            vitals_verdict=vitals_verdict,
        )

    def _interval_map(self, names: Any) -> dict[str, int]:
        """Per-loop interval for the stall threshold, via the deps interval_cb.

        Absent in minimal fixtures (``interval_cb is None``) → an empty map, so
        stalls are simply not flagged rather than falsely tripping.
        """
        if self._interval_cb is None:
            return {}
        out: dict[str, int] = {}
        for name in names:
            # A missing/erroring interval is simply skipped (that loop won't be
            # stall-checked) rather than failing the whole snapshot.
            try:
                out[name] = int(self._interval_cb(name))
            except Exception:  # noqa: BLE001
                continue
        return out

    async def _emit(self, obs: SupervisorObservation) -> None:
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SUPERVISOR_OBSERVATION,
                data=obs.model_dump(),
            )
        )
