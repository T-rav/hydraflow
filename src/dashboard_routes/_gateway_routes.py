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

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query

from gateway_control_reader import (
    DEFAULT_ACCOUNT_WINDOW_SECONDS,
    DEFAULT_RECENT_LIMIT,
    GatewayControlReader,
    reader_from_config,
)

# Bounds are borrowed from the gateway's own read plane, never re-declared here:
# a proxy that validated against a stale copy would turn every poll into a 422
# the operator would read as "gateway unreachable".
from hydraflow_gateway.accounts import (
    MAX_HEALTH_WINDOW_SECONDS,
    MIN_HEALTH_WINDOW_SECONDS,
)
from hydraflow_gateway.active_routes import MAX_RECENT_LIMIT

if TYPE_CHECKING:
    from collections.abc import Callable

    from config import HydraFlowConfig


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
            ge=MIN_HEALTH_WINDOW_SECONDS,
            le=MAX_HEALTH_WINDOW_SECONDS,
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
