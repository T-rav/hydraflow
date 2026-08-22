"""Injectable FastAPI application for gateway control and data planes."""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hydraflow_gateway.accounts import (
    DEFAULT_HEALTH_WINDOW_SECONDS,
    MAX_HEALTH_WINDOW_SECONDS,
    MIN_HEALTH_WINDOW_SECONDS,
    AccountsView,
    build_accounts_view,
)
from hydraflow_gateway.active_routes import (
    MAX_RECENT_LIMIT,
    ActiveRouteRegistry,
    ActiveRoutesView,
    RecentRoutesView,
    build_active_routes_view,
    build_recent_routes_view,
)
from hydraflow_gateway.keys import (
    ExpiredVirtualKey,
    InvalidVirtualKey,
    KeyPolicyError,
    VirtualKeyStore,
)
from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger
from hydraflow_gateway.models import (
    MintKeyRequest,
    MintKeyResponse,
    RevokeKeyResponse,
)
from hydraflow_gateway.proxy import (
    GatewayCredentialError,
    GatewayProxy,
    extract_virtual_token,
)
from hydraflow_gateway.settings import GatewaySettings
from model_pricing import ModelPricingTable, load_pricing

_DATA_PLANE_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


class _ControlPlaneBoundary:
    """Authenticate and bound control requests before application body parsing."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        control_token: str,
        max_body_bytes: int,
    ) -> None:
        self._app = app
        self._control_token = control_token
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/control/"):
            await self._app(scope, receive, send)
            return

        raw_headers = list(scope.get("headers", []))
        presented = _extract_control_bearer(raw_headers)
        if presented is None or not secrets.compare_digest(
            presented, self._control_token
        ):
            await _control_error(
                scope,
                receive,
                send,
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid control credential",
                headers={"WWW-Authenticate": "Bearer"},
            )
            return

        declared_size = _declared_content_length(raw_headers)
        if declared_size is None:
            pass
        elif declared_size < 0:
            await _control_error(
                scope,
                receive,
                send,
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid Content-Length",
            )
            return
        elif declared_size > self._max_body_bytes:
            await _control_error(
                scope,
                receive,
                send,
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="control request body is too large",
            )
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self._max_body_bytes:
                await _control_error(
                    scope,
                    receive,
                    send,
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="control request body is too large",
                )
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {
                    "type": "http.request",
                    "body": bytes(body),
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        await self._app(scope, replay_receive, send)


def create_app(
    settings: GatewaySettings | None = None,
    *,
    key_store: VirtualKeyStore | None = None,
    client: httpx.AsyncClient | None = None,
    ledger: GatewayLedger | None = None,
    body_store: GatewayBodyStore | None = None,
    pricing: ModelPricingTable | None = None,
    active_routes: ActiveRouteRegistry | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    wall_clock: Callable[[], float] = time.time,
) -> FastAPI:
    """Build an app with injectable boundaries for deterministic testing."""
    resolved_settings = settings or GatewaySettings.from_env()
    resolved_store = key_store or VirtualKeyStore(
        max_ttl_seconds=resolved_settings.max_key_ttl_seconds,
        body_capture_repo_slugs=resolved_settings.body_capture_repo_slugs,
    )
    resolved_ledger = ledger or GatewayLedger(resolved_settings.ledger_path)
    resolved_body_store = body_store or GatewayBodyStore(resolved_settings.body_dir)
    resolved_pricing = pricing or load_pricing()
    resolved_active_routes = active_routes or ActiveRouteRegistry(
        started_at=_as_utc(wall_clock())
    )
    owns_client = client is None
    resolved_client = client or _build_http_client(resolved_settings)
    proxy = GatewayProxy(
        settings=resolved_settings,
        client=resolved_client,
        ledger=resolved_ledger,
        body_store=resolved_body_store,
        pricing=resolved_pricing,
        active_routes=resolved_active_routes,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        reaper = asyncio.create_task(
            _reap_gateway_state(
                resolved_store,
                resolved_body_store,
                interval_seconds=resolved_settings.reaper_interval_seconds,
                body_retention_seconds=resolved_settings.body_retention_seconds,
                sleep=sleep,
                wall_clock=wall_clock,
                on_storage_error=proxy.mark_telemetry_unhealthy,
            ),
            name="gateway-key-reaper",
        )
        try:
            yield
        finally:
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper
            # Shutdown ends every stream this process owned; no in-flight row
            # may survive it and misreport traffic on the next read.
            resolved_active_routes.clear()
            if owns_client:
                await resolved_client.aclose()

    app = FastAPI(title="hydraflow-gateway", lifespan=lifespan)
    app.add_middleware(
        _ControlPlaneBoundary,
        control_token=resolved_settings.control_token.get_secret_value(),
        max_body_bytes=resolved_settings.max_control_request_bytes,
    )
    app.state.gateway_settings = resolved_settings
    app.state.gateway_key_store = resolved_store
    app.state.gateway_ledger = resolved_ledger
    app.state.gateway_body_store = resolved_body_store
    app.state.gateway_http_client = resolved_client
    app.state.gateway_proxy = proxy
    app.state.gateway_active_routes = resolved_active_routes

    @app.get("/healthz", include_in_schema=False)
    async def health() -> object:
        if not proxy.telemetry_healthy:
            return JSONResponse(
                {
                    "status": "degraded",
                    "providers": sorted(
                        provider.value for provider in resolved_settings.upstreams
                    ),
                },
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return {
            "status": "ok",
            "providers": sorted(
                provider.value for provider in resolved_settings.upstreams
            ),
        }

    @app.post(
        "/control/v1/keys",
        response_model=MintKeyResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def mint_key(payload: MintKeyRequest) -> MintKeyResponse:
        if payload.provider_binding not in resolved_settings.upstreams:
            raise HTTPException(status_code=422, detail="provider is unavailable")
        try:
            return resolved_store.mint(payload)
        except KeyPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete(
        "/control/v1/keys/{key_id}",
        response_model=RevokeKeyResponse,
    )
    async def revoke_key(key_id: str) -> RevokeKeyResponse:
        return RevokeKeyResponse(key_id=key_id, revoked=resolved_store.revoke(key_id))

    @app.get("/control/v2/accounts", response_model=AccountsView)
    async def read_accounts(
        window_seconds: int = Query(
            default=DEFAULT_HEALTH_WINDOW_SECONDS,
            ge=MIN_HEALTH_WINDOW_SECONDS,
            le=MAX_HEALTH_WINDOW_SECONDS,
        ),
    ) -> AccountsView:
        return build_accounts_view(
            settings=resolved_settings,
            leases=resolved_store.lease_identities(),
            in_flight=resolved_active_routes.in_flight(),
            recent=resolved_active_routes.recent(),
            now=_as_utc(wall_clock()),
            window_seconds=window_seconds,
            evidence_since=resolved_active_routes.started_at,
        )

    @app.get("/control/v2/routes/active", response_model=ActiveRoutesView)
    async def read_active_routes() -> ActiveRoutesView:
        return build_active_routes_view(
            leases=resolved_store.lease_identities(),
            in_flight=resolved_active_routes.in_flight(),
            now=_as_utc(wall_clock()),
            evidence_since=resolved_active_routes.started_at,
        )

    @app.get("/control/v2/routes/recent", response_model=RecentRoutesView)
    async def read_recent_routes(
        limit: int = Query(default=50, ge=1, le=MAX_RECENT_LIMIT),
    ) -> RecentRoutesView:
        return build_recent_routes_view(
            routes=resolved_active_routes.recent(limit=limit),
            now=_as_utc(wall_clock()),
            evidence_since=resolved_active_routes.started_at,
            capacity=resolved_active_routes.recent_capacity,
            truncated=resolved_active_routes.truncated(),
        )

    @app.api_route("/{path:path}", methods=_DATA_PLANE_METHODS)
    async def passthrough(request: Request, path: str) -> object:
        del path
        try:
            token = extract_virtual_token(request.headers.raw)
            identity = resolved_store.resolve(token)
        except (GatewayCredentialError, InvalidVirtualKey, ExpiredVirtualKey) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or expired gateway credential",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        request.state.gateway_identity = identity
        return await proxy.forward(request, identity)

    return app


def _as_utc(epoch_seconds: float) -> datetime:
    return datetime.fromtimestamp(epoch_seconds, tz=UTC)


def _build_http_client(settings: GatewaySettings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.connect_timeout_seconds,
            read=None,
            write=settings.write_timeout_seconds,
            pool=settings.pool_timeout_seconds,
        ),
        limits=httpx.Limits(
            max_connections=settings.max_connections,
            max_keepalive_connections=settings.max_keepalive_connections,
        ),
        follow_redirects=False,
        trust_env=False,
    )


async def _reap_gateway_state(
    store: VirtualKeyStore,
    body_store: GatewayBodyStore,
    *,
    interval_seconds: float,
    body_retention_seconds: int,
    sleep: Callable[[float], Awaitable[None]],
    wall_clock: Callable[[], float],
    on_storage_error: Callable[[], None],
) -> None:
    while True:
        await sleep(interval_seconds)
        store.reap_expired()
        try:
            body_store.reap_older_than(wall_clock() - body_retention_seconds)
        except OSError:
            on_storage_error()


def _extract_control_bearer(
    raw_headers: Sequence[tuple[bytes, bytes]],
) -> str | None:
    values = [
        value.strip() for name, value in raw_headers if name.lower() == b"authorization"
    ]
    if len(values) != 1:
        return None
    scheme, separator, token = values[0].partition(b" ")
    if not separator or scheme.lower() != b"bearer" or not token.strip():
        return None
    try:
        return token.strip().decode("ascii")
    except UnicodeDecodeError:
        return None


def _declared_content_length(
    raw_headers: Sequence[tuple[bytes, bytes]],
) -> int | None:
    values = [
        value.strip()
        for name, value in raw_headers
        if name.lower() == b"content-length"
    ]
    if not values:
        return None
    if len(values) != 1:
        return -1
    try:
        value = int(values[0])
    except ValueError:
        return -1
    return value if value >= 0 else -1


async def _control_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    status_code: int,
    detail: str,
    headers: dict[str, str] | None = None,
) -> None:
    response = JSONResponse(
        {"detail": detail}, status_code=status_code, headers=headers
    )
    await response(scope, receive, send)
