"""Background worker loop — health monitor with safe auto-adjustment.

Periodically evaluates pipeline health metrics, applies safe session-scoped
parameter adjustments within bounded ranges, writes a decision audit trail,
and files HITL recommendations for problems outside the safe adjustment range.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import Credentials, HydraFlowConfig
from dedup_store import DedupStore
from repo_existence_prober import DefaultRepoProber

from ._adjust import HealthMonitorAdjustmentMixin
from ._common import (
    PendingAdjustment,
)
from ._errors import HealthMonitorPersistentErrorMixin
from ._freshness import HealthMonitorFreshnessMixin
from ._heavy import HealthMonitorHeavyPassMixin
from ._hitl import HealthMonitorHitlMixin
from ._stall import HealthMonitorStallMixin
from ._vitals import HealthMonitorFleetVitalsMixin

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bg_worker_manager import BGWorkerManager
    from ports import ObservabilityPort, PRPort
    from repo_existence_prober import RepoProber
    from retrospective_queue import RetrospectiveQueue
    from state import StateTracker

logger = logging.getLogger("hydraflow.health_monitor_loop")

# ---------------------------------------------------------------------------
# HealthMonitorLoop
# ---------------------------------------------------------------------------


class HealthMonitorLoop(
    HealthMonitorAdjustmentMixin,
    HealthMonitorFleetVitalsMixin,
    HealthMonitorFreshnessMixin,
    HealthMonitorHeavyPassMixin,
    HealthMonitorHitlMixin,
    HealthMonitorPersistentErrorMixin,
    HealthMonitorStallMixin,
    BaseBackgroundLoop,
):
    """Monitors pipeline health metrics, auto-adjusts bounded config parameters,
    records decisions, and files HITL recommendations for unsafe changes.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        deps: LoopDeps,
        *,
        prs: PRPort | None = None,
        verification_window: int = 20,
        retrospective_queue: RetrospectiveQueue | None = None,
        state: StateTracker | None = None,
        bg_workers: BGWorkerManager | None = None,
        observability: ObservabilityPort | None = None,
        credentials: Credentials | None = None,
        repo_prober: RepoProber | None = None,
    ) -> None:
        super().__init__(
            worker_name="health_monitor",
            config=config,
            deps=deps,
        )
        self._prs = prs
        self._verification_window = verification_window
        self._retrospective_queue = retrospective_queue
        self._decisions_dir: Path = config.memory_dir
        # Credentials for the stale-code check's own bounded `git fetch`
        # (issue #9596) — this loop hosts its own pre-read fetch so the
        # commits-behind snapshot it consumes (git_revision.get_commits_behind,
        # #9663) is fresh, not the possibly-stale local tracking ref.
        self._credentials: Credentials = credentials or Credentials()
        # Repo-existence probe for the persistent-error self-repair actuator's
        # ``principles_audit`` 404-prune (#10140). Extracted behind a
        # ``RepoProber`` seam so the raw ``git ls-remote`` spawn lives outside
        # ``*_loop.py`` (sandbox seam guard) and the sandbox/MockWorld can
        # inject a fake, air-gapping it. Self-defaults so production wiring
        # (service_registry) needs no change.
        self._repo_prober: RepoProber = repo_prober or DefaultRepoProber(
            self._credentials.gh_token, config.repo_root
        )
        # §12.1 dead-man-switch inputs — ``state`` is available at
        # service-registry time; ``bg_workers`` is built after the loop
        # registry, so orchestrator injects it via ``set_bg_workers``.
        self._state: StateTracker | None = state
        self._bg_workers: BGWorkerManager | None = bg_workers
        self._obs: ObservabilityPort | None = observability
        # Dedup for the dead-man-switch so we file one sanity-loop-stalled
        # issue per stall event, not one per health_monitor tick.
        self._sanity_stall_dedup = DedupStore(
            "health_monitor_sanity_stall",
            config.data_root / "dedup" / "health_monitor_sanity_stall.json",
        )
        # Activity-based health (G5): a sanity loop that ticks but never
        # scans any workers (e.g. silently no-oping) updates its heartbeat
        # without doing real work; the heartbeat-only check would never
        # fire. Track consecutive ticks where workers_scanned == 0 — when
        # it crosses _SANITY_NOOP_STREAK_THRESHOLD we file the same stall
        # escalation as a missed heartbeat.
        self._sanity_noop_streak: int = 0
        self._pending: list[PendingAdjustment] = []
        self._last_log_scan: datetime | None = None
        # Heavy-pass cadence gate (#10652). The loop now ticks on the fast
        # stall-sweep cadence (``_get_default_interval``), but the ~9 heavy
        # caretaker checks in ``_run_heavy_pass`` still run at most once per
        # ``health_monitor_interval``. ``None`` ⇒ never run ⇒ boot runs a full
        # pass, matching the pre-decoupling first-cycle behaviour.
        self._last_heavy_pass_ts: datetime | None = None
        # Dedup for the wiki-freshness dead-man-switch — file one wiki-stale
        # issue per stall event; clear on recovery.
        self._wiki_stall_dedup = DedupStore(
            "health_monitor_wiki_stall",
            config.data_root / "dedup" / "health_monitor_wiki_stall.json",
        )
        # Generic loop-stall sweep markers (restart-attempted / issue-filed
        # per worker per stall event); cleared on that worker's recovery.
        self._worker_stall_dedup = DedupStore(
            "health_monitor_worker_stall",
            config.data_root / "dedup" / "health_monitor_worker_stall.json",
        )
        # Dedup for the stale-code dead-man-switch (#9596) — file one
        # factory-stale-code issue per stall event; clear on recovery.
        self._stale_code_dedup = DedupStore(
            "health_monitor_stale_code",
            config.data_root / "dedup" / "health_monitor_stale_code.json",
        )
        # Persistent-error self-repair actuator (#10140) — per-worker
        # consecutive-error-heartbeat streak, in-memory only (mirrors
        # `_sanity_noop_streak`'s same tradeoff: a process restart resets
        # the count, an acceptable bound for this v1 slice).
        self._error_streaks: dict[str, int] = {}
        # Known auto-repairable failure patterns, keyed by worker name.
        # Each repair returns a short description of what it fixed (used in
        # the SYSTEM_ALERT + log line), or None when it found nothing to
        # repair this tick (falls through to the generic issue-filing
        # path). v1 has exactly one entry — the concrete #10140 case.
        self._known_repairs: dict[str, Callable[[], Awaitable[str | None]]] = {
            "principles_audit": self._repair_principles_audit_404_repo,
        }

    def set_bg_workers(self, bg_workers: BGWorkerManager) -> None:
        """Late-binding for the post-ctor BGWorkerManager wiring."""
        self._bg_workers = bg_workers

    def _get_default_interval(self) -> int:
        """Poll cadence for the loop's *fast* path — the restart-first stall
        sweep (#10652).

        The sweep exists to remediate exactly the stalls
        ``TrustFleetSanityLoop`` alerts on; if it only ran on the shared
        ``health_monitor_interval`` (7200s) the alert could fire, be triaged,
        and be closed several times over before remediation ever ran — the
        churn documented on #10652. Ticking at (or faster than) the sanity
        loop's own re-check cadence keeps remediation abreast of the alert.

        The ~9 heavy caretaker checks keep their ``health_monitor_interval``
        cadence regardless — ``_do_work`` gates them behind
        ``_should_run_heavy_pass`` — so the faster tick costs nothing beyond
        the cheap sweep. ``trust_fleet_sanity_interval`` is bounded at 3600s
        (< the 7200s ``health_monitor_interval`` default), so this never makes
        the loop poll slower than it did before the decoupling.
        """
        return self._config.trust_fleet_sanity_interval

    @property
    def _outcomes_path(self) -> Path:
        return self._config.memory_dir / "outcomes.jsonl"

    @property
    def _scores_path(self) -> Path:
        return self._config.memory_dir / "item_scores.json"

    @property
    def _failures_path(self) -> Path:
        # Repo-scoped (ADR-0021 D2) — must match HarnessInsightStore's writer.
        return self._config.repo_memory_dir / "harness_failures.jsonl"

    async def _do_work(self) -> dict[str, Any] | None:
        """Execute one health-monitor cycle.

        Two cadences share this loop (#10652):

        * The **fast path** — the restart-first stall sweep
          (``_check_worker_staleness``) — runs on **every** tick. The loop
          polls on the fast ``_get_default_interval`` (aligned with
          ``TrustFleetSanityLoop``'s re-check cadence), so remediation for a
          stalled loop like ``staging_bisect`` fires close to the sanity
          loop's staleness alert instead of up to a full
          ``health_monitor_interval`` later.
        * The **heavy pass** — the ~9 caretaker checks in
          ``_run_heavy_pass`` — keeps its ``health_monitor_interval`` cadence,
          gated by ``_should_run_heavy_pass``. Its issue-filing cadence, cost
          and Sentry-metric volume are therefore unchanged.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.health_monitor_loop_enabled:
            return {"status": "config_disabled"}

        # Fast path — runs every tick. Generic stall sweep: restart-first for
        # any silent registry loop, and the remediation half of the alert →
        # remediation loop ``TrustFleetSanityLoop`` opens (#10652). It must
        # poll at least as often as that alert re-checks, so it lives on the
        # fast tick rather than behind the heavy-pass gate. Deliberately
        # unwrapped (unlike the grandfathered dead-man-switches in the heavy
        # pass): a sweep failure propagates to the base cycle handler, which
        # owns credit/auth classification and surfaces a visible cycle error
        # instead of a debug line — the tick retries.
        await self._check_worker_staleness()

        # Persistent-error actuator (#10140): a loop that keeps TICKING but keeps
        # FAILING — complements the silent-heartbeat staleness sweep, so it runs on
        # the SAME fast tick (not behind the 2h heavy-pass gate) or persistent
        # worker errors would take up to health_monitor_interval to be filed
        # (#10652). Deliberately unwrapped — a genuine bug here surfaces as a
        # visible cycle error and retries, not a debug line.
        await self._check_persistent_worker_errors()

        if not self._should_run_heavy_pass():
            # Sweep-only cycle: a compact, distinct status (NOT zeroed trend
            # metrics, which would read as a real 0% first-pass rate on the
            # dashboards). The heavy pass keeps its own 2h cadence below.
            return {"status": "stall_sweep", "heavy_pass": False}

        return await self._run_heavy_pass()

    def _should_run_heavy_pass(self) -> bool:
        """True when the ~9 heavy caretaker checks are due (#10652).

        Boot (``_last_heavy_pass_ts`` unset) always runs a full pass. After
        that the heavy body runs at most once per ``health_monitor_interval``
        even though the loop ticks on the faster sweep cadence. ``getattr``
        guards ``__new__``-bypassed test scaffolding that skips ``__init__``
        (PR #8460 post-mortem).
        """
        last = getattr(self, "_last_heavy_pass_ts", None)
        if last is None:
            return True
        elapsed_s = (datetime.now(UTC) - last).total_seconds()
        return elapsed_s >= self._config.health_monitor_interval
