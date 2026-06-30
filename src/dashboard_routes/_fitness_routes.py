"""Fitness route handlers — read-only loop fitness scorecard endpoint."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import HydraFlowConfig
from dashboard_routes._routes import RouteContext
from metrics_manager import get_metrics_cache_dir

logger = logging.getLogger("hydraflow.dashboard")


def latest_fitness_by_worker(config: HydraFlowConfig) -> dict[str, dict]:
    """Return the most recent fitness row per worker_name.

    Reads ``<metrics_cache_dir>/fitness.jsonl`` and keeps the row with the
    maximum ``timestamp`` for each ``worker_name``. Returns ``{}`` when the
    file is absent or unreadable.
    """
    path = get_metrics_cache_dir(config) / "fitness.jsonl"
    if not path.exists():
        return {}

    latest: dict[str, dict] = {}
    try:
        with open(path) as f:
            for raw_line in f:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    row = json.loads(stripped)
                except json.JSONDecodeError:
                    logger.debug("Skipping corrupt fitness.jsonl line", exc_info=True)
                    continue
                worker = row.get("worker_name")
                if not worker:
                    continue
                existing = latest.get(worker)
                if existing is None or row.get("timestamp", "") > existing.get(
                    "timestamp", ""
                ):
                    latest[worker] = row
    except OSError:
        logger.warning("Could not read fitness cache %s", path, exc_info=True)
        return {}

    return latest


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Register fitness-related routes on *router*."""

    @router.get("/api/loop-fitness")
    async def get_loop_fitness() -> JSONResponse:
        """Return the latest fitness row per worker as JSON."""
        return JSONResponse(latest_fitness_by_worker(ctx.config))
