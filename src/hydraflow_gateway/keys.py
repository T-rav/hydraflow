"""Short-lived, fail-closed virtual keys for gateway data-plane requests."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ulid import ULID

from hydraflow_gateway.models import (
    BodyCapturePolicy,
    GatewayIdentity,
    MintKeyRequest,
    MintKeyResponse,
    Principal,
    ProviderBinding,
    RepoClass,
    RouteBinding,
)

_VIRTUAL_PREFIX = "hfgw_"


class VirtualKeyError(ValueError):
    """Base error for virtual-key validation without secret-bearing messages."""


class InvalidVirtualKey(VirtualKeyError):
    """The presented token is malformed, unknown, revoked, or incorrect."""


class ExpiredVirtualKey(VirtualKeyError):
    """The presented token has passed its immutable expiry."""


class KeyPolicyError(ValueError):
    """A mint request violates TTL or repository capture policy."""


@dataclass(frozen=True)
class _KeyRecord:
    identity: GatewayIdentity
    token_digest: bytes = field(repr=False)
    expires_at_monotonic: float


class VirtualKeyStore:
    """In-memory virtual-key store intended for a single gateway worker.

    Only a SHA-256 digest of each high-entropy token is retained. Process
    restart invalidates every key, which is deliberately fail-closed for v1.
    """

    def __init__(
        self,
        *,
        max_ttl_seconds: int,
        wall_clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] | None = None,
        secret_factory: Callable[[], str] | None = None,
        body_capture_repo_slugs: frozenset[str] = frozenset(),
    ) -> None:
        if max_ttl_seconds <= 0:
            raise ValueError("max_ttl_seconds must be positive")
        self._max_ttl_seconds = max_ttl_seconds
        self._wall_clock = wall_clock
        self._monotonic = monotonic
        self._id_factory = id_factory or (lambda: str(ULID()))
        self._secret_factory = secret_factory or (lambda: secrets.token_urlsafe(32))
        self._body_capture_repo_slugs = frozenset(
            slug.lower() for slug in body_capture_repo_slugs
        )
        self._records: dict[str, _KeyRecord] = {}
        self._lock = threading.Lock()
        self._on_release: Callable[[str], object] | None = None

    def on_release(self, callback: Callable[[str], object]) -> None:
        """Register the one hook called when a key leaves this store.

        Every path that ends a key — explicit revoke, expiry noticed on resolve,
        the reaper, and an account-wide revocation — funnels through
        :meth:`_release`, and the callback is invoked exactly once per key
        because the dict removal is what decides. That is what lets an account's
        lease accounting be correct without every call site remembering to
        release: ADR-0142's "cancellation and expiry release capacity exactly
        once" is a property of this seam rather than of four callers.
        """
        self._on_release = callback

    def mint(self, request: MintKeyRequest) -> MintKeyResponse:
        """Mint and retain one high-entropy token for the requested identity."""
        self._validate_policy(
            ttl_seconds=request.ttl_seconds,
            repo_class=request.repo_class,
            repo_slug=request.repo_slug,
            body_capture_policy=request.body_capture_policy,
        )
        return self._mint(
            principal=request.principal(),
            repo_slug=request.repo_slug,
            repo_class=request.repo_class,
            provider_binding=request.provider_binding,
            body_capture_policy=request.body_capture_policy,
            ttl_seconds=request.ttl_seconds,
            route_binding=None,
        )

    def mint_bound(
        self,
        *,
        principal: Principal,
        repo_slug: str,
        repo_class: RepoClass,
        provider_binding: ProviderBinding,
        capture_bodies: bool,
        ttl_seconds: int,
        route_binding: RouteBinding,
    ) -> MintKeyResponse:
        """Mint a key whose route is fixed for its whole lifetime (ADR-0141).

        Same store, same token shape, same policy gate as :meth:`mint` — the only
        difference is that the resulting identity carries a ``route_binding``, so
        "this key is governed" is a fact the data plane reads off the identity
        rather than a claim any caller makes.
        """
        capture_policy = (
            BodyCapturePolicy.FULL
            if capture_bodies
            else BodyCapturePolicy.METADATA_ONLY
        )
        self._validate_policy(
            ttl_seconds=ttl_seconds,
            repo_class=repo_class,
            repo_slug=repo_slug,
            body_capture_policy=capture_policy,
        )
        return self._mint(
            principal=principal,
            repo_slug=repo_slug,
            repo_class=repo_class,
            provider_binding=provider_binding,
            body_capture_policy=capture_policy,
            ttl_seconds=ttl_seconds,
            route_binding=route_binding,
        )

    def _mint(
        self,
        *,
        principal: Principal,
        repo_slug: str,
        repo_class: RepoClass,
        provider_binding: ProviderBinding,
        body_capture_policy: BodyCapturePolicy,
        ttl_seconds: int,
        route_binding: RouteBinding | None,
    ) -> MintKeyResponse:
        now = self._wall_clock()
        expires_at = now + ttl_seconds
        expires_at_monotonic = self._monotonic() + ttl_seconds
        key_id = self._id_factory()
        if not key_id or "." in key_id:
            raise ValueError("id_factory returned an invalid key id")
        secret = self._secret_factory()
        if not secret:
            raise ValueError("secret_factory returned an empty secret")
        token = f"{_VIRTUAL_PREFIX}{key_id}.{secret}"
        identity = GatewayIdentity(
            key_id=key_id,
            principal=principal,
            repo_slug=repo_slug,
            repo_class=repo_class,
            provider_binding=provider_binding,
            body_capture_policy=body_capture_policy,
            issued_at=_as_datetime(now),
            expires_at=_as_datetime(expires_at),
            route_binding=route_binding,
        )
        record = _KeyRecord(
            identity=identity,
            token_digest=_digest(token),
            expires_at_monotonic=expires_at_monotonic,
        )
        with self._lock:
            if key_id in self._records:
                raise ValueError("id_factory returned a duplicate key id")
            self._records[key_id] = record
        return MintKeyResponse(
            key_id=key_id,
            token=token,
            expires_at=identity.expires_at,
        )

    def resolve(self, token: str) -> GatewayIdentity:
        """Return identity for a valid token or raise without echoing the token."""
        key_id = _key_id_from_token(token)
        now = self._monotonic()
        expired = False
        with self._lock:
            record = self._records.get(key_id)
            if record is None:
                raise InvalidVirtualKey("unknown virtual key")
            if now >= record.expires_at_monotonic:
                del self._records[key_id]
                expired = True
            elif not secrets.compare_digest(record.token_digest, _digest(token)):
                raise InvalidVirtualKey("invalid virtual key")
        if expired:
            # Announced outside the lock, like every other release: the callback
            # takes the capacity table's lock, and taking two locks in two orders
            # across this store's methods is how a deadlock arrives later.
            self._release((key_id,))
            raise ExpiredVirtualKey("expired virtual key")
        return record.identity

    def revoke(self, key_id: str) -> bool:
        """Revoke a key immediately; return whether it was active."""
        with self._lock:
            removed = self._records.pop(key_id, None) is not None
        if removed:
            self._release((key_id,))
        return removed

    def revoke_for_account(self, account_id: str) -> tuple[str, ...]:
        """Revoke every route-bound key on one account; return the ids ended.

        The explicit blast-radius action behind ``revoke-leases``. It names only
        route-bound keys, because an unbound v1 key has no account to belong to —
        revoking those as collateral would let an account-scoped action end
        leases it was never told about.
        """
        target = account_id.strip().lower()
        with self._lock:
            revoked = [
                key_id
                for key_id, record in self._records.items()
                if record.identity.route_binding is not None
                and record.identity.route_binding.account_id.strip().lower() == target
            ]
            for key_id in revoked:
                del self._records[key_id]
        self._release(revoked)
        return tuple(revoked)

    def reap_expired(self) -> int:
        """Remove every expired key and return the number reaped."""
        now = self._monotonic()
        with self._lock:
            expired_ids = [
                key_id
                for key_id, record in self._records.items()
                if now >= record.expires_at_monotonic
            ]
            for key_id in expired_ids:
                del self._records[key_id]
        self._release(expired_ids)
        return len(expired_ids)

    def _release(self, key_ids: Sequence[str]) -> None:
        """Announce keys that have left the store, exactly once each."""
        if self._on_release is None:
            return
        for key_id in key_ids:
            self._on_release(key_id)

    @property
    def active_count(self) -> int:
        """Return the number of records currently held in memory."""
        with self._lock:
            return len(self._records)

    def lease_identities(self) -> tuple[GatewayIdentity, ...]:
        """Return the non-secret identity of every unexpired key, oldest first.

        Only :class:`GatewayIdentity` leaves the store: the token digest stays
        private, and no caller can reach token material through this seam.
        """
        now = self._monotonic()
        with self._lock:
            identities = [
                record.identity
                for record in self._records.values()
                if now < record.expires_at_monotonic
            ]
        return tuple(sorted(identities, key=lambda item: (item.issued_at, item.key_id)))

    def _validate_policy(
        self,
        *,
        ttl_seconds: int,
        repo_class: RepoClass,
        repo_slug: str,
        body_capture_policy: BodyCapturePolicy,
    ) -> None:
        if ttl_seconds > self._max_ttl_seconds:
            raise KeyPolicyError("requested TTL exceeds the configured maximum")
        if (
            repo_class is not RepoClass.HYDRAFLOW
            and body_capture_policy is BodyCapturePolicy.FULL
        ):
            raise KeyPolicyError(
                "body capture is prohibited for client and personal repos"
            )
        if (
            body_capture_policy is BodyCapturePolicy.FULL
            and repo_slug.lower() not in self._body_capture_repo_slugs
        ):
            raise KeyPolicyError(
                "body capture is not authorized for the requested repository"
            )


def _key_id_from_token(token: str) -> str:
    if not token.startswith(_VIRTUAL_PREFIX):
        raise InvalidVirtualKey("invalid virtual key format")
    key_and_secret = token[len(_VIRTUAL_PREFIX) :]
    key_id, separator, secret = key_and_secret.partition(".")
    if not separator or not key_id or not secret:
        raise InvalidVirtualKey("invalid virtual key format")
    return key_id


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _as_datetime(epoch_seconds: float) -> datetime:
    return datetime.fromtimestamp(epoch_seconds, tz=UTC)
