"""HITL recommendation filing of ``HealthMonitorLoop``.

Extracted VERBATIM from ``src/health_monitor_loop.py`` (god-class
decomposition, Refs #11547) as a mixin.

One concern: what happens when a condition is OUTSIDE the safe auto-adjustment
range — the deduped ``hydraflow-hitl`` issue and the body it renders.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from config import HydraFlowConfig

from ._common import (
    _AVG_SCORE_LOW,
    _HITL_HIGH,
    _STALE_COUNT_HIGH,
    _SURPRISE_HIGH,
    TrendMetrics,
)

logger = logging.getLogger("hydraflow.health_monitor_loop")


class HealthMonitorHitlMixin:
    """HITL recommendation filing of ``HealthMonitorLoop``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``HealthMonitorLoop.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig

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
