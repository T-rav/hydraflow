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
from hydraflow_gateway.route_mint import (
    MintAttemptConflict,
    MintV2Request,
    MintV2Response,
    RouteMintStore,
)
from hydraflow_gateway.routing_account_admin import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    AccountAdminAuditView,
    AccountAdminRejected,
    AccountAdminStore,
    AccountStateRequest,
    AccountStateResponse,
    AdminRejection,
    RevokeLeasesRequest,
    RevokeLeasesResponse,
    audit_view,
)
from hydraflow_gateway.routing_account_admin import (
    AdminMutationResult as _AdminResult,
)
from hydraflow_gateway.routing_account_state import AccountRuntimeState, live_facts
from hydraflow_gateway.routing_accounts import AccountPool, load_account_pool
from hydraflow_gateway.routing_fallback import TerminalDecisionIndex
from hydraflow_gateway.settings import GatewaySettings
from model_pricing import ModelPricingTable, load_pricing

_DATA_PLANE_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

_ADMIN_REJECTION_STATUS: dict[AdminRejection, int] = {
    # A stale revision is a lost update, not a bad request: the same 409 the
    # policy workspace answers, so one operator console can handle both the same
    # way — reload, re-read the revision, decide again.
    AdminRejection.STALE_REVISION: status.HTTP_409_CONFLICT,
    AdminRejection.UNKNOWN_ACCOUNT: status.HTTP_404_NOT_FOUND,
    # An unverifiable chain is a server-side integrity failure, and the caller
    # cannot fix it by asking differently.
    AdminRejection.AUDIT_CHAIN_BROKEN: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _administer(mutate: Callable[[], _AdminResult]) -> _AdminResult:
    """Run one administrative mutation, mapping its refusal onto a status code."""
    try:
        return mutate()
    except AccountAdminRejected as exc:
        raise HTTPException(
            status_code=_ADMIN_REJECTION_STATUS.get(
                exc.rejection, status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=exc.rejection.value,
        ) from exc


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
    account_pool: AccountPool | None = None,
    account_state: AccountRuntimeState | None = None,
    admin_store: AccountAdminStore | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    wall_clock: Callable[[], float] = time.time,
) -> FastAPI:
    """Build an app with injectable boundaries for deterministic testing."""
    resolved_settings = settings or GatewaySettings.from_env()
    resolved_store = key_store or VirtualKeyStore(
        max_ttl_seconds=resolved_settings.max_key_ttl_seconds,
        body_capture_repo_slugs=resolved_settings.body_capture_repo_slugs,
        wall_clock=wall_clock,
    )
    resolved_ledger = ledger or GatewayLedger(resolved_settings.ledger_path)
    resolved_body_store = body_store or GatewayBodyStore(resolved_settings.body_dir)
    resolved_pricing = pricing or load_pricing()
    resolved_active_routes = active_routes or ActiveRouteRegistry(
        started_at=_as_utc(wall_clock())
    )
    resolved_pool = account_pool or load_account_pool(resolved_settings)
    resolved_account_state = account_state or AccountRuntimeState(
        resolved_pool.registry, wall_clock=wall_clock
    )
    resolved_admin = admin_store or AccountAdminStore(
        resolved_settings.account_state_dir
    )
    resolved_terminals = TerminalDecisionIndex()
    route_mint = RouteMintStore(
        key_store=resolved_store,
        # What this deployment can actually serve, in the order it serves it. An
        # account whose credential is absent is never eligible, which is the
        # failure table's first row.
        pool=resolved_pool,
        account_state=resolved_account_state,
        admin=resolved_admin,
        terminals=resolved_terminals,
        max_fallback_hops=resolved_settings.max_fallback_hops,
        wall_clock=wall_clock,
        attempt_retention_seconds=resolved_settings.max_key_ttl_seconds,
    )
    # One release seam for both halves of a key's life: the store hands back a
    # lease slot on revoke, expiry, reap and shutdown, and the reservation is
    # keyed on the key id so none of those paths can release it twice.
    resolved_store.on_release(resolved_account_state.release_lease)
    owns_client = client is None
    resolved_client = client or _build_http_client(resolved_settings)
    proxy = GatewayProxy(
        settings=resolved_settings,
        client=resolved_client,
        ledger=resolved_ledger,
        body_store=resolved_body_store,
        pricing=resolved_pricing,
        active_routes=resolved_active_routes,
        account_pool=resolved_pool,
        account_state=resolved_account_state,
        terminals=resolved_terminals,
        # One clock behind the whole observation path: a read model that
        # compared a fake `as_of` against real row timestamps would silently
        # drop evidence out of its own window.
        wall_clock=wall_clock,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        reaper = asyncio.create_task(
            _reap_gateway_state(
                resolved_store,
                resolved_body_store,
                route_mint,
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
    app.state.gateway_route_mint = route_mint
    app.state.gateway_account_pool = resolved_pool
    app.state.gateway_account_state = resolved_account_state
    app.state.gateway_account_admin = resolved_admin

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
        # A governed repository has no unbound mint (ADR-0141 §D4). Refusing here
        # is the whole authorization boundary: v1 carries a caller-selected
        # provider and no route lineage, so one v1 key would be a policy-free
        # lane into an enforced repository — and refusing at the mint means the
        # attempt never becomes a credential, let alone an upstream byte.
        if resolved_settings.governs(payload.repo_slug):
            raise HTTPException(
                status_code=422,
                detail="governed repository requires the v2 route-aware mint",
            )
        if payload.provider_binding not in resolved_settings.upstreams:
            raise HTTPException(status_code=422, detail="provider is unavailable")
        try:
            return resolved_store.mint(payload)
        except KeyPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/control/v2/keys", response_model=MintV2Response)
    async def resolve_and_mint_key(payload: MintV2Request) -> MintV2Response:
        try:
            return route_mint.resolve_and_mint(payload)
        except MintAttemptConflict as exc:
            # Never auto-retried and never silently absorbed: the caller reused
            # one idempotency key for two intents, and only it knows which one
            # it meant.
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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
            evidence_truncated=resolved_active_routes.truncated(),
            pool=resolved_pool,
            administrative=dict(resolved_admin.read().states),
            live=live_facts(pool=resolved_pool, state=resolved_account_state),
        )

    @app.patch(
        "/control/v2/accounts/{account_id}/state",
        response_model=AccountStateResponse,
    )
    async def set_account_state(
        account_id: str, payload: AccountStateRequest
    ) -> AccountStateResponse:
        # Optimistic concurrency in the body rather than an `If-Match` header,
        # matching ADR-0140's policy workspace: one convention for "the revision
        # I composed this against" across the whole routing control plane, and
        # the stale case is a 409 with no partial write either way.
        result = _administer(
            lambda: resolved_admin.set_state(
                account_id,
                payload.administrative_state,
                expected_revision=payload.expected_revision,
                actor=payload.actor,
                recorded_at=_as_utc(wall_clock()).isoformat(),
                registry=resolved_pool.registry,
            )
        )
        return AccountStateResponse(
            account_id=account_id.strip().lower(),
            administrative_state=payload.administrative_state,
            revision=result.revision,
        )

    @app.post(
        "/control/v2/accounts/{account_id}/revoke-leases",
        response_model=RevokeLeasesResponse,
    )
    async def revoke_account_leases(
        account_id: str, payload: RevokeLeasesRequest
    ) -> RevokeLeasesResponse:
        # The revocation happens *inside* the audited mutation, after its
        # revision check: a stale request must revoke nothing, and a committed
        # one must record the ids it actually ended.
        result = _administer(
            lambda: resolved_admin.record_revocation(
                account_id,
                expected_revision=payload.expected_revision,
                actor=payload.actor,
                recorded_at=_as_utc(wall_clock()).isoformat(),
                registry=resolved_pool.registry,
                revoke=lambda: resolved_store.revoke_for_account(account_id),
            )
        )
        return RevokeLeasesResponse(
            account_id=account_id.strip().lower(),
            revoked_key_ids=tuple(result.record.payload.get("revoked_key_ids", ())),
            revision=result.revision,
        )

    @app.get("/control/v2/accounts/audit", response_model=AccountAdminAuditView)
    async def read_account_audit(
        limit: int = Query(default=DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT),
    ) -> AccountAdminAuditView:
        return audit_view(resolved_admin, limit=limit)

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
        retained = resolved_active_routes.recent()
        return build_recent_routes_view(
            routes=retained[:limit],
            now=_as_utc(wall_clock()),
            evidence_since=resolved_active_routes.started_at,
            capacity=resolved_active_routes.recent_capacity,
            retained=len(retained),
            # Truncation is BOTH kinds: rows the ring evicted and rows this page
            # did not return. A page that silently drops 70 of 120 rows while
            # reporting `truncated: false` is exactly the overclaim this view
            # exists to prevent.
            truncated=resolved_active_routes.truncated() or len(retained) > limit,
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
    route_mint: RouteMintStore,
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
        # The idempotency table outlives its keys by exactly one key TTL, so a
        # retry can never outrace a reap into a second lease.
        route_mint.reap_expired_attempts()
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
