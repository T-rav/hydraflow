"""Transparent single-attempt streaming data plane for the LLM gateway."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import unquote_to_bytes

import httpx
from fastapi import HTTPException, Request
from starlette.background import BackgroundTask
from starlette.requests import ClientDisconnect
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send
from ulid import ULID

from hydraflow_gateway.ledger import (
    GatewayBodyCapture,
    GatewayBodyStore,
    GatewayLedger,
    GatewayLedgerRow,
)
from hydraflow_gateway.models import GatewayIdentity, GatewayRequestStatus
from hydraflow_gateway.observer import (
    RequestMetadataObserver,
    SseUsageObserver,
    UsageSnapshot,
)
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from model_pricing import ModelPricingTable

_HOP_BY_HOP_HEADERS = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
}
_CLIENT_AUTH_HEADERS = {b"authorization", b"x-api-key"}
_MAX_LEDGER_PATH_CHARS = 2048


class GatewayCredentialError(ValueError):
    """A data-plane request did not present one unambiguous virtual key."""


class RequestBodyTooLarge(Exception):
    """A streamed request crossed the configured byte ceiling."""


@dataclass
class _GatewayAttempt:
    """Own one observation and make every terminal path idempotent."""

    request_id: str
    identity: GatewayIdentity
    request_observer: RequestMetadataObserver
    started_epoch: float
    started_monotonic: float
    path: str | None = None
    capture: GatewayBodyCapture | None = None
    capture_failed: bool = False
    finalized: bool = False

    def finalize(
        self,
        proxy: GatewayProxy,
        *,
        usage: UsageSnapshot | None = None,
        status_code: int,
        completed: bool,
        client_aborted: bool,
    ) -> None:
        """Persist and close this attempt at most once."""
        if self.finalized:
            return
        self.finalized = True
        proxy._finalize_attempt(
            request_id=self.request_id,
            identity=self.identity,
            capture=self.capture,
            request_observer=self.request_observer,
            usage=usage or UsageSnapshot(),
            started_epoch=self.started_epoch,
            started_monotonic=self.started_monotonic,
            path=self.path,
            status_code=status_code,
            completed=completed,
            client_aborted=client_aborted,
            capture_failed=self.capture_failed,
        )


class _ObservedStreamingResponse(StreamingResponse):
    """Finalize an attempt cancelled before its body iterator can run."""

    def __init__(
        self,
        content: AsyncIterator[bytes],
        *,
        status_code: int,
        background: BackgroundTask,
        on_abort: Callable[[], Awaitable[None]],
    ) -> None:
        super().__init__(content, status_code=status_code, background=background)
        self._on_abort = on_abort

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        except (asyncio.CancelledError, ClientDisconnect):
            await self._on_abort()
            raise


class GatewayProxy:
    """Proxy authenticated requests without buffering or retrying upstream."""

    def __init__(
        self,
        *,
        settings: GatewaySettings,
        client: httpx.AsyncClient,
        ledger: GatewayLedger,
        body_store: GatewayBodyStore,
        pricing: ModelPricingTable,
        wall_clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._ledger = ledger
        self._body_store = body_store
        self._pricing = pricing
        self._wall_clock = wall_clock
        self._monotonic = monotonic
        self._request_id_factory = request_id_factory or (lambda: str(ULID()))
        self._telemetry_healthy = True

    @property
    def telemetry_healthy(self) -> bool:
        """Whether observation persistence is still safe for new requests."""
        return self._telemetry_healthy

    def ensure_telemetry_healthy(self) -> None:
        """Fail future traffic closed after a persistence boundary fails."""
        if not self._telemetry_healthy:
            raise HTTPException(
                status_code=503, detail="gateway observation storage is unavailable"
            )

    async def forward(
        self, request: Request, identity: GatewayIdentity
    ) -> StreamingResponse:
        """Start one upstream attempt and return its raw streaming response."""
        upstream = self._settings.upstreams.get(identity.provider_binding)
        if upstream is None:
            raise HTTPException(status_code=503, detail="bound upstream is unavailable")
        attempt = _GatewayAttempt(
            request_id=self._request_id_factory(),
            identity=identity,
            request_observer=RequestMetadataObserver(),
            started_epoch=self._wall_clock(),
            started_monotonic=self._monotonic(),
            path=sanitized_request_path(request),
        )
        try:
            self.ensure_telemetry_healthy()
        except HTTPException as exc:
            attempt.finalize(
                self,
                status_code=exc.status_code,
                completed=False,
                client_aborted=False,
            )
            raise
        try:
            enforce_request_size(request, self._settings.max_request_bytes)
            upstream_url = build_upstream_url(upstream.base_url, request)
        except HTTPException as exc:
            attempt.finalize(
                self,
                status_code=exc.status_code,
                completed=False,
                client_aborted=False,
            )
            raise

        try:
            attempt.capture = self._body_store.start(attempt.request_id, identity)
        except OSError as exc:
            self.mark_telemetry_unhealthy()
            attempt.capture_failed = True
            attempt.finalize(
                self,
                status_code=503,
                completed=False,
                client_aborted=False,
            )
            raise HTTPException(
                status_code=503, detail="gateway observation storage is unavailable"
            ) from exc
        request_bytes = 0
        downstream_stream = request.stream()
        try:
            first_chunk = await anext(downstream_stream, b"")
        except ClientDisconnect as exc:
            attempt.finalize(
                self,
                status_code=499,
                completed=False,
                client_aborted=True,
            )
            raise HTTPException(status_code=499, detail="client disconnected") from exc
        except asyncio.CancelledError:
            attempt.finalize(
                self,
                status_code=499,
                completed=False,
                client_aborted=True,
            )
            raise

        async def request_content() -> AsyncIterator[bytes]:
            nonlocal request_bytes
            chunks = _prepend_chunk(first_chunk, downstream_stream)
            async for chunk in chunks:
                request_bytes += len(chunk)
                if request_bytes > self._settings.max_request_bytes:
                    raise RequestBodyTooLarge
                attempt.request_observer.feed(chunk)
                if attempt.capture is not None and not attempt.capture_failed:
                    try:
                        attempt.capture.write_request(chunk)
                    except OSError:
                        attempt.capture_failed = True
                        self.mark_telemetry_unhealthy()
                yield chunk

        content = request_content() if first_chunk else None
        timeout = httpx.Timeout(
            connect=self._settings.connect_timeout_seconds,
            read=None,
            write=self._settings.write_timeout_seconds,
            pool=self._settings.pool_timeout_seconds,
        )
        upstream_request = httpx.Request(
            request.method,
            upstream_url,
            headers=replace_request_headers(request.headers.raw, upstream),
            content=content,
            extensions={"timeout": timeout.as_dict()},
        )
        try:
            upstream_response = await self._client.send(
                upstream_request,
                stream=True,
                follow_redirects=False,
            )
        except (ClientDisconnect, RequestBodyTooLarge) as exc:
            status_code = 413 if isinstance(exc, RequestBodyTooLarge) else 499
            attempt.finalize(
                self,
                status_code=status_code,
                completed=False,
                client_aborted=isinstance(exc, ClientDisconnect),
            )
            detail = (
                "request body is too large"
                if isinstance(exc, RequestBodyTooLarge)
                else "client disconnected"
            )
            raise HTTPException(status_code=status_code, detail=detail) from exc
        except asyncio.CancelledError:
            attempt.finalize(
                self,
                status_code=499,
                completed=False,
                client_aborted=True,
            )
            raise
        except httpx.RequestError as exc:
            attempt.finalize(
                self,
                status_code=502,
                completed=False,
                client_aborted=False,
            )
            raise HTTPException(status_code=502, detail="upstream unavailable") from exc

        response_observer = SseUsageObserver()
        completed = False
        client_aborted = False

        async def finalize_response(*, aborted: bool, complete: bool) -> None:
            try:
                await upstream_response.aclose()
            finally:
                if not attempt.finalized:
                    attempt.finalize(
                        self,
                        usage=response_observer.finish(),
                        status_code=499 if aborted else upstream_response.status_code,
                        completed=complete,
                        client_aborted=aborted,
                    )

        async def response_content() -> AsyncIterator[bytes]:
            nonlocal completed, client_aborted
            try:
                async for chunk in upstream_response.aiter_raw():
                    response_observer.feed(chunk)
                    if attempt.capture is not None and not attempt.capture_failed:
                        try:
                            attempt.capture.write_response(chunk)
                        except OSError:
                            attempt.capture_failed = True
                            self.mark_telemetry_unhealthy()
                    yield chunk
                completed = True
            except (asyncio.CancelledError, GeneratorExit):
                client_aborted = True
                raise
            finally:
                await finalize_response(aborted=client_aborted, complete=completed)

        async def abort_response() -> None:
            await finalize_response(aborted=True, complete=False)

        response = _ObservedStreamingResponse(
            response_content(),
            status_code=upstream_response.status_code,
            background=BackgroundTask(abort_response),
            on_abort=abort_response,
        )
        response.raw_headers = filter_response_headers(upstream_response.headers.raw)
        return response

    def _finalize_attempt(
        self,
        *,
        request_id: str,
        identity: GatewayIdentity,
        capture: GatewayBodyCapture | None,
        request_observer: RequestMetadataObserver,
        usage: UsageSnapshot,
        started_epoch: float,
        started_monotonic: float,
        path: str | None,
        status_code: int,
        completed: bool,
        client_aborted: bool,
        capture_failed: bool,
    ) -> None:
        if capture is not None:
            try:
                capture.close()
            except OSError:
                capture_failed = True
                self.mark_telemetry_unhealthy()
        # Partial usage is never a price: an aborted or unfinished stream, or
        # one whose usage event never arrived, is cost-unknown rather than $0.
        usage_complete = completed and not client_aborted and usage.usage_observed
        cost_usd = (
            self._pricing.estimate_cost(
                usage.model_served,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                # Every gateway upstream speaks the Anthropic stream shape,
                # whose ``input_tokens`` EXCLUDES cache — regardless of the
                # model's table flag, which describes its one-shot
                # OpenAI-compat face (prompt_tokens INCLUDES cache).
                input_includes_cache=False,
            )
            if usage.model_served is not None and usage_complete
            else None
        )
        request_status = GatewayRequestStatus.COMPLETED
        if client_aborted:
            request_status = GatewayRequestStatus.CLIENT_ABORTED
        elif not completed:
            request_status = GatewayRequestStatus.UPSTREAM_ERROR
        row = GatewayLedgerRow(
            request_id=request_id,
            key_id=identity.key_id,
            principal=identity.principal,
            repo_slug=identity.repo_slug,
            repo_class=identity.repo_class,
            body_capture_policy=identity.body_capture_policy,
            timestamp=datetime.fromtimestamp(started_epoch, tz=UTC),
            latency_ms=max(0.0, (self._monotonic() - started_monotonic) * 1000),
            status_code=status_code,
            status=request_status,
            upstream_provider=identity.provider_binding,
            path=path,
            model_requested=request_observer.model_requested(),
            model_served=usage.model_served,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=usage.cache_read_tokens,
            cache_creation_input_tokens=usage.cache_write_tokens,
            completed=completed,
            client_aborted=client_aborted,
            observer_malformed_events=usage.malformed_events,
            body_capture_id=capture.capture_id if capture is not None else None,
            body_capture_complete=(None if capture is None else not capture_failed),
            usage_complete=usage_complete,
            cost_usd=cost_usd,
            cost_unknown=cost_usd is None,
        )
        try:
            self._ledger.append(row)
        except OSError:
            self.mark_telemetry_unhealthy()

    def mark_telemetry_unhealthy(self) -> None:
        """Trip readiness after observation persistence becomes unreliable."""
        self._telemetry_healthy = False


def extract_virtual_token(raw_headers: Sequence[tuple[bytes, bytes]]) -> str:
    """Extract exactly one bearer or x-api-key virtual credential."""
    authorizations = [
        value.strip() for name, value in raw_headers if name.lower() == b"authorization"
    ]
    api_keys = [
        value.strip() for name, value in raw_headers if name.lower() == b"x-api-key"
    ]
    if len(authorizations) + len(api_keys) != 1:
        raise GatewayCredentialError("exactly one gateway credential is required")
    if api_keys:
        token_bytes = api_keys[0]
    else:
        scheme, separator, token_bytes = authorizations[0].partition(b" ")
        if not separator or scheme.lower() != b"bearer":
            raise GatewayCredentialError("authorization must use Bearer")
        token_bytes = token_bytes.strip()
    if not token_bytes:
        raise GatewayCredentialError("gateway credential is empty")
    try:
        return token_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise GatewayCredentialError("gateway credential must be ASCII") from exc


def sanitized_request_path(request: Request) -> str:
    """Return the decoded request path, query string stripped and bounded."""
    path = request.url.path.split("?", maxsplit=1)[0]
    return path[:_MAX_LEDGER_PATH_CHARS]


def enforce_request_size(request: Request, max_request_bytes: int) -> None:
    """Reject a declared oversized body before opening any upstream request."""
    values = [
        value.strip()
        for name, value in request.headers.raw
        if name.lower() == b"content-length"
    ]
    if not values:
        return
    if len(values) != 1:
        raise HTTPException(status_code=400, detail="ambiguous Content-Length")
    try:
        content_length = int(values[0])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid Content-Length") from exc
    if content_length < 0:
        raise HTTPException(status_code=400, detail="invalid Content-Length")
    if content_length > max_request_bytes:
        raise HTTPException(status_code=413, detail="request body is too large")


def build_upstream_url(base_url: str, request: Request) -> httpx.URL:
    """Preserve the raw path/query while pinning scheme and authority."""
    base = httpx.URL(base_url)
    base_path = base.raw_path.split(b"?", maxsplit=1)[0].rstrip(b"/")
    raw_path_value = request.scope.get("raw_path")
    raw_path = (
        bytes(raw_path_value)
        if isinstance(raw_path_value, bytes)
        else request.url.path.encode("utf-8")
    )
    if not raw_path.startswith(b"/"):
        raw_path = b"/" + raw_path
    _reject_dot_segments(raw_path)
    combined = base_path + raw_path
    query_value = request.scope.get("query_string", b"")
    if isinstance(query_value, bytes) and query_value:
        combined += b"?" + query_value
    return base.copy_with(raw_path=combined)


async def _prepend_chunk(
    first_chunk: bytes, remainder: AsyncIterator[bytes]
) -> AsyncIterator[bytes]:
    yield first_chunk
    async for chunk in remainder:
        if chunk:
            yield chunk


def _reject_dot_segments(raw_path: bytes) -> None:
    """Reject literal or repeatedly encoded path traversal segments."""
    candidate = raw_path
    for _ in range(16):
        normalized = candidate.replace(b"\\", b"/")
        if any(segment in {b".", b".."} for segment in normalized.split(b"/")):
            raise HTTPException(status_code=400, detail="invalid upstream path")
        if b"\x00" in candidate:
            raise HTTPException(status_code=400, detail="invalid upstream path")
        decoded = unquote_to_bytes(candidate)
        if decoded == candidate:
            return
        candidate = decoded
    raise HTTPException(status_code=400, detail="upstream path is too deeply encoded")


def replace_request_headers(
    raw_headers: Sequence[tuple[bytes, bytes]], upstream: UpstreamSettings
) -> list[tuple[bytes, bytes]]:
    """Remove transport/client auth headers and inject server-owned auth."""
    blocked = _connection_scoped_names(raw_headers) | _CLIENT_AUTH_HEADERS | {b"host"}
    forwarded = [
        (name, value) for name, value in raw_headers if name.lower() not in blocked
    ]
    provider_key = upstream.api_key.get_secret_value().encode("ascii")
    if upstream.auth_style == UpstreamAuthStyle.X_API_KEY:
        forwarded.append((b"x-api-key", provider_key))
    else:
        forwarded.append((b"authorization", b"Bearer " + provider_key))
    return forwarded


def filter_response_headers(
    raw_headers: Iterable[tuple[bytes, bytes]],
) -> list[tuple[bytes, bytes]]:
    """Remove transport fields and any provider credential echo."""
    headers = list(raw_headers)
    blocked = _connection_scoped_names(headers) | _CLIENT_AUTH_HEADERS
    return [(name, value) for name, value in headers if name.lower() not in blocked]


def _connection_scoped_names(
    raw_headers: Iterable[tuple[bytes, bytes]],
) -> set[bytes]:
    blocked = set(_HOP_BY_HOP_HEADERS)
    for name, value in raw_headers:
        if name.lower() != b"connection":
            continue
        blocked.update(
            token.strip().lower() for token in value.split(b",") if token.strip()
        )
    return blocked
