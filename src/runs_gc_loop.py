"""Background worker loop — garbage-collect expired run artifacts.

Also the caretaker tick for the hash-chained audit streams (CH-1, #9729):
each cycle verifies every chain and enforces the per-stream retention floor.
The check lives here (not in a repo-CI pytest) because the streams live in
the runtime data root, which a CI checkout never has — an in-repo check would
trivially pass; this loop already owns artifact lifecycle and runs hourly.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from audit_chain import AuditChain, audit_streams
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventType, HydraFlowEvent
from prompt_telemetry import refresh_prompt_telemetry_health_after_retention
from run_recorder import RunRecorder

logger = logging.getLogger("hydraflow.runs_gc_loop")


class RunsGCLoop(BaseBackgroundLoop):
    """Periodically purges expired and oversized run artifacts.

    Enforces the configured retention TTL (``artifact_retention_days``)
    and size cap (``artifact_max_size_mb``) by delegating to
    :class:`RunRecorder` purge methods. Additionally walks every hash-chained
    audit stream: a chain break raises a ``SYSTEM_ALERT`` (tampering or
    corruption becomes a detected event), and streams with a configured
    retention floor are prefix-pruned — records younger than the floor can
    never be deleted, and broken streams are never pruned (tamper evidence
    is preserved).
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        run_recorder: RunRecorder,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="runs_gc", config=config, deps=deps)
        self._recorder = run_recorder
        # One SYSTEM_ALERT per break EVENT, not per hourly cycle — a
        # persistent break would otherwise emit 24 alerts/day/stream and
        # drown the signal (cost_budget_alerts dedup precedent). Cleared
        # when the stream verifies clean again, so a fresh break re-alerts.
        self._chain_alert_dedup = DedupStore(
            "runs_gc_chain_alerts",
            config.data_root / "dedup" / "runs_gc_chain_alerts.json",
        )

    def _get_default_interval(self) -> int:
        return self._config.runs_gc_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Run one GC cycle: purge expired runs, then enforce size cap."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.runs_gc_loop_enabled:
            return {"status": "config_disabled"}
        expired = self._recorder.purge_expired(self._config.artifact_retention_days)
        oversized = self._recorder.purge_oversized(self._config.artifact_max_size_mb)
        stats = self._recorder.get_storage_stats()

        # #9905: events.jsonl rotation used to run only at boot, so a
        # long-lived instance grows the log without bound (observed 660 MB
        # after a flood). Rotate every GC cycle; the EventLog holds the
        # append lock across the read→write, so this is safe against
        # concurrent publishes.
        event_log_rotation: dict[str, int] = {}
        if self._config.event_log_periodic_rotate_enabled:
            event_log_rotation = await self._bus.rotate_log(
                self._config.event_log_max_size_mb * 1024 * 1024,
                self._config.event_log_retention_days,
            )
            if event_log_rotation:
                logger.info(
                    "Runs GC: rotated event log (kept %d, dropped %d by age, "
                    "%d by size bound)",
                    event_log_rotation.get("kept", 0),
                    event_log_rotation.get("dropped_age", 0),
                    event_log_rotation.get("dropped_size", 0),
                )

        total_purged = expired + oversized
        if total_purged > 0:
            logger.info(
                "Runs GC: purged %d expired, %d oversized (%d runs remain, %.1f MB)",
                expired,
                oversized,
                stats["total_runs"],
                stats["total_mb"],
            )

        audit_chain_status, audit_pruned = await self._tend_audit_chains()

        return {
            "expired_purged": expired,
            "oversized_purged": oversized,
            "total_runs": stats["total_runs"],
            "total_mb": stats["total_mb"],
            "issues": stats["issues"],
            "audit_chain_status": audit_chain_status,
            "audit_pruned": audit_pruned,
            "event_log_rotation": event_log_rotation,
        }

    async def _tend_audit_chains(self) -> tuple[dict[str, str], dict[str, int]]:
        """Verify every chained audit stream, then enforce retention floors.

        Verification runs FIRST: a broken stream is alerted and never pruned,
        so GC cannot destroy tamper evidence. Retention (``None`` = keep
        forever) is a floor — only records strictly older are prefix-pruned.
        """
        status: dict[str, str] = {}
        pruned: dict[str, int] = {}
        for spec in audit_streams(self._config):
            chain = AuditChain(spec.path)
            result = chain.verify()
            if not result.ok:
                status[spec.name] = "break"
                alert_key = f"audit_chain_break:{spec.name}"
                already_alerted = alert_key in self._chain_alert_dedup.get()
                if already_alerted:
                    continue
                self._chain_alert_dedup.set_all(
                    self._chain_alert_dedup.get() | {alert_key}
                )
                logger.error(
                    "Audit chain break in stream %r (%s): %s",
                    spec.name,
                    spec.path,
                    "; ".join(
                        f"record {b.record_no}: {b.reason}" for b in result.breaks[:5]
                    ),
                )
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SYSTEM_ALERT,
                        data={
                            "kind": "audit_chain_break",
                            "stream": spec.name,
                            "path": str(spec.path),
                            "breaks": [
                                f"record {b.record_no}: {b.reason}"
                                for b in result.breaks[:5]
                            ],
                        },
                    )
                )
                continue
            # Crash-window warnings (torn_tail / sidecar_lag) are healthy:
            # they self-heal on the stream's next append and MUST NOT raise
            # the tamper alert or block retention pruning below.
            if any(w.startswith("torn_tail") for w in result.warnings):
                status[spec.name] = "torn_tail"
            elif any(w.startswith("sidecar_lag") for w in result.warnings):
                status[spec.name] = "sidecar_lag"
            else:
                status[spec.name] = "ok" if result.chained_records else "empty"
            recovered_key = f"audit_chain_break:{spec.name}"
            keys = self._chain_alert_dedup.get()
            if recovered_key in keys:
                self._chain_alert_dedup.set_all(keys - {recovered_key})
            if spec.retention_days is None:
                continue
            cutoff = datetime.now(UTC) - timedelta(days=spec.retention_days)
            removed = chain.prune_before(cutoff, spec.timestamp_key)
            pruned[spec.name] = removed
            if removed:
                if spec.name == "inference_telemetry" and not (
                    refresh_prompt_telemetry_health_after_retention(spec.path)
                ):
                    logger.error(
                        "Audit retention could not refresh prompt telemetry "
                        "source-health anchor for %s",
                        spec.path,
                    )
                logger.info(
                    "Audit retention: pruned %d record(s) older than %d days "
                    "from stream %r",
                    removed,
                    spec.retention_days,
                    spec.name,
                )
        return status, pruned
