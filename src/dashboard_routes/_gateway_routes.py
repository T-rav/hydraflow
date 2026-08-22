"""Read-only gateway account and route proxy routes (ADR-0138, issue #11534).

Three GET endpoints under ``/api/gateway`` that proxy the gateway's v2 read
plane. The dashboard backend holds the env-only control credential and returns
only the gateway's already-sanitized read models, so the browser never receives
a gateway control token and no provider secret crosses this boundary.

Read-only: there is no mutation route here, and the gateway exposes no v2 write
endpoint. Account administration, policy, and enforcement belong to later
phases of epic #11531.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query

from gateway_control_reader import (
    DEFAULT_ACCOUNT_WINDOW_SECONDS,
    DEFAULT_RECENT_LIMIT,
    GatewayControlReader,
    reader_from_config,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.dashboard.gateway")

MIN_ACCOUNT_WINDOW_SECONDS = 60
MAX_ACCOUNT_WINDOW_SECONDS = 86_400
MAX_RECENT_LIMIT = 200


def build_gateway_router(
    config: HydraFlowConfig,
    *,
    reader_factory: Callable[[], GatewayControlReader] | None = None,
) -> APIRouter:
    """Build the ``/api/gateway`` read-only router.

    *reader_factory* is the injectable boundary: production builds a reader from
    *config* plus ``HYDRAFLOW_GATEWAY_CONTROL_TOKEN``; tests supply a reader
    pointed at an in-process gateway app.
    """

    router = APIRouter(prefix="/api/gateway", tags=["gateway"])

    def _reader() -> GatewayControlReader:
        if reader_factory is not None:
            return reader_factory()
        return reader_from_config(config)

    @router.get("/accounts")
    async def read_accounts(
        window_seconds: int = Query(
            default=DEFAULT_ACCOUNT_WINDOW_SECONDS,
            ge=MIN_ACCOUNT_WINDOW_SECONDS,
            le=MAX_ACCOUNT_WINDOW_SECONDS,
        ),
    ) -> dict[str, Any]:
        result = await _reader().accounts(window_seconds=window_seconds)
        return result.to_json_dict()

    @router.get("/routes/active")
    async def read_active_routes() -> dict[str, Any]:
        result = await _reader().active_routes()
        return result.to_json_dict()

    @router.get("/routes/recent")
    async def read_recent_routes(
        limit: int = Query(default=DEFAULT_RECENT_LIMIT, ge=1, le=MAX_RECENT_LIMIT),
    ) -> dict[str, Any]:
        result = await _reader().recent_routes(limit=limit)
        return result.to_json_dict()

    return router
