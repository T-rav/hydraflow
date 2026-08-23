"""The heavy pass of ``HealthMonitorLoop``.

Extracted VERBATIM from ``src/health_monitor_loop.py`` (god-class
decomposition, Refs #11547) as a mixin ``HealthMonitorLoop`` inherits, so every
method still resolves as an attribute of the class and instance/class-level
patching in tests still lands.

One concern: the expensive, lower-cadence half of the cycle — the pass gate's
body and the ingestion / auto-file / verification / cross-project cycles it
fans out to.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import HydraFlowConfig
from exception_classify import reraise_on_credit_or_bug

from ._common import (
    TrendMetrics,
)
from ._trends import compute_trend_metrics

if TYPE_CHECKING:
    from events import EventBus
    from ports import ObservabilityPort
    from retrospective_queue import RetrospectiveQueue


logger = logging.getLogger("hydraflow.health_monitor_loop")


class HealthMonitorHeavyPassMixin:
    """The heavy pass of ``HealthMonitorLoop``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``HealthMonitorLoop.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _bus: EventBus
    _config: HydraFlowConfig
    _last_heavy_pass_ts: datetime | None
    _last_log_scan: datetime | None
    _obs: ObservabilityPort | None
    _retrospective_queue: RetrospectiveQueue | None

    if TYPE_CHECKING:

        def _apply_adjustments(
            self, metrics: TrendMetrics
        ) -> int: ...  # provided by _adjust

        async def _check_event_loop_stall(self) -> None: ...  # provided by _stall

        async def _check_sanity_loop_staleness(self) -> None: ...  # provided by _stall

        async def _check_stale_code(self) -> None: ...  # provided by _freshness

        async def _check_wiki_freshness(self) -> None: ...  # provided by _freshness

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
        ) -> None: ...  # provided by _vitals

        @property
        def _failures_path(self) -> Path: ...  # provided by _loop

        async def _file_hitl_recommendations(
            self, metrics: TrendMetrics
        ) -> None: ...  # provided by _hitl

        @property
        def _outcomes_path(self) -> Path: ...  # provided by _loop

        async def _run_fleet_vitals(
            self, metrics: Any
        ) -> None: ...  # provided by _vitals

        @property
        def _scores_path(self) -> Path: ...  # provided by _loop

        def _verify_pending_adjustments(
            self, metrics: TrendMetrics
        ) -> None: ...  # provided by _adjust

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
                except Exception as exc:  # noqa: BLE001
                    # A credit/auth failure is not "this one suggestion is
                    # malformed" — it means every subsequent iteration would
                    # spawn against an exhausted account. Let it out so the
                    # orchestrator's pause handler sees it (#6855, #11664).
                    reraise_on_credit_or_bug(exc)
                    continue
            # Clear processed suggestions so they are not re-ingested
            suggestions_path.write_text("", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            # Outer guard: also the path a credit error re-raised by the
            # per-item handler above takes on its way out of the loop.
            reraise_on_credit_or_bug(exc)
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
