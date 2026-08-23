"""Health trend computation.

Extracted VERBATIM from ``src/health_monitor_loop.py`` (god-class
decomposition, Refs #11547). Reads the outcome / score / failure JSONL trails
and folds them into the ``TrendMetrics`` one monitor cycle reasons over.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ._common import (
    TrendMetrics,
)

logger = logging.getLogger("hydraflow.health_monitor_loop")


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
