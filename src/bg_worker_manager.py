"""Background worker lifecycle management — states, intervals, and triggering."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from models import BackgroundWorkerState

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from base_background_loop import BaseBackgroundLoop
    from config import HydraFlowConfig
    from state import StateTracker

logger = logging.getLogger("hydraflow.bg_worker_manager")

DEFAULT_DISABLED_WORKERS: frozenset[str] = frozenset({"principles_audit"})


class BGWorkerManager:
    """Manages background worker states, enabled flags, intervals, and triggering."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        bg_loop_registry: dict[str, BaseBackgroundLoop],
    ) -> None:
        self._config = config
        self._state = state
        self._bg_loop_registry = bg_loop_registry
        self._bg_worker_states: dict[str, BackgroundWorkerState] = {}
        self._bg_worker_enabled: dict[str, bool] = {}
        self._bg_worker_intervals: dict[str, int] = {}
        self._bg_worker_timeouts: dict[str, int] = {}
        # Injected post-ctor by the orchestrator (chicken-and-egg with the
        # supervisor's task dict) — mirrors HealthMonitor's set_bg_workers.
        self._restart_cb: Callable[[str], Awaitable[bool]] | None = None
        self._seed_default_disabled_workers()

    @property
    def worker_states(self) -> dict[str, BackgroundWorkerState]:
        """Mutable worker states dict."""
        return self._bg_worker_states

    @property
    def worker_enabled(self) -> dict[str, bool]:
        """Mutable enabled flags dict."""
        return self._bg_worker_enabled

    @property
    def worker_intervals(self) -> dict[str, int]:
        """Mutable intervals dict."""
        return self._bg_worker_intervals

    @property
    def worker_timeouts(self) -> dict[str, int]:
        """Mutable watchdog-timeout overrides dict."""
        return self._bg_worker_timeouts

    def update_status(
        self, name: str, status: str, details: dict[str, Any] | None = None
    ) -> None:
        """Record the latest heartbeat from a background worker."""
        self._bg_worker_states[name] = BackgroundWorkerState(
            name=name,
            status=status,
            last_run=datetime.now(UTC).isoformat(),
            details=dict(details) if details is not None else {},
        )
        self._state.set_bg_worker_state(name, self._bg_worker_states[name])

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a background worker by name and persist to state."""
        self._bg_worker_enabled[name] = enabled
        disabled = {n for n, e in self._bg_worker_enabled.items() if not e}
        self._state.set_disabled_workers(disabled)

    def is_enabled(self, name: str) -> bool:
        """Return whether a background worker is enabled (defaults to True)."""
        return self._bg_worker_enabled.get(name, True)

    def get_states(self) -> dict[str, BackgroundWorkerState]:
        """Return a copy of all background worker states with enabled flag."""
        result: dict[str, BackgroundWorkerState] = {}
        for name, state_dict in self._bg_worker_states.items():
            result[name] = cast(
                BackgroundWorkerState, {**state_dict, "enabled": self.is_enabled(name)}
            )
        return result

    def trigger(self, name: str) -> bool:
        """Trigger an immediate execution of a background worker.

        Returns ``True`` if the worker was found and triggered, ``False``
        if *name* does not correspond to a registered ``BaseBackgroundLoop``.
        """
        loop = self._bg_loop_registry.get(name)
        if loop is None:
            return False
        loop.trigger()
        return True

    def set_restart_cb(self, cb: Callable[[str], Awaitable[bool]]) -> None:
        """Inject the orchestrator's restart verb (post-ctor wiring)."""
        self._restart_cb = cb

    async def restart(self, name: str) -> bool:
        """Cancel-and-recreate a loop task via the orchestrator's restart verb.

        ``trigger`` wakes a *sleeping* loop; it cannot unstick one wedged on
        an ``await`` mid-cycle. ``restart`` can — HealthMonitorLoop's
        restart-first stall policy uses it before escalating to a human.
        Returns ``False`` when unwired (minimal fixtures) or unknown *name*.
        """
        if self._restart_cb is None:
            return False
        return await self._restart_cb(name)

    def registered_loop_names(self) -> set[str]:
        """Names of workers backed by a registered ``BaseBackgroundLoop``.

        Pipeline phases, the store poller, and other non-loop workers are
        absent — their supervision semantics differ (no interval/watchdog
        contract), so stall sweeps must not touch them.
        """
        return set(self._bg_loop_registry)

    def get_loop(self, name: str) -> BaseBackgroundLoop | None:
        """Return the registered loop instance for *name*, or ``None``.

        Read-only accessor used by the Trust Fleet drill-down to reach a
        loop's own diagnostics surface (e.g. ``StagingBisectLoop.stall_state``,
        #10240) without threading each loop into the route separately.
        """
        return self._bg_loop_registry.get(name)

    def cycle_timeout(self, name: str) -> int:
        """Effective per-cycle watchdog bound for *name* (#9556 semantics).

        Falls back to ``loop_watchdog_default_seconds`` for names without a
        registered ``BaseBackgroundLoop``.

        Used by ``HealthMonitorLoop``'s stall-multiplier calc, NOT by the
        watchdog itself — the watchdog reads through ``loop._timeout_cb``
        (wired to :meth:`get_timeout` for every shared-``LoopDeps`` loop), so
        this delegates to ``loop._cycle_timeout_seconds()`` to stay correct
        for loops with a bespoke ``timeout_cb`` (e.g. ``principles_audit``'s
        hardcoded LLM-bound closure in ``service_registry.py``, #9639) that
        bypasses the operator override table entirely (#9503).
        """
        loop = self._bg_loop_registry.get(name)
        if loop is None:
            return self._config.loop_watchdog_default_seconds
        return loop._cycle_timeout_seconds()

    def run_started_at(self, name: str) -> datetime | None:
        """When *name*'s current ``run()`` task started — ``None`` if unknown.

        Stall sweeps compare against ``max(heartbeat, run_started_at)`` so a
        freshly (re)created task with a stale persisted heartbeat (post
        credit-pause / orchestrator restart) is never false-restarted.
        """
        loop = self._bg_loop_registry.get(name)
        if loop is None:
            return None
        return loop._run_started_at

    def _restore_intervals(self, intervals: dict[str, int]) -> None:
        """Bulk-restore interval overrides (used during startup recovery)."""
        self._bg_worker_intervals.update(intervals)

    def _restore_timeouts(self, timeouts: dict[str, int]) -> None:
        """Bulk-restore watchdog-timeout overrides (used during startup recovery)."""
        self._bg_worker_timeouts.update(timeouts)

    def _seed_default_disabled_workers(self) -> None:
        """Persist first-run disabled defaults without overriding later UI enables."""
        defaults = DEFAULT_DISABLED_WORKERS & set(self._bg_loop_registry)
        if not defaults:
            return
        seeded = self._state.get_default_disabled_workers_seeded()
        missing = defaults - seeded
        if not missing:
            return
        disabled = self._state.get_disabled_workers() | missing
        for name in missing:
            self._bg_worker_enabled[name] = False
        self._state.set_disabled_workers(disabled)
        self._state.set_default_disabled_workers_seeded(seeded | missing)

    def _restore_enabled_flags(self, disabled_names: set[str]) -> None:
        """Bulk-restore disabled flags (used during startup recovery)."""
        for name in disabled_names:
            self._bg_worker_enabled[name] = False

    def _remove_enabled_entry(self, name: str) -> None:
        """Remove an enabled-flag entry entirely (for stale worker pruning)."""
        self._bg_worker_enabled.pop(name, None)

    def _restore_worker_state(self, name: str, state: BackgroundWorkerState) -> None:
        """Set a single worker state entry (used during startup recovery)."""
        self._bg_worker_states[name] = state

    def _restore_worker_states(self, states: dict[str, BackgroundWorkerState]) -> None:
        """Bulk-restore worker heartbeat states (used during startup recovery)."""
        self._bg_worker_states.update(states)

    def _known_worker_state_names(self) -> set[str]:
        """Return the set of worker names that have heartbeat state."""
        return set(self._bg_worker_states)

    def _remove_worker_state_entry(self, name: str) -> None:
        """Remove an in-memory heartbeat entry entirely (for stale worker pruning)."""
        self._bg_worker_states.pop(name, None)

    def set_interval(self, name: str, seconds: int) -> None:
        """Set a dynamic interval override for a background worker."""
        self._bg_worker_intervals[name] = seconds
        self._state.set_worker_intervals(dict(self._bg_worker_intervals))

    def clear_interval(self, name: str) -> None:
        """Remove a dynamic interval override and persist (no-op if absent).

        The loop falls back to its own ``_get_default_interval()`` — used by
        the cost-throttle recovery path to undo a stretch the operator never
        asked for.
        """
        if name not in self._bg_worker_intervals:
            return
        del self._bg_worker_intervals[name]
        self._state.set_worker_intervals(dict(self._bg_worker_intervals))

    def get_interval(self, name: str) -> int:
        """Return the effective interval for a background worker.

        Priority: dynamic override → loop's own _get_default_interval() →
        non-loop fallback table → poll_interval.
        """
        if name in self._bg_worker_intervals:
            return self._bg_worker_intervals[name]
        loop = self._bg_loop_registry.get(name)
        if loop is not None:
            return loop._get_default_interval()
        # Fallback for non-loop workers that are not BaseBackgroundLoop subclasses.
        non_loop_defaults: dict[str, int] = {
            "memory_sync": self._config.memory_sync_interval,
            "pipeline_poller": 5,
        }
        return non_loop_defaults.get(name, self._config.poll_interval)

    def set_timeout(self, name: str, seconds: int) -> None:
        """Set a dynamic watchdog-timeout override for a background worker.

        Mirrors :meth:`set_interval`. Wired to every registered loop's
        ``timeout_cb`` (via ``WorkerRegistryCallbacks.get_watchdog_timeout`` →
        :meth:`get_timeout`), so the override takes effect on the loop's very
        next cycle without a redeploy (#9503).
        """
        self._bg_worker_timeouts[name] = seconds
        self._state.set_watchdog_timeouts(dict(self._bg_worker_timeouts))

    def clear_timeout(self, name: str) -> None:
        """Remove a dynamic watchdog-timeout override and persist (no-op if absent).

        Mirrors :meth:`clear_interval`. The loop falls back to its own
        :meth:`get_timeout` default (LONG_LLM_CYCLE-aware) once cleared.
        """
        if name not in self._bg_worker_timeouts:
            return
        del self._bg_worker_timeouts[name]
        self._state.set_watchdog_timeouts(dict(self._bg_worker_timeouts))

    def get_timeout(self, name: str) -> int:
        """Return the effective per-cycle watchdog bound for a background worker.

        Priority: dynamic override -> loop's own
        ``_default_cycle_timeout_seconds()`` -> config default. Mirrors
        :meth:`get_interval`. This is the method wired as every loop's
        ``timeout_cb`` (via ``WorkerRegistryCallbacks.get_watchdog_timeout``),
        so it — not :meth:`cycle_timeout` — is the live read path the
        watchdog actually consults each cycle.
        """
        if name in self._bg_worker_timeouts:
            return self._bg_worker_timeouts[name]
        loop = self._bg_loop_registry.get(name)
        if loop is not None:
            return loop._default_cycle_timeout_seconds()
        return self._config.loop_watchdog_default_seconds
