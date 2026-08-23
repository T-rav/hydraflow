"""Stall detection and restart actuation of ``HealthMonitorLoop``.

Extracted VERBATIM from ``src/health_monitor_loop.py`` (god-class
decomposition, Refs #11547) as a mixin.

One concern: a loop that has stopped ticking — the ADR-0046 dead-man-switch
over the meta-observer, the generic registry-wide heartbeat sweep, and the
ADR-0106 event-loop freeze marker. Each one restarts first and files second.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from dedup_store import DedupStore
from event_loop_watchdog import (
    clear_stall_marker,
    event_loop_stall_marker_path,
    read_stall_marker,
)
from events import EventType, HydraFlowEvent

from ._common import (
    _SANITY_NOOP_STREAK_THRESHOLD,
    _SANITY_RESTART_KEY,
    _SANITY_STALL_MULTIPLIER,
    _WORKER_STALL_EXCLUDED,
    _WORKER_STALL_MULTIPLIER,
)

if TYPE_CHECKING:
    from bg_worker_manager import BGWorkerManager
    from events import EventBus
    from ports import PRPort
    from state import StateTracker


logger = logging.getLogger("hydraflow.health_monitor_loop")


class HealthMonitorStallMixin:
    """Stall detection and restart actuation of ``HealthMonitorLoop``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``HealthMonitorLoop.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _bg_workers: BGWorkerManager | None
    _bus: EventBus
    _config: HydraFlowConfig
    _prs: PRPort | None
    _sanity_noop_streak: int
    _sanity_stall_dedup: DedupStore
    _state: StateTracker | None

    if TYPE_CHECKING:

        async def _close_issues_by_label(
            self,
            prs: PRPort,
            label: str,
            comment: str,
            *,
            title_contains: str | None = None,
        ) -> None: ...  # provided by _freshness

    async def _check_sanity_loop_staleness(self) -> None:  # noqa: PLR0911
        """Dead-man-switch for `TrustFleetSanityLoop` (spec §12.1).

        When the sanity loop is enabled but its heartbeat is older than
        ``_SANITY_STALL_MULTIPLIER × trust_fleet_sanity_interval``,
        file one `hydraflow-find` + `sanity-loop-stalled` issue per stall
        event. The sanity loop watches the nine trust loops; this
        method watches the sanity loop. Recursion is bounded at one
        meta-layer (spec §12.1 "Bounds of meta-observability").

        ``bg_workers`` is injected post-ctor by the orchestrator
        (chicken-and-egg with BGWorkerManager); ``state`` is passed at
        construction time. When either is missing — as happens in some
        minimal scenario fixtures — this check is a silent no-op so
        production cycles do not spam debug-level exceptions.

        Dedup: filed issues are tracked in ``_sanity_stall_dedup``. The
        key is cleared the next time the sanity loop ticks within the
        threshold, so a subsequent stall files a fresh issue.
        """
        state = self._state
        bg_workers = self._bg_workers
        prs = self._prs
        if state is None or bg_workers is None or prs is None:
            return

        dedup_key = "health_monitor:trust_fleet_sanity:stalled"
        filed_keys = self._sanity_stall_dedup.get()

        hb = state.get_worker_heartbeats().get("trust_fleet_sanity")
        last_run_iso = hb.get("last_run") if isinstance(hb, dict) else None
        enabled = bool(
            getattr(bg_workers, "worker_enabled", {}).get("trust_fleet_sanity", True)
        )
        if not last_run_iso or not enabled:
            return
        try:
            last_run = datetime.fromisoformat(
                last_run_iso.replace("Z", "+00:00"),
            )
        except ValueError:
            return
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=UTC)
        elapsed_s = (datetime.now(UTC) - last_run).total_seconds()
        threshold_s = (
            _SANITY_STALL_MULTIPLIER * self._config.trust_fleet_sanity_interval
        )
        # Activity-based health (G5): track no-op streak. A sanity loop
        # that ticks but reports zero workers_scanned has fresh heartbeat
        # but isn't doing real work — catch that here.
        details = hb.get("details") if isinstance(hb, dict) else None
        workers_scanned = (
            int(details.get("workers_scanned", 0)) if isinstance(details, dict) else 0
        )
        noop_tripped = False
        if elapsed_s < threshold_s:
            # Heartbeat is fresh. Check the no-op streak.
            if workers_scanned == 0:
                self._sanity_noop_streak += 1
            else:
                self._sanity_noop_streak = 0
            if self._sanity_noop_streak >= _SANITY_NOOP_STREAK_THRESHOLD:
                noop_tripped = True
            else:
                # Loop is ticking again. Close any open stall issue and clear
                # its dedup key (#9359 issue-hygiene) — a persistent no-op
                # re-escalates via the streak.
                if dedup_key in filed_keys:
                    await self._close_issues_by_label(
                        prs,
                        "sanity-loop-stalled",
                        "trust_fleet_sanity is ticking again — auto-closing.",
                    )
                # Only re-arm restart-first on GENUINE recovery (real work).
                # workers_scanned == 0 with streak < threshold is a no-op
                # streak still building — clearing the marker there would
                # restart a persistent no-op every 3 ticks forever with
                # escalation permanently bypassed.
                cleared = {dedup_key}
                if workers_scanned > 0:
                    cleared.add(_SANITY_RESTART_KEY)
                if filed_keys & cleared:
                    self._sanity_stall_dedup.set_all(filed_keys - cleared)
                return
        else:
            # Young-task window: heartbeats only refresh at cycle COMPLETION,
            # so a freshly recreated task (restart-first tick, credit-pause
            # resume, orchestrator restart) still carries the stale heartbeat
            # while its first cycle is in flight. Neither recovered (clearing
            # the restart marker here would break restart-once-then-escalate:
            # a wedged loop would be restarted every threshold window forever)
            # nor actionable — wait until the task itself outlives the
            # threshold without heartbeating.
            started_at = bg_workers.run_started_at("trust_fleet_sanity")
            if (
                started_at is not None
                and (datetime.now(UTC) - started_at).total_seconds() < threshold_s
            ):
                return
            # Stale-heartbeat path — counter remains as last seen; no-op
            # streak may or may not be set, but we file the stale-stall
            # variant of the issue regardless.
            self._sanity_noop_streak = 0
        # Restart-first (dark-factory): before paging a human, try the
        # restart verb once per stall event. A wedged task is cancelled and
        # recreated; escalation waits one more threshold window. When the
        # verb is unwired (minimal fixtures / restart returns False) fall
        # through to filing immediately — pre-restart behavior.
        if _SANITY_RESTART_KEY not in filed_keys:
            restarted = await bg_workers.restart("trust_fleet_sanity")
            if restarted:
                logger.warning(
                    "trust_fleet_sanity stalled — auto-restarted "
                    "(restart-first; escalation deferred one threshold window)"
                )
                self._sanity_noop_streak = 0
                self._sanity_stall_dedup.set_all(filed_keys | {_SANITY_RESTART_KEY})
                return
        # Heartbeat-stale or no-op-streak path: file (or dedup-skip).
        if dedup_key in filed_keys:
            # Already filed for the current stall event; wait for recovery
            # (or operator-close via issue_close reconcile) before refiling.
            return

        if noop_tripped:
            title = (
                f"sanity-loop-stalled: trust_fleet_sanity ticked but did no "
                f"work for {self._sanity_noop_streak} consecutive cycles"
            )
            cause_summary = (
                f"The meta-observability loop has updated its heartbeat but "
                f"reported `workers_scanned: 0` for "
                f"`{self._sanity_noop_streak}` consecutive ticks "
                f"(threshold `{_SANITY_NOOP_STREAK_THRESHOLD}`) — "
                f"silent no-op (spec §12.1 + audit G5)."
            )
        else:
            title = (
                f"sanity-loop-stalled: trust_fleet_sanity silent for "
                f"{int(elapsed_s)}s (threshold {int(threshold_s)}s)"
            )
            cause_summary = (
                f"The meta-observability loop has not ticked in "
                f"`{int(elapsed_s)}s`, exceeding "
                f"`{_SANITY_STALL_MULTIPLIER} × "
                f"trust_fleet_sanity_interval` = "
                f"`{int(threshold_s)}s` (spec §12.1)."
            )
        body = (
            f"## TrustFleetSanityLoop dead-man-switch tripped\n\n"
            f"{cause_summary}\n\n"
            f"- Last heartbeat: `{last_run_iso}`\n"
            f"- Interval: "
            f"`{self._config.trust_fleet_sanity_interval}s`\n"
            f"- Enabled: `True`\n"
            f"- Workers scanned (last tick): `{workers_scanned}`\n"
            f"- Auto-restart attempted: "
            f"`{_SANITY_RESTART_KEY in filed_keys}` "
            f"(restart-first did not clear the stall)\n\n"
            f"### Operator playbook\n"
            f"1. Check orchestrator logs for the `trust_fleet_sanity` "
            f"loop task (look for uncaught exceptions on the run task).\n"
            f"2. Restart the orchestrator (`systemctl restart hydraflow` "
            f"or equivalent).\n"
            f"3. If the loop continues to stall, flip its "
            f"kill-switch in the **System** tab and file a HydraFlow "
            f"bug report.\n\n"
            f"_Auto-filed by HydraFlow `health_monitor` "
            f"(spec §12.1 dead-man-switch)._"
        )
        await prs.create_issue(
            title,
            body,
            ["hydraflow-find", "sanity-loop-stalled"],
        )
        filed_keys = self._sanity_stall_dedup.get()
        self._sanity_stall_dedup.set_all(filed_keys | {dedup_key})

    def _worker_stall_multiplier(self, name: str) -> int:
        """Interval multiplier for *name*'s stall-sweep threshold (#10241).

        The blanket ``_WORKER_STALL_MULTIPLIER`` (3) leaves two poll intervals
        of grace over the worst-case legitimate heartbeat age (one pre-cycle
        interval + a full ``cycle_timeout``). For a short-poll / long-cycle
        loop like ``staging_bisect`` that pushes remediation ~30 min past
        ``TrustFleetSanityLoop``'s own staleness alert, leaving a window where
        an anomaly issue exists but nothing has been auto-restarted yet
        (#10234). Opt-in loops (``worker_stall_tight_loops``) use the tighter
        ``worker_stall_tight_multiplier`` instead, firing the restart closer to
        that alert window.

        The multiplier stays ``>= 1`` (config floor) so the resulting
        threshold ``multiplier × interval + cycle_timeout`` remains strictly
        above ``interval + cycle_timeout`` — the longest a *healthy* cycle can
        keep the heartbeat stale (the watchdog cancels any cycle at
        ``cycle_timeout``). A legitimately long in-flight cycle is therefore
        still never false-restarted; only genuine hangs past the floor trip.
        """
        cfg = self._config
        tight_loops = getattr(cfg, "worker_stall_tight_loops", None) or ()
        if name in tight_loops:
            return int(cfg.worker_stall_tight_multiplier)
        return _WORKER_STALL_MULTIPLIER

    async def _check_worker_staleness(self) -> None:
        """Generic restart-first stall sweep across registry loops.

        Third leg of loop supervision: the per-cycle watchdog (#9556)
        bounds a cycle that hangs, the supervisor restarts a loop that
        raises — but a loop that goes *silent* (task wedged outside the
        watchdog window) shows only as a stale heartbeat (#9650). Restart
        it once per stall event; escalate with a ``loop-stalled`` issue
        (plus a ``worker_stall`` ``SYSTEM_ALERT`` event, #10086 — the only
        observable signal of a genuine escalation, since this sweep never
        surfaces per-worker results through ``_do_work()``'s returned stats)
        only when the restart didn't clear it. Recovery auto-closes the
        issue (title-filtered — the label is shared across loops) and
        clears both markers so a future stall restarts fresh.

        Threshold is ``_WORKER_STALL_MULTIPLIER × interval +
        cycle_timeout`` so a legitimately long LLM cycle (heartbeat only
        refreshes between cycles) is never false-restarted. Non-registry
        workers (pipeline phases, store poller) are out of scope — their
        supervision semantics differ. Silent no-op when deps are missing
        (minimal scenario fixtures), mirroring the §12.1 check.
        """
        state = self._state
        bg_workers = self._bg_workers
        prs = self._prs
        # ``getattr`` guard: __new__-bypassed test scaffolding constructs
        # this loop without the ctor (see PR #8460 post-mortem).
        dedup = getattr(self, "_worker_stall_dedup", None)
        if state is None or bg_workers is None or prs is None or dedup is None:
            return

        heartbeats = state.get_worker_heartbeats()
        registered = bg_workers.registered_loop_names()
        enabled_flags = getattr(bg_workers, "worker_enabled", {})
        keys = dedup.get()
        now = datetime.now(UTC)
        for name, hb in heartbeats.items():
            if name in _WORKER_STALL_EXCLUDED or name not in registered:
                continue
            if not enabled_flags.get(name, True):
                continue
            last_run_iso = hb.get("last_run") if isinstance(hb, dict) else None
            if not last_run_iso:
                continue
            try:
                last_run = datetime.fromisoformat(last_run_iso.replace("Z", "+00:00"))
            except ValueError:
                continue
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=UTC)
            elapsed_s = (now - last_run).total_seconds()
            interval_s = bg_workers.get_interval(name)
            stall_multiplier = self._worker_stall_multiplier(name)
            threshold_s = stall_multiplier * interval_s + bg_workers.cycle_timeout(name)
            restart_key = f"health_monitor:worker-stall:restart:{name}"
            filed_key = f"health_monitor:worker-stall:filed:{name}"
            if elapsed_s < threshold_s:
                # Recovery — close this worker's stall issue (if filed)
                # and clear markers so a future stall restarts fresh.
                if filed_key in keys:
                    # Delimited needle (": {name} ") — a bare name would
                    # also match prefix siblings (stale_issue ⊂
                    # stale_issue_gc) and close the wrong loop's issue.
                    await self._close_issues_by_label(
                        prs,
                        "loop-stalled",
                        f"`{name}` is heartbeating again — auto-closing.",
                        title_contains=f": {name} ",
                    )
                if keys & {restart_key, filed_key}:
                    keys = keys - {restart_key, filed_key}
                    dedup.set_all(keys)
                continue
            # Young-task window: heartbeats only refresh at cycle
            # COMPLETION, so a freshly recreated task (restart-first tick,
            # credit-pause resume, orchestrator restart) still carries the
            # stale heartbeat while its first cycle is in flight. Neither
            # recovered (clearing markers here would break restart-once-
            # then-escalate: a wedged loop would restart every threshold
            # window forever) nor actionable — wait until the task itself
            # outlives the threshold without heartbeating.
            started_at = bg_workers.run_started_at(name)
            if (
                started_at is not None
                and (now - started_at).total_seconds() < threshold_s
            ):
                continue
            # Stale. Restart-first: one restart per stall event; escalation
            # waits one more sweep. Falls through to filing when the verb
            # is unwired (returns False).
            if restart_key not in keys:
                restarted = await bg_workers.restart(name)
                if restarted:
                    logger.warning(
                        "Loop %r stalled (%.0fs > %.0fs) — auto-restarted "
                        "(restart-first; escalation deferred one sweep)",
                        name,
                        elapsed_s,
                        threshold_s,
                    )
                    keys = keys | {restart_key}
                    dedup.set_all(keys)
                    continue
            if filed_key in keys:
                # Already filed for the current stall event.
                continue
            title = (
                f"loop-stalled: {name} silent for {int(elapsed_s)}s "
                f"(threshold {int(threshold_s)}s)"
            )
            body = (
                f"## Background loop dead-man-switch tripped\n\n"
                f"`{name}` has not heartbeated in `{int(elapsed_s)}s`, "
                f"exceeding `{stall_multiplier} × interval + "
                f"cycle_timeout` = `{int(threshold_s)}s`.\n\n"
                f"- Last heartbeat: `{last_run_iso}`\n"
                f"- Interval: `{interval_s}s`\n"
                f"- Watchdog bound: `{bg_workers.cycle_timeout(name)}s`\n"
                f"- Auto-restart attempted: `{restart_key in keys}` "
                f"(restart-first did not clear the stall)\n\n"
                f"### Operator playbook\n"
                f"1. Check orchestrator logs for the `{name}` loop task "
                f"(look for a wedged await outside the cycle watchdog).\n"
                f"2. Restart the orchestrator (`systemctl restart "
                f"hydraflow` or equivalent).\n"
                f"3. If the loop stalls repeatedly, flip its kill-switch "
                f"in the **System** tab and file a HydraFlow bug report.\n\n"
                f"_Auto-filed by HydraFlow `health_monitor` (generic "
                f"loop-stall dead-man-switch)._"
            )
            issue_number = await prs.create_issue(
                title,
                body,
                ["hydraflow-find", "loop-stalled"],
            )
            # SYSTEM_ALERT alongside the filed issue (mirrors the sibling
            # stale-code dead-man-switch below) — the sweep itself never
            # surfaces escalation through ``_do_work()``'s returned stats (it
            # runs across an arbitrary number of registered workers, not one
            # fixed metric), so this is the only observable signal that a
            # stall genuinely escalated rather than merely heartbeated (#10086).
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "kind": "worker_stall",
                        "source": "health_monitor",
                        "worker": name,
                        "issue": issue_number,
                        "elapsed_seconds": int(elapsed_s),
                        "threshold_seconds": int(threshold_s),
                    },
                )
            )
            keys = keys | {filed_key}
            dedup.set_all(keys)

    async def _check_event_loop_stall(self) -> None:
        """Escalate a synchronous event-loop freeze recorded by the watchdog.

        ``EventLoopWatchdog`` (#9552) is a daemon THREAD: while the event
        loop is frozen it can dump stacks and write a marker, but it cannot
        file a GitHub issue — the async Ports run on the very loop that
        froze. This check runs once the loop is healthy again (in-place
        recovery, or the first cycles after a process restart), files one
        ``hydraflow-find`` + ``loop-stalled`` issue per marker, then consumes
        the marker. File-then-clear: a failed filing leaves the marker in
        place so the next tick retries; the marker file itself is the dedup.
        """
        prs = self._prs
        if prs is None:
            return
        marker_path = event_loop_stall_marker_path(self._config)
        marker = read_stall_marker(marker_path)
        if marker is None:
            return
        detected_at = marker.get("detected_at", "unknown")
        stalled_for = marker.get("stalled_for_seconds", "?")
        threshold = marker.get("threshold_seconds", "?")
        dump_path = marker.get("dump_path", "unknown")
        episodes = marker.get("episode_count", 1)
        hard_restart = marker.get("hard_restart", False)
        # #11604 attribution: was the loop wedged, or was the HOST starving
        # the whole process? Restarting the second class makes it worse, so
        # the watchdog records its verdict and the operator needs to see it
        # before chasing the frame in the stack dump.
        verdict = marker.get("verdict", "unknown")
        decision = marker.get("restart_decision", "unknown")
        service_ratio = marker.get("observer_service_ratio", "?")
        cpu_fraction = marker.get("process_cpu_fraction", "?")
        title = (
            f"event-loop-stalled: process event loop froze synchronously "
            f"for {stalled_for}s"
        )
        body = (
            f"## Event-loop freeze detected by the thread-level watchdog "
            f"(#9552)\n\n"
            f"The asyncio event loop stopped scheduling tasks for "
            f"`{stalled_for}s` (threshold `{threshold}s`) — a SYNCHRONOUS "
            f"block (CPU spin, blocking file I/O, non-async subprocess.run) "
            f"inside a loop's `_do_work` wedged the entire process. The "
            f"per-cycle asyncio watchdog cannot see this class; the "
            f"`EventLoopWatchdog` daemon thread caught it from outside the "
            f"loop.\n\n"
            f"- Detected at: `{detected_at}`\n"
            f"- Freeze episodes before this escalation: `{episodes}`\n"
            f"- All-thread stack dump: `{dump_path}`\n"
            f"- Hard restart was enabled at trip time: `{hard_restart}`\n"
            f"- Verdict: `{verdict}` — restart decision `{decision}`\n"
            f"- Watchdog observer service ratio: `{service_ratio}` "
            f"(1.0 = the watchdog thread kept its own poll cadence); "
            f"process CPU per wall-second: `{cpu_fraction}`\n\n"
            f"### Operator playbook\n"
            f"1. Read the verdict first (#11604). `starved` means the HOST "
            f"was oversubscribed and the watchdog thread lost its own "
            f"schedule too — the loop was not wedged, the stack frame below "
            f"is just where it happened to be, and no code fix is implied. "
            f"`blocked` / `blocked_spin` mean the loop really did stop while "
            f"the observer kept running.\n"
            f"2. For a `blocked` verdict, open the stack dump above — the "
            f"frozen loop thread's top Python frame IS the offending "
            f"synchronous call site.\n"
            f"3. Move that call off-loop (`asyncio.create_subprocess_exec`, "
            f"`run_in_executor`) and file/fix accordingly.\n"
            f"4. For recovery-in-place next time, consider enabling "
            f"`event_loop_watchdog_hard_restart` in the **System** tab "
            f"(requires a process supervisor with Restart=always). The "
            f"destructive path additionally requires a non-`starved` verdict "
            f"and `event_loop_watchdog_restart_after_episodes` episodes.\n\n"
            f"_Auto-filed by HydraFlow `health_monitor` (event-loop freeze "
            f"escalation, #9552)._"
        )
        await prs.create_issue(title, body, ["hydraflow-find", "loop-stalled"])
        clear_stall_marker(marker_path)
