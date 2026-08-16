"""Background worker loop — health monitor with safe auto-adjustment.

Periodically evaluates pipeline health metrics, applies safe session-scoped
parameter adjustments within bounded ranges, writes a decision audit trail,
and files HITL recommendations for problems outside the safe adjustment range.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from audit_chain import AuditChain
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import Credentials, HydraFlowConfig
from dedup_store import DedupStore
from event_loop_watchdog import (
    clear_stall_marker,
    event_loop_stall_marker_path,
    read_stall_marker,
)
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
from git_revision import get_commits_behind
from repo_existence_prober import DefaultRepoProber
from rollup_issue_manager import RollupIssueManager
from subprocess_util import run_subprocess

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bg_worker_manager import BGWorkerManager
    from ports import ObservabilityPort, PRPort
    from repo_existence_prober import RepoProber
    from retrospective_queue import RetrospectiveQueue
    from state import StateTracker

logger = logging.getLogger("hydraflow.health_monitor_loop")

# ---------------------------------------------------------------------------
# Tunable parameter bounds (inclusive)
# ---------------------------------------------------------------------------

TUNABLE_BOUNDS: dict[str, tuple[int, int]] = {
    "max_quality_fix_attempts": (1, 5),
    "agent_timeout": (120, 900),
}

# ---------------------------------------------------------------------------
# Adjustment rules: (metric_expr, parameter, direction_delta)
# Each rule is checked in order; at most one adjustment per parameter per cycle.
# ---------------------------------------------------------------------------

_AdjustmentRule = tuple[str, str, int]  # (condition_key, parameter, step)

ADJUSTMENT_RULES: list[_AdjustmentRule] = [
    ("first_pass_rate_low", "max_quality_fix_attempts", +1),
    ("first_pass_rate_high", "max_quality_fix_attempts", -1),
]

# Thresholds used in condition evaluation
_FIRST_PASS_LOW = 0.2
_FIRST_PASS_HIGH = 0.9
_SURPRISE_HIGH = 0.3
_HITL_HIGH = 0.4
_AVG_SCORE_LOW = 0.4
_STALE_COUNT_HIGH = 5

# HealthMonitor dead-man-switch for TrustFleetSanityLoop (spec §12.1).
# Files a `hydraflow-find` + `sanity-loop-stalled` issue when the sanity
# loop's heartbeat is older than this multiple of its configured interval.
_SANITY_STALL_MULTIPLIER = 3

# Files the same stall when the sanity loop has ticked but reported zero
# workers_scanned for this many consecutive ticks (G5 — activity-based
# health). Catches silent no-op bugs where heartbeat is fresh but the
# loop did no real work.
_SANITY_NOOP_STREAK_THRESHOLD = 3

# Dedup marker recording that the restart-first path already cancelled and
# recreated the sanity loop for the current stall event — the next stall
# tick escalates to an issue instead of restart-thrashing. Cleared with the
# stall dedup key on recovery.
_SANITY_RESTART_KEY = "health_monitor:trust_fleet_sanity:restart-attempted"

# Generic stall sweep across registry loops: a heartbeat older than
# multiplier × interval + cycle_timeout means the loop task is wedged
# outside its watchdog window. The cycle_timeout term keeps a legitimately
# long LLM cycle (heartbeat only refreshes between cycles) from being
# false-restarted.
_WORKER_STALL_MULTIPLIER = 3

# Loops excluded from the generic sweep. trust_fleet_sanity has its own
# §12.1 dead-man-switch above (with G5 no-op detection the generic sweep
# lacks); double coverage would double-restart and double-file.
# health_monitor runs the sweep itself — self-cancelling mid-cycle (stale
# persisted heartbeat after long orchestrator downtime) is harm without
# benefit, and a truly wedged health_monitor can't sweep itself anyway.
_WORKER_STALL_EXCLUDED = frozenset({"trust_fleet_sanity", "health_monitor"})

# Bounded pre-read `git fetch` timeout for the stale-code dead-man-switch
# (#9596). Short and fixed — a single-branch fetch, not a full clone; the
# check must degrade (skip the tick) rather than hang the health-monitor
# cycle when the remote is unreachable.
_STALE_CODE_FETCH_TIMEOUT_SECS = 30.0

# Persistent-error self-repair actuator (#10140, follow-up to #9854's
# read-only health harness). A registry loop whose heartbeat reports
# `error` for this many CONSECUTIVE health_monitor ticks either gets a
# known auto-repair applied or one deduped `hydraflow-find` issue naming
# it filed — the actuator half of the harness, so a repeatedly-failing
# loop self-heals (or is at least surfaced) instead of waiting for a human
# to eyeball the dashboard. Mirrors `_SANITY_NOOP_STREAK_THRESHOLD`'s
# per-tick (not per-underlying-cycle) counting convention: simple, already
# proven in this file, and testable without needing to fake a target
# loop's own cycle cadence.
_ERROR_STREAK_THRESHOLD = 3

# Loops excluded from persistent-error actuation. health_monitor cannot
# meaningfully self-diagnose (mirrors `_WORKER_STALL_EXCLUDED`);
# trust_fleet_sanity already has its own `tick_error_ratio` anomaly
# detector (spec §12.1) for this exact failure class (a loop that ticks
# but keeps failing) — double coverage would double-file.
_PERSISTENT_ERROR_EXCLUDED = frozenset({"trust_fleet_sanity", "health_monitor"})

# RollupIssueManager namespace for the persistent-error actuator's
# generic (unknown-pattern) issue-filing fallback.
_PERSISTENT_ERROR_NAMESPACE = "health_monitor_persistent_error"

# ---------------------------------------------------------------------------
# Trend metrics
# ---------------------------------------------------------------------------


class TrendMetrics:
    """Computed health trend metrics for one monitor cycle."""

    def __init__(
        self,
        first_pass_rate: float,
        avg_memory_score: float,
        surprise_rate: float,
        hitl_escalation_rate: float,
        stale_item_count: int,
        total_outcomes: int,
    ) -> None:
        self.first_pass_rate = first_pass_rate
        self.avg_memory_score = avg_memory_score
        self.surprise_rate = surprise_rate
        self.hitl_escalation_rate = hitl_escalation_rate
        self.stale_item_count = stale_item_count
        self.total_outcomes = total_outcomes

    def active_conditions(self) -> list[str]:
        """Return a list of active condition keys for adjustment rule matching."""
        conditions: list[str] = []
        if self.first_pass_rate < _FIRST_PASS_LOW:
            conditions.append("first_pass_rate_low")
        if self.first_pass_rate > _FIRST_PASS_HIGH:
            conditions.append("first_pass_rate_high")
        return conditions


# ---------------------------------------------------------------------------
# Decision audit trail
# ---------------------------------------------------------------------------


def _next_decision_id(_decisions_dir: Path) -> str:
    """Return a unique decision ID using UUID."""
    return f"adj-{uuid.uuid4().hex[:8]}"


def _write_decision(decisions_dir: Path, record: dict[str, Any]) -> None:
    try:
        decisions_dir.mkdir(parents=True, exist_ok=True)
        # Hash-chained append (CH-1, #9729): stamps prev_hash/record_hash so
        # out-of-band edits to the decision trail are detectable.
        AuditChain(decisions_dir / "decisions.jsonl").append(record)
    except (OSError, ValueError):
        # Disk full, permission, or other I/O error — plus ValueError from
        # the chain's serialization paths (incl. json.JSONDecodeError from
        # secret scrubbing). The health monitor loop must not abort its tick
        # over a single failed decision write.
        logger.warning(
            "Failed to persist health decision to %s", decisions_dir, exc_info=True
        )


def _load_decisions(decisions_dir: Path) -> list[dict[str, Any]]:
    decisions_file = decisions_dir / "decisions.jsonl"
    if not decisions_file.exists():
        return []
    try:
        lines = decisions_file.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        rec: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            rec = json.loads(line)
        if rec:
            records.append(rec)
    return records


def _update_decision(
    decisions_dir: Path, decision_id: str, updates: dict[str, Any]
) -> None:
    """Atomically rewrite decisions.jsonl updating the record matching decision_id.

    This is the sanctioned amendment path for the decision audit trail
    (verification outcomes are back-filled after the observation window).
    ``AuditChain.rewrite`` re-chains the hash fields from the amended record
    forward, so the trail stays verifiable while out-of-band edits still
    break the chain (CH-1, #9729).
    """
    # Anti-laundering guard: _load_decisions silently drops unparseable
    # lines, so rewriting a BROKEN stream would erase tamper evidence
    # before the RunsGC verifier ever sees it. Amendments only proceed on
    # a clean chain; a broken one is left byte-for-byte for detection.
    decisions_file = decisions_dir / "decisions.jsonl"
    if decisions_file.exists() and not AuditChain(decisions_file).verify().ok:
        logger.error(
            "decisions.jsonl chain is broken — amendment for %s aborted "
            "to preserve tamper evidence (RunsGC will alert)",
            decision_id,
        )
        return
    records = _load_decisions(decisions_dir)
    updated = False
    for record in records:
        if record.get("decision_id") == decision_id:
            record.update(updates)
            updated = True
            break
    if not updated:
        return
    decisions_dir.mkdir(parents=True, exist_ok=True)
    AuditChain(decisions_dir / "decisions.jsonl").rewrite(records)


# ---------------------------------------------------------------------------
# Metric computation helpers
# ---------------------------------------------------------------------------


def compute_trend_metrics(
    outcomes_path: Path,
    scores_path: Path,
    failures_path: Path,
    *,
    window: int = 50,
) -> TrendMetrics:
    """Load recent data and compute all trend metrics."""
    # --- outcomes.jsonl ---
    successes = 0
    total_outcomes = 0
    if outcomes_path.exists():
        try:
            lines = outcomes_path.read_text(encoding="utf-8").strip().splitlines()
            tail = lines[-window:] if len(lines) > window else lines
            for line in tail:
                try:
                    rec = json.loads(line)
                    total_outcomes += 1
                    if rec.get("outcome") == "success":
                        successes += 1
                except Exception:  # noqa: BLE001
                    logger.debug("Skipping malformed outcomes line", exc_info=True)
        except OSError:
            pass

    first_pass_rate = (successes / total_outcomes) if total_outcomes > 0 else 0.0

    # --- item_scores.json ---
    avg_memory_score = 0.0
    stale_item_count = 0
    if scores_path.exists():
        try:
            raw: dict[str, Any] = json.loads(scores_path.read_text(encoding="utf-8"))
            scores = list(raw.values())
            if scores:
                score_vals = [float(s.get("score", 0.5)) for s in scores]
                avg_memory_score = sum(score_vals) / len(score_vals)
                stale_item_count = sum(
                    1
                    for s in scores
                    if float(s.get("score", 0.5)) < 0.3
                    and int(s.get("appearances", 0)) >= 5
                )
        except Exception:  # noqa: BLE001
            # Signal parse failure via a sentinel negative count (#6470) so
            # callers can distinguish "no data" from "corrupt file".
            logger.warning(
                "Failed to parse item_scores.json — score metrics unavailable",
                exc_info=True,
            )
            avg_memory_score = 0.0
            stale_item_count = -1

    # --- harness_failures.jsonl — surprise & hitl rates ---
    total_failures = 0
    surprise_count = 0
    hitl_count = 0
    if failures_path.exists():
        try:
            lines = failures_path.read_text(encoding="utf-8").strip().splitlines()
            tail = lines[-window:] if len(lines) > window else lines
            total_failures = len(tail)
            for line in tail:
                try:
                    rec = json.loads(line)
                    if rec.get("category") == "hitl_escalation":
                        hitl_count += 1
                    # Surprise is detected in the memory trail, not here;
                    # we approximate via "review_rejection" as unexpected
                    if rec.get("category") == "review_rejection":
                        surprise_count += 1
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "Skipping malformed harness_failures line",
                        exc_info=True,
                    )
        except OSError:
            logger.warning("Failed to read harness_failures.jsonl", exc_info=True)

    surprise_rate = (surprise_count / total_failures) if total_failures > 0 else 0.0
    hitl_escalation_rate = (hitl_count / total_failures) if total_failures > 0 else 0.0

    return TrendMetrics(
        first_pass_rate=first_pass_rate,
        avg_memory_score=avg_memory_score,
        surprise_rate=surprise_rate,
        hitl_escalation_rate=hitl_escalation_rate,
        stale_item_count=stale_item_count,
        total_outcomes=total_outcomes,
    )


# ---------------------------------------------------------------------------
# Pending adjustment tracking (for outcome verification)
# ---------------------------------------------------------------------------


class PendingAdjustment:
    """Tracks a single applied auto-adjustment awaiting outcome verification."""

    def __init__(
        self,
        decision_id: str,
        parameter: str,
        before: int,
        after: int,
        metric_name: str,
        metric_value: float,
        outcomes_at_adjustment: int,
    ) -> None:
        self.decision_id = decision_id
        self.parameter = parameter
        self.before = before
        self.after = after
        self.metric_name = metric_name
        self.metric_value = metric_value
        self.outcomes_at_adjustment = outcomes_at_adjustment


# ---------------------------------------------------------------------------
# HealthMonitorLoop
# ---------------------------------------------------------------------------


class HealthMonitorLoop(BaseBackgroundLoop):
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

    async def _run_heavy_pass(self) -> dict[str, Any] | None:
        """Run the ~9 heavy caretaker checks and emit trend metrics (#10652).

        Stamps ``_last_heavy_pass_ts`` *before* the body runs so a heavy pass
        that raises retries on its own ``health_monitor_interval`` cadence
        rather than thrashing on every fast sweep tick.
        """
        self._last_heavy_pass_ts = datetime.now(UTC)

        # Dead-man-switch: detect a stalled TrustFleetSanityLoop (spec §12.1).
        try:
            await self._check_sanity_loop_staleness()
        except Exception:  # noqa: BLE001
            logger.debug("sanity-loop stall check failed", exc_info=True)

        # Dead-man-switch: detect a stalled RepoWikiLoop via log.jsonl mtime.
        try:
            await self._check_wiki_freshness()
        except Exception:  # noqa: BLE001
            logger.debug("wiki-freshness check failed", exc_info=True)

        # Dead-man-switch: detect the running instance loading stale code
        # (#9596) relative to origin/<base_branch>.
        try:
            await self._check_stale_code()
        except Exception:
            logger.debug("stale-code check failed", exc_info=True)

        # Escalate a prior synchronous event-loop freeze recorded by the
        # thread-level EventLoopWatchdog (#9552). The watchdog thread cannot
        # file issues itself — Ports are async and run on the very loop that
        # froze — so it leaves a marker this (now-healthy) loop consumes.
        try:
            await self._check_event_loop_stall()
        except Exception:
            logger.debug("event-loop stall check failed", exc_info=True)

        metrics = compute_trend_metrics(
            self._outcomes_path, self._scores_path, self._failures_path
        )
        logger.info(
            "Health monitor cycle: first_pass_rate=%.2f avg_score=%.2f "
            "surprise_rate=%.2f hitl_rate=%.2f stale_items=%d",
            metrics.first_pass_rate,
            metrics.avg_memory_score,
            metrics.surprise_rate,
            metrics.hitl_escalation_rate,
            metrics.stale_item_count,
        )

        # #11391 fleet vitals (SHADOW): bands + hysteresis over the fleet
        # metrics just logged. Founding incident: hitl_rate=0.74 /
        # first_pass_rate=0.00 went out at INFO while the light-tier
        # cascade ran — the fleet had no verdict function. Fail-soft.
        try:
            await self._run_fleet_vitals(metrics)
        except (OSError, RuntimeError, TypeError, ValueError, KeyError):
            logger.debug("fleet-vitals evaluation failed", exc_info=True)

        self._verify_pending_adjustments(metrics)
        adjustments_made = self._apply_adjustments(metrics)
        await self._file_hitl_recommendations(metrics)

        gap_count = self._run_knowledge_gap_count()
        log_result = await self._run_log_ingestion_cycle()
        await self._run_harness_auto_file_cycle()
        await self._run_harness_suggestion_ingestion_cycle()
        self._run_proposal_verification_cycle()
        self._run_cross_project_pattern_cycle()

        self._emit_sentry_metrics(
            metrics,
            gap_count=gap_count,
            adjustment_count=adjustments_made,
            log_patterns_total=log_result.total_patterns if log_result else 0,
            log_patterns_novel=log_result.filed if log_result else 0,
            log_patterns_escalating=log_result.escalated if log_result else 0,
            hitl_recommendations_count=self._count_unactioned_hitl_recommendations(),
        )

        return {
            "first_pass_rate": round(metrics.first_pass_rate, 4),
            "avg_memory_score": round(metrics.avg_memory_score, 4),
            "surprise_rate": round(metrics.surprise_rate, 4),
            "hitl_escalation_rate": round(metrics.hitl_escalation_rate, 4),
            "stale_item_count": metrics.stale_item_count,
            "adjustments_made": adjustments_made,
            "total_outcomes": metrics.total_outcomes,
            "heavy_pass": True,
        }

    # ------------------------------------------------------------------
    # Extracted sub-tasks (each independently testable)
    # ------------------------------------------------------------------

    def _run_knowledge_gap_count(self) -> int:
        """Knowledge gap detection retired with memory_scoring in Phase 3 cutover."""
        return 0

    async def _run_log_ingestion_cycle(self) -> Any | None:
        """Parse logs, detect patterns, enrich, and file novel patterns."""
        try:
            from log_ingestion import (  # noqa: PLC0415
                detect_log_patterns,
                file_log_patterns,
                load_known_patterns,
                parse_log_files,
                save_known_patterns,
            )

            log_file = getattr(self._config, "log_file", None)
            if log_file:
                log_dir = Path(log_file).parent
            else:
                log_dir = self._config.data_root / "logs"

            if not log_dir.is_dir():
                return None

            entries = parse_log_files(log_dir, since=self._last_log_scan)
            patterns = detect_log_patterns(entries)
            known = load_known_patterns(self._config.memory_dir)

            # Enrich with EventBus context (best-effort)
            try:
                from log_ingestion import (
                    enrich_patterns_with_events,  # noqa: PLC0415
                )

                history = self._bus.get_history()
                event_dicts = [{"type": e.type.value, "data": e.data} for e in history]
                enrich_patterns_with_events(patterns, event_dicts)
            except Exception:  # noqa: BLE001
                # Best-effort enrichment — don't crash the cycle, but leave
                # a debug-level signal so operators can diagnose failing
                # event-dict construction (#6622).
                logger.debug("EventBus enrichment failed", exc_info=True)

            log_result = await file_log_patterns(
                patterns, known, self._config, self._obs
            )
            save_known_patterns(self._config.memory_dir, known)
            self._last_log_scan = datetime.now(UTC)

            logger.info(
                "Log ingestion: %d patterns, %d novel filed, %d escalated",
                log_result.total_patterns,
                log_result.filed,
                log_result.escalated,
            )
            return log_result
        except ImportError:
            return None
        except Exception:  # noqa: BLE001
            logger.debug("Log ingestion failed", exc_info=True)
            return None

    async def _run_harness_auto_file_cycle(self) -> None:
        """Auto-file harness insight suggestions."""
        try:
            from harness_insights import (  # noqa: PLC0415
                HarnessInsightStore,
                auto_file_suggestions,
            )

            store = HarnessInsightStore(self._config.repo_memory_dir)
            await auto_file_suggestions(store, self._config)
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("Harness auto-file failed", exc_info=True)

    async def _run_harness_suggestion_ingestion_cycle(self) -> None:
        """Read harness suggestions JSONL and file each as a memory item."""
        try:
            suggestions_path = (
                self._config.repo_memory_dir / "harness_suggestions.jsonl"
            )
            if not suggestions_path.exists():
                return

            from phase_utils import file_memory_suggestion  # noqa: PLC0415

            raw_suggestions = (
                suggestions_path.read_text(encoding="utf-8").strip().splitlines()
            )
            for line in raw_suggestions:
                try:
                    rec = json.loads(line)
                    principle = rec.get("suggestion", rec.get("title", ""))
                    rationale = (
                        f"Detected from {rec.get('occurrences', 0)} pipeline"
                        f" failures in category {rec.get('category', 'unknown')}"
                    )
                    failure_mode = (
                        f"Pipeline failure pattern: {rec.get('title', 'Unknown')}"
                    )
                    transcript = (
                        "MEMORY_SUGGESTION_START\n"
                        f"principle: {principle}\n"
                        f"rationale: {rationale}\n"
                        f"failure_mode: {failure_mode}\n"
                        "scope: hydraflow\n"
                        "MEMORY_SUGGESTION_END"
                    )
                    await file_memory_suggestion(
                        transcript,
                        "harness_insight",
                        "health_monitor",
                        self._config,
                    )
                except Exception:  # noqa: BLE001
                    continue
            # Clear processed suggestions so they are not re-ingested
            suggestions_path.write_text("", encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.debug("Harness suggestion ingestion failed", exc_info=True)

    def _run_proposal_verification_cycle(self) -> None:
        """Enqueue proposal verification or run inline fallback."""
        if self._retrospective_queue is not None:
            from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

            self._retrospective_queue.append(QueueItem(kind=QueueKind.VERIFY_PROPOSALS))
            return

        # Fallback: inline verification when queue not wired
        try:
            from review_insights import (  # noqa: PLC0415
                ReviewInsightStore,
                verify_proposals,
            )

            insight_store = ReviewInsightStore(self._config.repo_memory_dir)
            # Sample current_count over the configured review_insight_window so
            # it matches the baseline pre_count window (#9444). A hardcoded 50
            # vs a pre_count measured over review_insight_window (default 10)
            # made current_count >= pre_count permanently true for frequent
            # categories, perpetually re-filing false stale-insight HITL recs.
            records = insight_store.load_recent(self._config.review_insight_window)
            stale = verify_proposals(insight_store, records)
            for category in stale:
                # Informational HITL-recommendation status, not a warning — this
                # line floods the WARNING channel in production (~195 occ.) with
                # benign tuning-recommendation output (WS-05 log-hygiene).
                logger.info("HITL recommendation: stale review insight '%s'", category)
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("Proposal verification failed", exc_info=True)

    def _run_cross_project_pattern_cycle(self) -> None:
        """Detect log patterns shared across projects."""
        try:
            from log_ingestion import (  # noqa: PLC0415
                detect_cross_project_log_patterns,
                load_known_patterns,
            )

            project_patterns = {
                self._config.repo_slug: load_known_patterns(self._config.memory_dir)
            }
            cross_patterns = detect_cross_project_log_patterns(project_patterns)
            if cross_patterns:
                logger.info("Found %d cross-project log patterns", len(cross_patterns))
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.debug("Cross-project log pattern detection failed", exc_info=True)

    def _count_unactioned_hitl_recommendations(self) -> int:
        """Count unactioned HITL recommendations for Sentry metrics."""
        try:
            rec_path = self._config.data_path("memory", "hitl_recommendations.jsonl")
            if not rec_path.exists():
                return 0
            lines = rec_path.read_text(encoding="utf-8").strip().splitlines()
            return sum(
                1
                for line in lines
                if line.strip() and not json.loads(line).get("actioned", False)
            )
        except Exception:  # noqa: BLE001
            return 0

    # ------------------------------------------------------------------
    # Safe auto-adjustment
    # ------------------------------------------------------------------

    def _apply_adjustments(self, metrics: TrendMetrics) -> int:
        """Apply ADJUSTMENT_RULES against active conditions. Returns count applied."""
        active = set(metrics.active_conditions())
        if not active:
            return 0

        applied = 0
        for condition_key, parameter, step in ADJUSTMENT_RULES:
            if condition_key not in active:
                continue
            try:
                current_val = int(getattr(self._config, parameter))
                lo, hi = TUNABLE_BOUNDS[parameter]
                new_val = current_val + step
                new_val = max(lo, min(hi, new_val))
                if new_val == current_val:
                    continue

                object.__setattr__(self._config, parameter, new_val)

                decision_id = _next_decision_id(self._decisions_dir)
                evidence = (
                    f"{metrics.total_outcomes - int(metrics.first_pass_rate * metrics.total_outcomes)}"
                    f"/{metrics.total_outcomes} issues needed retry"
                )
                record: dict[str, Any] = {
                    "decision_id": decision_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "type": "auto_adjust",
                    "parameter": parameter,
                    "before": current_val,
                    "after": new_val,
                    "reason": (
                        f"{condition_key.replace('_', ' ')} "
                        f"{metrics.first_pass_rate:.2f} "
                        f"{'below' if step > 0 else 'above'} "
                        f"{_FIRST_PASS_LOW if step > 0 else _FIRST_PASS_HIGH} threshold"
                    ),
                    "evidence_summary": evidence,
                    "outcome_verified": None,
                }
                _write_decision(self._decisions_dir, record)
                logger.info(
                    "Auto-adjusted %s: %d → %d (%s)",
                    parameter,
                    current_val,
                    new_val,
                    condition_key,
                )
                if self._obs is not None:
                    self._obs.breadcrumb(
                        "memory.auto_adjust",
                        f"Adjusted {parameter}: {current_val} → {new_val}",
                        level="warning",
                        parameter=parameter,
                        before=current_val,
                        after=new_val,
                        reason=record["reason"],
                    )

                self._pending.append(
                    PendingAdjustment(
                        decision_id=decision_id,
                        parameter=parameter,
                        before=current_val,
                        after=new_val,
                        metric_name="first_pass_rate",
                        metric_value=metrics.first_pass_rate,
                        outcomes_at_adjustment=metrics.total_outcomes,
                    )
                )
                applied += 1
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Auto-adjustment failed for parameter %s",
                    parameter,
                    exc_info=True,
                )

        return applied

    # ------------------------------------------------------------------
    # Outcome verification
    # ------------------------------------------------------------------

    def _count_outcomes_since(self, since_count: int) -> int:
        """Return total outcomes accumulated since a prior snapshot count."""
        try:
            if not self._outcomes_path.exists():
                return 0
            lines = self._outcomes_path.read_text(encoding="utf-8").strip().splitlines()
            return max(0, len(lines) - since_count)
        except Exception:  # noqa: BLE001
            return 0

    def _verify_pending_adjustments(self, metrics: TrendMetrics) -> None:
        """Check if any pending adjustments have enough follow-on outcomes for verification."""
        still_pending: list[PendingAdjustment] = []
        for adj in self._pending:
            try:
                new_outcomes = self._count_outcomes_since(adj.outcomes_at_adjustment)
                if new_outcomes < self._verification_window:
                    still_pending.append(adj)
                    continue

                # Enough outcomes — evaluate
                new_metric_val = metrics.first_pass_rate
                old_metric_val = adj.metric_value
                improved_direction = adj.after > adj.before  # larger = more attempts

                if improved_direction:
                    # We increased attempts hoping to improve first_pass_rate
                    improved = new_metric_val > old_metric_val + 0.05
                    worsened = new_metric_val < old_metric_val - 0.05
                else:
                    # We reduced attempts hoping it stays high
                    improved = new_metric_val >= old_metric_val - 0.05
                    worsened = new_metric_val < old_metric_val - 0.1

                if worsened:
                    # Revert the adjustment
                    try:
                        object.__setattr__(self._config, adj.parameter, adj.before)
                        logger.warning(
                            "Reverting auto-adjustment %s for %s: metric worsened"
                            " (%.2f → %.2f)",
                            adj.decision_id,
                            adj.parameter,
                            old_metric_val,
                            new_metric_val,
                        )
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "Failed to revert %s for %s",
                            adj.decision_id,
                            adj.parameter,
                            exc_info=True,
                        )
                    outcome_verified = "reverted"
                elif improved:
                    outcome_verified = "improved"
                else:
                    outcome_verified = "neutral"

                _update_decision(
                    self._decisions_dir,
                    adj.decision_id,
                    {"outcome_verified": outcome_verified},
                )
                logger.info(
                    "Decision %s verified as %s",
                    adj.decision_id,
                    outcome_verified,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Verification check failed for decision %s",
                    adj.decision_id,
                    exc_info=True,
                )
                still_pending.append(adj)

        self._pending = still_pending

    # ------------------------------------------------------------------
    # HITL recommendations
    # ------------------------------------------------------------------

    async def _file_hitl_recommendations(self, metrics: TrendMetrics) -> None:
        """Write HITL recommendations to JSONL for unsafe problems needing human attention."""
        try:
            recommendations: list[tuple[str, float, str, str]] = []

            if metrics.surprise_rate > _SURPRISE_HIGH:
                recommendations.append(
                    (
                        "surprise_rate",
                        metrics.surprise_rate,
                        (
                            "High surprise rate indicates memory items are consistently "
                            "producing unexpected outcomes (high-score items failing or "
                            "low-score items succeeding). Manual curation may be needed."
                        ),
                        (
                            "Review item trails in `item_scores.json` for items classified "
                            "as `needs_curation`. Consider running `make compact` to evict "
                            "stale items and reset scores."
                        ),
                    )
                )

            if metrics.hitl_escalation_rate > _HITL_HIGH:
                recommendations.append(
                    (
                        "hitl_escalation_rate",
                        metrics.hitl_escalation_rate,
                        (
                            "High HITL escalation rate suggests systematic failures that "
                            "cannot be auto-recovered. Pipeline confidence is degraded."
                        ),
                        (
                            "Review recent `harness_failures.jsonl` entries categorized as "
                            "`hitl_escalation`. Update prompts or constraints to prevent "
                            "the most common escalation causes."
                        ),
                    )
                )

            if metrics.avg_memory_score < _AVG_SCORE_LOW:
                recommendations.append(
                    (
                        "avg_memory_score",
                        metrics.avg_memory_score,
                        (
                            "Average memory item score is critically low, indicating that "
                            "most memory items are not contributing to positive outcomes."
                        ),
                        (
                            "Run a full memory compaction pass to evict low-scoring items. "
                            "Review the memory digest for outdated or conflicting guidance."
                        ),
                    )
                )

            if metrics.stale_item_count > _STALE_COUNT_HIGH:
                recommendations.append(
                    (
                        "stale_item_count",
                        float(metrics.stale_item_count),
                        (
                            f"{metrics.stale_item_count} memory items have score < 0.3 "
                            "with 5+ appearances, indicating persistent low-value content."
                        ),
                        (
                            "Run `make compact` to auto-evict items below the eviction "
                            "threshold. Review remaining low-score items for manual pruning."
                        ),
                    )
                )

            for metric_name, value, observation, recommendation in recommendations:
                try:
                    title = (
                        f"[Health Monitor] {metric_name} at {value:.2f}"
                        " — recommendation"
                    )
                    body = self._build_hitl_body(
                        metric_name=metric_name,
                        value=value,
                        observation=observation,
                        recommendation=recommendation,
                        metrics=metrics,
                    )
                    try:
                        rec = {
                            "title": title,
                            "body": body,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "type": "recommendation",
                        }
                        rec_path = self._config.data_path(
                            "memory", "hitl_recommendations.jsonl"
                        )
                        rec_path.parent.mkdir(parents=True, exist_ok=True)
                        with rec_path.open("a") as f:
                            f.write(json.dumps(rec) + "\n")
                        # Informational status (a recommendation was filed), not a
                        # warning — downgraded from WARNING to stop flooding the
                        # production WARNING channel (WS-05 log-hygiene).
                        logger.info("HITL recommendation: %s", title)
                    except OSError:
                        logger.debug(
                            "Failed to write HITL recommendation", exc_info=True
                        )
                    # NB: filing a HITL recommendation is normal operation — it is
                    # already persisted to hitl_recommendations.jsonl and logged.
                    # It is NOT a code bug, so it is deliberately NOT captured to
                    # Sentry (Sentry's contract is real code bugs only).
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Failed to file HITL recommendation for %s",
                        metric_name,
                        exc_info=True,
                    )
        except Exception:  # noqa: BLE001
            logger.warning("_file_hitl_recommendations failed", exc_info=True)

    def _build_hitl_body(
        self,
        *,
        metric_name: str,
        value: float,
        observation: str,
        recommendation: str,
        metrics: TrendMetrics,
    ) -> str:
        config = self._config
        return (
            f"## Health Monitor Recommendation\n\n"
            f"**Metric:** `{metric_name}` = `{value:.4f}`\n\n"
            f"### Observation\n{observation}\n\n"
            f"### Current Config\n"
            f"- `max_quality_fix_attempts`: {config.max_quality_fix_attempts}\n"
            f"- `agent_timeout`: {config.agent_timeout}\n\n"
            f"### Evidence\n"
            f"- First-pass rate (last 50): `{metrics.first_pass_rate:.2%}`\n"
            f"- Avg memory score: `{metrics.avg_memory_score:.4f}`\n"
            f"- Surprise rate: `{metrics.surprise_rate:.2%}`\n"
            f"- HITL escalation rate: `{metrics.hitl_escalation_rate:.2%}`\n"
            f"- Stale items (score<0.3, ≥5 appearances): `{metrics.stale_item_count}`\n\n"
            f"### Recommendation\n{recommendation}\n"
        )

    # ------------------------------------------------------------------
    # Sentry metrics
    # ------------------------------------------------------------------

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
        )
        alarms = evaluate_fleet_vitals(
            state,
            reading,
            bands=FleetBands(
                hitl_rate_alarm=self._config.fleet_hitl_rate_alarm,
                hitl_rate_rearm=self._config.fleet_hitl_rate_rearm,
                first_pass_floor=self._config.fleet_first_pass_floor,
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

    # ------------------------------------------------------------------
    # Dead-man-switch for TrustFleetSanityLoop (spec §12.1)
    # ------------------------------------------------------------------

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
            f"- Hard restart was enabled at trip time: `{hard_restart}`\n\n"
            f"### Operator playbook\n"
            f"1. Open the stack dump above — the frozen loop thread's top "
            f"Python frame IS the offending synchronous call site.\n"
            f"2. Move that call off-loop (`asyncio.create_subprocess_exec`, "
            f"`run_in_executor`) and file/fix accordingly.\n"
            f"3. For recovery-in-place next time, consider enabling "
            f"`event_loop_watchdog_hard_restart` in the **System** tab "
            f"(requires a process supervisor with Restart=always).\n\n"
            f"_Auto-filed by HydraFlow `health_monitor` (event-loop freeze "
            f"escalation, #9552)._"
        )
        await prs.create_issue(title, body, ["hydraflow-find", "loop-stalled"])
        clear_stall_marker(marker_path)

    async def _check_wiki_freshness(self) -> None:
        """Dead-man-switch for `RepoWikiLoop` via `docs/wiki/log.jsonl` mtime.

        The wiki loop appends to `log.jsonl` on every ingest, compile, and
        active_lint operation. When the file's mtime hasn't moved in
        `wiki_freshness_stale_days`, file one `wiki-stale` issue per stall
        event. Clears dedup on recovery (file moves again).

        Quietly no-ops when the wiki directory or log file does not exist —
        new repos won't have one yet, and that is not a stall.
        """
        prs = self._prs
        if prs is None:
            return

        log_path = self._config.repo_root / "docs" / "wiki" / "log.jsonl"
        if not log_path.exists():
            return

        try:
            mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=UTC)
        except OSError:
            return

        elapsed_s = (datetime.now(UTC) - mtime).total_seconds()
        threshold_s = self._config.wiki_freshness_stale_days * 86400

        dedup_key = "health_monitor:repo_wiki:stalled"
        filed_keys = self._wiki_stall_dedup.get()

        if elapsed_s < threshold_s:
            # Recovered — close the open wiki-stale issue and clear dedup so a
            # future stall files a fresh issue (#9359 issue-hygiene).
            if dedup_key in filed_keys:
                await self._close_issues_by_label(
                    prs,
                    "wiki-stale",
                    "docs/wiki/log.jsonl is moving again — auto-closing.",
                )
                self._wiki_stall_dedup.set_all(filed_keys - {dedup_key})
            return

        if dedup_key in filed_keys:
            # Already filed for the current stall; wait for recovery.
            return

        elapsed_days = int(elapsed_s // 86400)
        title = (
            f"wiki-stale: docs/wiki/log.jsonl has not moved in "
            f"{elapsed_days}d (threshold {self._config.wiki_freshness_stale_days}d)"
        )
        body = (
            f"## RepoWikiLoop dead-man-switch tripped\n\n"
            f"`docs/wiki/log.jsonl` is the append-only operation log for the "
            f"repo wiki. It moves on every ingest, compile, and active_lint "
            f"tick; an unmoved log indicates the wiki loop has not run "
            f"successfully in `{elapsed_days}` days.\n\n"
            f"- Last log entry: `{mtime.isoformat()}`\n"
            f"- Threshold: `{self._config.wiki_freshness_stale_days}` days "
            f"(`wiki_freshness_stale_days`)\n"
            f"- Loop interval: `{self._config.repo_wiki_interval}s`\n\n"
            f"### Operator playbook\n"
            f"1. Check the System tab — is `repo_wiki` enabled? If not, "
            f"flip the kill-switch back on.\n"
            f"2. Check orchestrator logs for the `repo_wiki` task "
            f"(uncaught exceptions, credit/auth failures).\n"
            f"3. Confirm HydraFlow is actually running on this repo "
            f"(the loop only ticks while the harness is up).\n\n"
            f"_Auto-filed by HydraFlow `health_monitor` "
            f"(wiki-freshness dead-man-switch)._"
        )
        await prs.create_issue(
            title,
            body,
            ["hydraflow-find", "wiki-stale"],
        )
        filed_keys = self._wiki_stall_dedup.get()
        self._wiki_stall_dedup.set_all(filed_keys | {dedup_key})

    async def _check_stale_code(self) -> None:
        """Dead-man-switch: alert when this instance is running stale code.

        Consumes ``git_revision.get_commits_behind`` (#9663) for the
        commits-behind count against the in-memory boot SHA — this method
        does NOT recompute staleness itself. ``git_revision`` deliberately
        performs no network fetch (it only reads local tracking refs), so
        this loop owns a bounded, pre-read ``git fetch`` of
        ``origin/<base_branch>`` first; without it the local tracking ref
        can go stale indefinitely and the check would never trip.

        Files one ``factory-stale-code`` issue (deduped) plus one
        ``SYSTEM_ALERT`` dashboard event per stall event when
        ``commits_behind >= stale_code_alert_threshold``. Recovery (a
        fresh process boots onto current code, or origin catches up)
        closes the open issue and clears dedup so a future stall re-files.

        Fails safe: an unreachable remote (fetch failure) or an
        unavailable boot SHA / commit count (``get_commits_behind``
        returns ``None``) degrades this tick to a silent no-op — neither
        files nor clears an alert, since neither the stale nor the
        recovered state was actually confirmed.
        """
        prs = self._prs
        if prs is None:
            return

        base_branch = self._config.base_branch()
        try:
            await run_subprocess(
                "git",
                "fetch",
                "origin",
                base_branch,
                cwd=self._config.repo_root,
                gh_token=self._credentials.gh_token,
                timeout=_STALE_CODE_FETCH_TIMEOUT_SECS,
            )
        except RuntimeError:
            # Includes SubprocessTimeoutError (RuntimeError subclass).
            # Degrade — do not compute or alert against a possibly-stale
            # local tracking ref.
            logger.warning(
                "stale-code check: git fetch origin %s failed; skipping this cycle",
                base_branch,
                exc_info=True,
            )
            return

        commits_behind = get_commits_behind(base_ref=f"origin/{base_branch}")
        if commits_behind is None:
            # Boot SHA or commit count unavailable (e.g. not a git checkout)
            # — fail-safe no-op, per git_revision's own contract.
            return

        threshold = self._config.stale_code_alert_threshold
        dedup_key = "health_monitor:stale_code:stale"
        filed_keys = self._stale_code_dedup.get()

        if commits_behind < threshold:
            # Recovered (or never stale) — close any open alert and clear
            # dedup so a future stall re-files (#9359 issue-hygiene).
            if dedup_key in filed_keys:
                await self._close_issues_by_label(
                    prs,
                    "factory-stale-code",
                    f"This instance is back within {threshold} commits of "
                    f"origin/{base_branch} — auto-closing.",
                )
                self._stale_code_dedup.set_all(filed_keys - {dedup_key})
            return

        if dedup_key in filed_keys:
            # Already filed for the current stall; wait for recovery.
            return

        title = (
            f"factory-stale-code: running instance is {commits_behind} "
            f"commits behind origin/{base_branch} (threshold {threshold})"
        )
        body = (
            f"## Stale-code dead-man-switch tripped\n\n"
            f"This HydraFlow instance's boot commit is `{commits_behind}` "
            f"commits behind `origin/{base_branch}`, at or past the "
            f"configured threshold of `{threshold}` "
            f"(`stale_code_alert_threshold`).\n\n"
            f"The boot SHA is captured once, in-memory, at process start "
            f"and never re-read — a `git pull` without a process restart "
            f"advances the working-tree HEAD while the process keeps "
            f"running the stale bytecode, so this check does not "
            f"self-clear until the process actually restarts onto fresh "
            f"code.\n\n"
            f"### Operator playbook\n"
            f"1. Check `GET /api/control/status` for `boot_sha` / "
            f"`commits_behind`.\n"
            f"2. Restart the orchestrator (`systemctl restart hydraflow` "
            f"or equivalent) to boot onto current `origin/{base_branch}`.\n"
            f"3. If this keeps tripping right after a restart, check "
            f"whether the deploy pulls before restarting.\n\n"
            f"_Auto-filed by HydraFlow `health_monitor` "
            f"(stale-code dead-man-switch, #9596)._"
        )
        await prs.create_issue(
            title,
            body,
            ["hydraflow-find", "factory-stale-code"],
        )
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                data={
                    "kind": "factory_stale_code",
                    "commits_behind": commits_behind,
                    "threshold": threshold,
                    "base_branch": base_branch,
                },
            )
        )
        filed_keys = self._stale_code_dedup.get()
        self._stale_code_dedup.set_all(filed_keys | {dedup_key})

    async def _close_issues_by_label(
        self,
        prs: PRPort,
        label: str,
        comment: str,
        *,
        title_contains: str | None = None,
    ) -> None:
        """Close every open issue carrying *label* when a dead-man-switch
        recovers (#9359). Titles embed elapsed-time so they can't be found by
        title; the label is the stable handle. ``title_contains`` narrows to
        one worker's issues when the label is shared (generic stall sweep)."""
        try:
            issues = await prs.list_issues_by_label(label)
        except Exception:  # noqa: BLE001
            logger.warning(
                "health_monitor: could not list %s issues to close",
                label,
                exc_info=True,
            )
            return
        for issue in issues:
            number = issue.get("number")
            if not number:
                continue
            if title_contains is not None and title_contains not in str(
                issue.get("title", "")
            ):
                continue
            await prs.post_comment(number, comment)
            await prs.close_issue(number)

    # ------------------------------------------------------------------
    # Persistent-error self-repair actuator (#10140)
    # ------------------------------------------------------------------

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
