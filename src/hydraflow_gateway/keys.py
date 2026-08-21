"""Short-lived, fail-closed virtual keys for gateway data-plane requests."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ulid import ULID

from hydraflow_gateway.models import (
    BodyCapturePolicy,
    GatewayIdentity,
    MintKeyRequest,
    MintKeyResponse,
    RepoClass,
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

    def mint(self, request: MintKeyRequest) -> MintKeyResponse:
        """Mint and retain one high-entropy token for the requested identity."""
        self._validate_policy(request)
        now = self._wall_clock()
        expires_at = now + request.ttl_seconds
        expires_at_monotonic = self._monotonic() + request.ttl_seconds
        key_id = self._id_factory()
        if not key_id or "." in key_id:
            raise ValueError("id_factory returned an invalid key id")
        secret = self._secret_factory()
        if not secret:
            raise ValueError("secret_factory returned an empty secret")
        token = f"{_VIRTUAL_PREFIX}{key_id}.{secret}"
        identity = GatewayIdentity(
            key_id=key_id,
            principal=request.principal(),
            repo_slug=request.repo_slug,
            repo_class=request.repo_class,
            provider_binding=request.provider_binding,
            body_capture_policy=request.body_capture_policy,
            issued_at=_as_datetime(now),
            expires_at=_as_datetime(expires_at),
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
        with self._lock:
            record = self._records.get(key_id)
            if record is None:
                raise InvalidVirtualKey("unknown virtual key")
            if now >= record.expires_at_monotonic:
                del self._records[key_id]
                raise ExpiredVirtualKey("expired virtual key")
            if not secrets.compare_digest(record.token_digest, _digest(token)):
                raise InvalidVirtualKey("invalid virtual key")
            return record.identity

    def revoke(self, key_id: str) -> bool:
        """Revoke a key immediately; return whether it was active."""
        with self._lock:
            return self._records.pop(key_id, None) is not None

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
        return len(expired_ids)

    @property
    def active_count(self) -> int:
        """Return the number of records currently held in memory."""
        with self._lock:
            return len(self._records)

    def _validate_policy(self, request: MintKeyRequest) -> None:
        if request.ttl_seconds > self._max_ttl_seconds:
            raise KeyPolicyError("requested TTL exceeds the configured maximum")
        if (
            request.repo_class is not RepoClass.HYDRAFLOW
            and request.body_capture_policy is BodyCapturePolicy.FULL
        ):
            raise KeyPolicyError(
                "body capture is prohibited for client and personal repos"
            )
        if (
            request.body_capture_policy is BodyCapturePolicy.FULL
            and request.repo_slug.lower() not in self._body_capture_repo_slugs
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
