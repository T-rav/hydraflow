"""TrustFleetSanityLoop — meta-observability for the trust loop fleet (spec §12.1).

Watches the nine §4.1–§4.9 trust loops. On any of five anomaly
conditions (thresholds config-driven, operator-tunable), files a
``hitl-escalation`` issue with label ``trust-loop-anomaly``. One-attempt
escalation — the anomaly IS the escalation, not a repair attempt.

Dead-man-switch: ``HealthMonitorLoop`` watches *this* loop's
heartbeat; when the sanity loop itself stops ticking, HealthMonitor
files ``sanity-loop-stalled``. Recursion bounded at one meta-layer
(spec §12.1 "Bounds of meta-observability").

Kill-switch: ``LoopDeps.enabled_cb("trust_fleet_sanity")`` — **no
``trust_fleet_sanity_enabled`` config field** (spec §12.2).

Read-side surface is `/api/trust/fleet?range=7d|30d` — schema
documented in :data:`FLEET_ENDPOINT_SCHEMA` below. Route impl is owned
by Plan 6b (§4.11 factory-cost work).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult

if TYPE_CHECKING:
    from bg_worker_manager import BGWorkerManager
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from events import EventBus
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.trust_fleet_sanity_loop")


FLEET_ENDPOINT_SCHEMA: str = """
/api/trust/fleet response schema (spec §12.1; owned by Plan 6b).

Request: GET /api/trust/fleet?range=7d|30d

Response JSON:

{
  "range": "7d" | "30d",
  "generated_at": "<iso8601 UTC>",
  "loops": [
    {
      "worker_name": "<string>",         # e.g. "ci_monitor", "rc_budget"
      "enabled": <bool>,                  # from BGWorkerManager.is_enabled
      "interval_s": <int>,                # effective interval (dynamic or default)
      "last_tick_at": "<iso8601>" | null, # from worker_heartbeats
      "ticks_total": <int>,               # window-scoped count from event log
      "ticks_errored": <int>,             # status=="error" in the window
      "issues_filed_total": <int>,        # sum of details.filed over the window
      "issues_closed_total": <int>,       # sum from `EventType.ISSUE_CLOSED` events (best-effort; 0 if absent)
      "issues_open_escalated": <int>,     # currently-open issues the loop filed with hitl-escalation label
      "repair_attempts_total": <int>,     # sum of details.repaired + details.failed
      "repair_successes_total": <int>,    # sum of details.repaired
      "repair_failures_total": <int>,     # sum of details.failed
      "loop_specific": {                  # optional per-loop metrics; see §12.1 examples
        "reverts_merged": <int>,          # staging_bisect
        "cases_added": <int>,             # corpus_learning
        "cassettes_refreshed": <int>,     # contract_refresh
        "principles_regressions": <int>,  # principles_audit
        ...
      }
    },
    ...
  ],
  "anomalies_recent": [
    {
      "kind": "issues_per_hour" | "repair_ratio" | "tick_error_ratio"
            | "staleness" | "cost_spike",
      "worker": "<string>",
      "filed_at": "<iso8601>",
      "issue_number": <int>,
      "details": {<detector-specific>}
    }
  ]
}

Implementation notes for Plan 6b:
- Read `ticks_total`/`ticks_errored`/`issues_filed_total` by calling
  `event_bus.load_events_since(now - range)` and tallying
  `EventType.BACKGROUND_WORKER_STATUS` entries where `data.worker`
  matches each loop.
- Read `last_tick_at`/`enabled`/`interval_s` from
  `state.get_worker_heartbeats()` + `bg_workers.worker_enabled` +
  `bg_workers.get_interval`.
- `anomalies_recent` is populated from the last-24h `hitl-escalation`+
  `trust-loop-anomaly` issues authored by the bot (via `gh issue list`).
- Loop-specific metrics are loop-maintained counter fields TBD by each
  sibling loop; default `0` when unreported.
"""

_MAX_ATTEMPTS = 1  # spec §12.1 — the anomaly IS the escalation.
_HOUR_SECONDS = 3600
_DAY_SECONDS = 86_400
_ANOMALY_KINDS: tuple[str, ...] = (
    "issues_per_hour",
    "repair_ratio",
    "tick_error_ratio",
    "staleness",
    "cost_spike",
)

_TITLE_RE = re.compile(
    r"HITL: trust-loop anomaly — (?P<worker>[\w_]+) (?P<kind>[\w_]+)$",
)


class TrustFleetSanityLoop(BaseBackgroundLoop):
    """Meta-observability loop — watches the nine trust loops (spec §12.1)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        bg_workers: BGWorkerManager,
        pr_manager: PRManager,
        dedup: DedupStore,
        event_bus: EventBus,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="trust_fleet_sanity",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._bg_workers = bg_workers
        self._pr = pr_manager
        self._dedup = dedup
        self._source_bus = event_bus  # separate handle for load_events_since

    def _get_default_interval(self) -> int:
        return self._config.trust_fleet_sanity_interval

    async def _do_work(self) -> WorkCycleResult:
        """Skeleton — Task 5 replaces with the full tick."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        await self._reconcile_closed_escalations()
        # Skeleton returns without running detectors (Task 5 fills this in).
        return {"status": "ok", "anomalies": 0}

    async def _reconcile_closed_escalations(self) -> None:
        """Task 5."""
        return None
