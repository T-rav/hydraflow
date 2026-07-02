"""Conformance route handlers — read-only ADR conformance scorecard endpoint."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import HydraFlowConfig
from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard")


def latest_conformance_by_adr(config: HydraFlowConfig) -> dict[str, dict]:
    """Return the most recent conformance row per adr_id.

    Reads ``<repo_data_root>/metrics/adr_conformance.jsonl`` (the same path
    ``AdrConformanceLoop._metrics_path()`` persists to) and keeps the row
    with the maximum ``timestamp`` for each ``adr_id``. Returns ``{}`` when
    the file is absent or unreadable.
    """
    path = config.repo_data_root / "metrics" / "adr_conformance.jsonl"
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
                    logger.debug(
                        "Skipping corrupt adr_conformance.jsonl line", exc_info=True
                    )
                    continue
                adr_id = row.get("adr_id")
                if not adr_id:
                    continue
                existing = latest.get(adr_id)
                if existing is None or row.get("timestamp", "") > existing.get(
                    "timestamp", ""
                ):
                    latest[adr_id] = row
    except OSError:
        logger.warning("Could not read conformance cache %s", path, exc_info=True)
        return {}

    return latest


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Register conformance-related routes on *router*."""

    @router.get("/api/adr-conformance")
    async def get_adr_conformance() -> JSONResponse:
        """Return the latest conformance row per ADR as JSON."""
        return JSONResponse(latest_conformance_by_adr(ctx.config))
