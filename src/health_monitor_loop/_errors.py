"""Persistent-error self-repair actuator of ``HealthMonitorLoop``.

Extracted VERBATIM from ``src/health_monitor_loop.py`` (god-class
decomposition, Refs #11547) as a mixin.

One concern: a registry loop that keeps ticking but keeps failing (#10140) —
the consecutive-error streak, the known auto-repairs it tries first, and the
rolled-up ``hydraflow-find`` issue it files when no repair applies.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventType, HydraFlowEvent
from rollup_issue_manager import RollupIssueManager

from ._common import (
    _ERROR_STREAK_THRESHOLD,
    _PERSISTENT_ERROR_EXCLUDED,
    _PERSISTENT_ERROR_NAMESPACE,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from events import EventBus
    from ports import PRPort
    from repo_existence_prober import RepoProber
    from state import StateTracker


logger = logging.getLogger("hydraflow.health_monitor_loop")


class HealthMonitorPersistentErrorMixin:
    """Persistent-error self-repair actuator of ``HealthMonitorLoop``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``HealthMonitorLoop.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _bus: EventBus
    _config: HydraFlowConfig
    _error_streaks: dict[str, int]
    _known_repairs: dict[str, Callable[[], Awaitable[str | None]]]
    _prs: PRPort | None
    _repo_prober: RepoProber
    _state: StateTracker | None

    def _persistent_error_rollup(
        self, prs: PRPort, state: StateTracker
    ) -> RollupIssueManager:
        return RollupIssueManager(
            pr=prs,
            state=state,
            namespace=_PERSISTENT_ERROR_NAMESPACE,
            labels=["hydraflow-find", "loop-persistent-error"],
        )

    async def _check_persistent_worker_errors(self) -> None:
        """Actuator half of #9854's read-only per-loop health harness.

        Complements ``_check_worker_staleness`` (silent — heartbeat stops
        advancing) with the opposite failure mode: a loop that keeps
        TICKING but keeps FAILING. When a registry loop's heartbeat
        reports ``error`` for ``_ERROR_STREAK_THRESHOLD`` consecutive
        health_monitor ticks, either:

        - a KNOWN auto-repairable pattern (``self._known_repairs``) is
          applied — v1's concrete case is PrinciplesAuditLoop crashing on
          a ``managed_repos`` entry whose repo 404s, repaired by pruning
          (disabling) that entry; or
        - failing that (unknown pattern, or the known repair found
          nothing to fix), ONE deduped ``hydraflow-find`` +
          ``loop-persistent-error`` issue is filed naming the loop, via
          ``RollupIssueManager`` (one issue per worker, body updated with
          the growing streak count, auto-closed on recovery) — so the
          pipeline fixes it rather than a human eyeballing the dashboard.

        ``trust_fleet_sanity`` is excluded — it already runs its own
        ``tick_error_ratio`` anomaly detector for this exact failure class
        (spec §12.1); ``health_monitor`` is excluded for the same reason
        the stall sweep excludes itself (can't meaningfully self-diagnose).

        Streak counters are in-memory only (mirrors ``_sanity_noop_streak``
        above) and count per health_monitor TICK, not per distinct
        underlying cycle — the same simplification already accepted for
        the sanity no-op streak. Silent no-op when ``state``/``prs`` are
        missing (minimal scenario fixtures) or the actuator is disabled
        (``self_repair_actuator_enabled`` kill-switch).
        """
        state = self._state
        prs = self._prs
        if state is None or prs is None:
            return
        if not self._config.self_repair_actuator_enabled:
            return

        heartbeats = state.get_worker_heartbeats()
        for name, hb in heartbeats.items():
            if name in _PERSISTENT_ERROR_EXCLUDED or not isinstance(hb, dict):
                continue
            status = hb.get("status")
            last_run = hb.get("last_run")

            if status != "error":
                # Recovered (or never errored). Close any tracked issue and
                # reset the streak so a future failure re-escalates cleanly.
                if self._error_streaks.get(name, 0) >= _ERROR_STREAK_THRESHOLD:
                    rollup = self._persistent_error_rollup(prs, state)
                    await rollup.resolve(
                        name,
                        comment=(
                            f"`{name}` is heartbeating `ok` again — auto-closing."
                        ),
                    )
                self._error_streaks[name] = 0
                continue

            streak = self._error_streaks.get(name, 0) + 1
            self._error_streaks[name] = streak
            if streak < _ERROR_STREAK_THRESHOLD:
                continue

            # Attempt the known repair exactly once per streak (at the
            # crossing tick) — re-probing every subsequent tick would be
            # unbounded subprocess overhead for a condition that, once
            # confirmed absent, won't change tick-to-tick.
            if streak == _ERROR_STREAK_THRESHOLD:
                repair = self._known_repairs.get(name)
                if repair is not None:
                    repaired = await repair()
                    if repaired:
                        logger.warning(
                            "Self-repair actuator: auto-repaired %r for "
                            "persistent-error loop %r (%d consecutive error "
                            "heartbeats)",
                            repaired,
                            name,
                            streak,
                        )
                        await self._bus.publish(
                            HydraFlowEvent(
                                type=EventType.SYSTEM_ALERT,
                                data={
                                    "kind": "loop_self_repair",
                                    "source": "health_monitor",
                                    "worker": name,
                                    "repaired": repaired,
                                    "streak": streak,
                                },
                            )
                        )
                        self._error_streaks[name] = 0
                        continue

            # Unknown pattern (or the known repair found nothing to
            # repair) — file/refresh one deduped issue naming the loop.
            rollup = self._persistent_error_rollup(prs, state)
            has_pattern = name in self._known_repairs
            title = f"loop-persistent-error: {name} is failing every cycle"
            body = (
                f"## Background loop persistent-error actuator tripped\n\n"
                f"`{name}` has reported an `error` heartbeat for "
                f"`{streak}` consecutive cycles (threshold "
                f"`{_ERROR_STREAK_THRESHOLD}`).\n\n"
                f"- Last heartbeat: `{last_run}`\n"
                f"- Known auto-repair pattern: `"
                f"{'attempted — no matching condition found' if has_pattern else 'none registered for this loop'}"
                f"`\n\n"
                f"### Operator playbook\n"
                f"1. Check orchestrator logs for `{name}`'s recent cycle "
                f"exceptions (heartbeat details carry no error message).\n"
                f"2. If this is a new recurring failure class, consider "
                f"adding an entry to `HealthMonitorLoop._known_repairs`.\n\n"
                f"_Auto-filed by HydraFlow `health_monitor` "
                f"(persistent-error self-repair actuator, #10140)._"
            )
            issue_number = await rollup.ensure(name, title=title, body=body)
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "kind": "loop_persistent_error",
                        "source": "health_monitor",
                        "worker": name,
                        "issue": issue_number,
                        "streak": streak,
                    },
                )
            )

    async def _repo_probe(self, slug: str) -> bool | None:
        """Bounded, fail-open existence probe for a managed-repo slug.

        Delegates to the injected :class:`RepoProber` (production default
        :class:`DefaultRepoProber`). Extracted from this loop in #10140 so
        the raw ``git ls-remote`` spawn lives outside ``*_loop.py`` (sandbox
        seam guard) and the sandbox/MockWorld can inject a fake to air-gap
        it. Contract unchanged: ``True`` (reachable), ``False`` (confirmed
        404 — safe to prune), or ``None`` (ambiguous: timeout,
        circuit-breaker-open, network/auth hiccup — never treated as a 404,
        so a transient failure can never prune a healthy entry).
        """
        return await self._repo_prober.probe(slug)

    async def _repair_principles_audit_404_repo(self) -> str | None:
        """Known auto-repair: prune a ``managed_repos`` entry whose repo 404s.

        Concrete first case (#10140): PrinciplesAuditLoop keeps failing
        because one ``managed_repos`` entry points at a repo that no
        longer exists (or is unreachable) on GitHub —
        ``_refresh_checkout``'s ``git clone``/``fetch`` fails every cycle.
        Probes each ENABLED entry with a bounded, fail-open ``git
        ls-remote`` (:meth:`_repo_probe` — never trips on a network blip
        or auth hiccup, only a confirmed 404) and disables
        (``enabled=False``) the first confirmed-gone repo — the same
        operator kill-switch semantics ``ManagedRepo.enabled`` already
        documents, so the repair is visible in config and reversible
        (re-enable once the repo is restored/renamed).

        Returns the pruned slug, or ``None`` if every enabled entry still
        resolves (nothing to repair this tick — falls through to generic
        issue filing).
        """
        config = self._config
        managed = list(config.managed_repos)
        for i, mr in enumerate(managed):
            if not mr.enabled:
                continue
            exists = await self._repo_probe(mr.slug)
            if exists is False:
                managed[i] = mr.model_copy(update={"enabled": False})
                object.__setattr__(config, "managed_repos", managed)
                logger.warning(
                    "Self-repair: disabled managed_repos entry %r — repo "
                    "404 confirmed via `git ls-remote`",
                    mr.slug,
                )
                return mr.slug
        return None
