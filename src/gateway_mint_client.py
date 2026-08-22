"""Per-spawn gateway credential lifecycle: mint, bind, renew, revoke.

Extracted from ``runner_utils`` when ADR-0141's route-aware v2 mint pushed that
module past the mass threshold. The cluster is cohesive on its own terms: it is
the entire HydraFlow-side client for the gateway's control plane, and nothing in
it knows about prompts, telemetry, or subprocess streaming.

``runner_utils`` re-exports every public name here so the seams keep one import
identity — a second definition of ``GatewayMintError`` or ``GatewayControlClient``
would be two types that look alike and never compare equal.

Two properties belong to this module rather than to its callers:

* **Gateway selection is fail-closed.** A mint failure raises
  :class:`GatewayMintError` before any worker process starts; it never degrades
  to an ambient provider credential.
* **A governed refusal is a body, not a status.** The v2 mint answers every
  well-formed attempt with 200 and a decision, so
  :func:`_require_selected_route_decision` is what turns a held, rejected, or
  replayed outcome into the same fail-closed error a transport failure produces.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol

import httpx

if TYPE_CHECKING:
    from config import HydraFlowConfig

# Deliberately the same logger as ``runner_utils``: these warnings are read as
# one subsystem's output, and renaming the channel would silently drop them from
# an operator's existing filters.
logger = logging.getLogger("hydraflow.runner_utils")

# A key must remain valid beyond the subprocess deadline so scheduling jitter,
# container startup, and the final response bytes cannot race token expiry.
_GATEWAY_LEASE_GRACE_SECONDS = 60


class GatewayMintError(RuntimeError):
    """The gateway was selected but a per-spawn credential could not be minted."""


@dataclass(frozen=True, slots=True)
class GatewayMintRequest:
    """Stable runner-side contract for ``POST /control/v1/keys``."""

    principal_kind: Literal["loop", "role", "spawn", "person", "team"]
    principal_id: str
    spawn_id: str
    session_id: str | None
    repo_slug: str
    repo_class: Literal["hydraflow", "client", "personal"]
    provider_binding: Literal["anthropic", "zai-harness"]
    capture_bodies: bool
    ttl_seconds: int
    # Optional work attribution stamped onto the key's principal and hence
    # every ledger row it produces. Omitted from the wire when unset.
    issue_number: int | None = None
    pr_number: int | None = None

    def wire_payload(self) -> dict[str, object]:
        """JSON body for ``POST /control/v1/keys``; attribution only when set
        so an older gateway (``extra="forbid"``) keeps accepting the mint."""
        payload: dict[str, object] = {
            "principal_kind": self.principal_kind,
            "principal_id": self.principal_id,
            "spawn_id": self.spawn_id,
            "session_id": self.session_id,
            "repo_slug": self.repo_slug,
            "repo_class": self.repo_class,
            "provider_binding": self.provider_binding,
            "capture_bodies": self.capture_bodies,
            "ttl_seconds": self.ttl_seconds,
        }
        if self.issue_number is not None:
            payload["issue_number"] = self.issue_number
        if self.pr_number is not None:
            payload["pr_number"] = self.pr_number
        return payload


@dataclass(frozen=True, slots=True)
class GatewayMintV2Request:
    """Runner-side contract for ``POST /control/v2/keys`` (ADR-0141).

    Identity and intent only. There is deliberately no ``provider_binding``,
    ``account_id``, or upstream field: the gateway derives the account from the
    model the policy chose, so a governed spawn cannot pick its own lane even by
    accident. ``dispatch_id`` is stable across one logical worker dispatch;
    ``mint_attempt_id`` is the idempotency key and changes for every new key.
    """

    mint_attempt_id: str
    dispatch_id: str
    principal_kind: Literal["loop", "role", "spawn", "person", "team"]
    principal_id: str
    spawn_id: str
    session_id: str | None
    repo: str
    repo_slug: str
    repo_class: Literal["hydraflow", "client", "personal"]
    worker_role: str | None
    request_face: str
    requirement_kind: str
    requirement_value: str
    requested_model: str
    effective_model: str
    route_decision_id: str
    policy_id: str | None
    policy_revision: int
    snapshot_hash: str
    capture_bodies: bool
    ttl_seconds: int
    issue_number: int | None = None
    pr_number: int | None = None

    def wire_payload(self) -> dict[str, object]:
        """JSON body for ``POST /control/v2/keys``; attribution only when set."""
        payload: dict[str, object] = {
            "mint_attempt_id": self.mint_attempt_id,
            "dispatch_id": self.dispatch_id,
            "principal_kind": self.principal_kind,
            "principal_id": self.principal_id,
            "spawn_id": self.spawn_id,
            "session_id": self.session_id,
            "repo": self.repo,
            "repo_slug": self.repo_slug,
            "repo_class": self.repo_class,
            "worker_role": self.worker_role,
            "request_face": self.request_face,
            "requirement_kind": self.requirement_kind,
            "requirement_value": self.requirement_value,
            "requested_model": self.requested_model,
            "effective_model": self.effective_model,
            "route_decision_id": self.route_decision_id,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "snapshot_hash": self.snapshot_hash,
            "capture_bodies": self.capture_bodies,
            "ttl_seconds": self.ttl_seconds,
        }
        if self.issue_number is not None:
            payload["issue_number"] = self.issue_number
        if self.pr_number is not None:
            payload["pr_number"] = self.pr_number
        return payload

    def with_new_attempt(self) -> GatewayMintV2Request:
        """A fresh attempt of the SAME dispatch, for a renewal or a retry.

        Reusing the attempt id would be read by the gateway as a replay and
        answered with a withheld token — correct for a duplicate submission, and
        exactly wrong for a lease that legitimately needs a successor key.
        """
        return replace(self, mint_attempt_id=uuid.uuid4().hex)


@dataclass(frozen=True, slots=True)
class GatewayMintCredential:
    """Validated subset of the gateway mint response used by a worker spawn."""

    key_id: str
    token: str = field(repr=False)
    expires_at: str


class GatewayControlClient(Protocol):
    """Injectable key-lifecycle boundary for the gateway control plane."""

    async def mint_key(
        self,
        *,
        base_url: str,
        control_token: str,
        request: GatewayMintRequest | GatewayMintV2Request,
    ) -> GatewayMintCredential: ...

    async def revoke_key(
        self,
        *,
        base_url: str,
        control_token: str,
        key_id: str,
    ) -> bool: ...


class _HttpGatewayControlClient:
    """Minimal production adapter for the gateway control endpoint."""

    async def mint_key(
        self,
        *,
        base_url: str,
        control_token: str,
        request: GatewayMintRequest | GatewayMintV2Request,
    ) -> GatewayMintCredential:
        governed = isinstance(request, GatewayMintV2Request)
        route = "/control/v2/keys" if governed else "/control/v1/keys"
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}{route}",
                    headers={"Authorization": f"Bearer {control_token}"},
                    json=request.wire_payload(),
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            # Never include a response body or credential in this exception: the
            # failure can flow through caretaker logs.
            raise GatewayMintError("gateway credential mint failed") from None

        if governed:
            _require_selected_route_decision(payload)
        safe_key_id = _safe_gateway_key_id(
            payload.get("key_id") if isinstance(payload, dict) else None
        )
        try:
            if not isinstance(payload, dict):
                raise GatewayMintError("gateway mint returned an invalid response")
            key_id = payload.get("key_id")
            token = payload.get("token")
            expires_at = payload.get("expires_at")
            if (
                not isinstance(key_id, str)
                or not isinstance(token, str)
                or not isinstance(expires_at, str)
            ):
                raise GatewayMintError("gateway mint returned an invalid response")
            credential = GatewayMintCredential(
                key_id=key_id,
                token=token,
                expires_at=expires_at,
            )
            _validate_gateway_credential(credential)
        except GatewayMintError:
            if safe_key_id is not None:
                await self._cleanup_invalid_mint(
                    base_url=base_url,
                    control_token=control_token,
                    key_id=safe_key_id,
                )
            raise GatewayMintError(
                "gateway mint returned an invalid response"
            ) from None
        return credential

    async def _cleanup_invalid_mint(
        self,
        *,
        base_url: str,
        control_token: str,
        key_id: str,
    ) -> None:
        """Best-effort revoke a key returned with malformed credential data."""

        try:
            revoked = await self.revoke_key(
                base_url=base_url,
                control_token=control_token,
                key_id=key_id,
            )
            if not revoked:
                raise GatewayMintError(
                    "gateway invalid-mint revocation was not acknowledged"
                )
        except GatewayMintError:
            # TTL remains the fail-closed fallback. Never retain or log the
            # malformed response, which can contain virtual secret material.
            logger.warning(
                "gateway invalid-mint cleanup failed for key_id=%s",
                key_id,
            )

    async def revoke_key(
        self,
        *,
        base_url: str,
        control_token: str,
        key_id: str,
    ) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                response = await client.delete(
                    f"{base_url.rstrip('/')}/control/v1/keys/{key_id}",
                    headers={"Authorization": f"Bearer {control_token}"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            # Do not retain an exception containing the authenticated request;
            # cleanup failures can be logged by long-lived caretaker processes.
            raise GatewayMintError("gateway credential revocation failed") from None
        revoked = payload.get("revoked")
        if not isinstance(revoked, bool):
            raise GatewayMintError("gateway revoke returned an invalid response")
        return revoked


def _parse_gateway_expiry(value: str) -> datetime:
    """Parse a control-plane expiry without ever including it in an error."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise GatewayMintError("gateway mint returned an invalid expiry") from None
    if parsed.tzinfo is None:
        raise GatewayMintError("gateway mint returned an invalid expiry")
    return parsed.astimezone(UTC)


def _require_selected_route_decision(payload: object) -> None:
    """Turn a held or rejected v2 decision into a fail-closed mint error.

    The gateway answers every well-formed attempt with 200 and a decision, so a
    refusal is a *body*, not a status code. Collapsing it into
    :class:`GatewayMintError` puts a governed refusal on the same path a failed
    mint already takes at every seam — a pre-spawn crash that can never fall
    through to an ambient credential. The reason code travels; the body does not.
    """
    if not isinstance(payload, dict):
        raise GatewayMintError("gateway mint returned an invalid response")
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        raise GatewayMintError("gateway mint returned no routing decision")
    outcome = decision.get("outcome")
    if outcome != "selected":
        reason = decision.get("reason")
        raise GatewayMintError(
            f"gateway refused the governed route: {outcome}/"
            f"{reason if isinstance(reason, str) else 'unknown'}"[:200]
        )
    state = payload.get("credential_state")
    if state != "issued":
        # A replayed attempt: the lease exists but its token is gone for good.
        # Spawning without a credential is not an option, and silently minting a
        # second lease is the duplicate-billing failure v2 exists to prevent.
        raise GatewayMintError(
            f"gateway withheld the governed credential: {state}"[:200]
        )


def _safe_gateway_key_id(value: object) -> str | None:
    """Return a path-safe key ID suitable for malformed-mint cleanup."""

    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        return None
    if not value.isascii() or any(
        not (char.isalnum() or char in "-_") for char in value
    ):
        return None
    return value


def _validate_gateway_credential(credential: GatewayMintCredential) -> None:
    if not credential.key_id or not credential.token or not credential.expires_at:
        raise GatewayMintError("gateway mint returned an incomplete credential")
    _parse_gateway_expiry(credential.expires_at)


def _gateway_ttl_seconds(config: HydraFlowConfig, timeout_seconds: float | None) -> int:
    """Return a TTL that covers one complete subprocess attempt plus cleanup."""

    configured = int(getattr(config, "gateway_key_ttl_seconds", 3660))
    if timeout_seconds is None:
        return configured
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise GatewayMintError("gateway spawn timeout must be positive and finite")
    return max(configured, math.ceil(timeout_seconds) + _GATEWAY_LEASE_GRACE_SECONDS)


@dataclass(slots=True)
class _GatewayKeyLease:
    """Private retained control-plane state for one worker spawn."""

    base_url: str
    control_token: str = field(repr=False)
    request: GatewayMintRequest | GatewayMintV2Request
    client: GatewayControlClient = field(repr=False)
    credential: GatewayMintCredential = field(repr=False)
    revoked: bool = False

    @property
    def key_id(self) -> str:
        return self.credential.key_id

    @property
    def expires_at(self) -> str:
        return self.credential.expires_at

    def seconds_remaining(self) -> float:
        return (
            _parse_gateway_expiry(self.expires_at) - datetime.now(UTC)
        ).total_seconds()

    async def renew_if_needed(self, *, min_validity_seconds: float) -> bool:
        """Remint only when this lease cannot cover one more full attempt."""

        if self.revoked:
            raise GatewayMintError("gateway credential lease is already closed")
        if self.seconds_remaining() >= min_validity_seconds:
            return False

        previous_key_id = self.key_id
        # A governed renewal is a NEW attempt of the SAME dispatch. Replaying the
        # original attempt id would be answered with a withheld token, which is
        # right for a duplicate submission and wrong for a successor key.
        if isinstance(self.request, GatewayMintV2Request):
            self.request = self.request.with_new_attempt()
        credential = await self.client.mint_key(
            base_url=self.base_url,
            control_token=self.control_token,
            request=self.request,
        )
        _validate_gateway_credential(credential)
        self.credential = credential
        try:
            revoked = await self.client.revoke_key(
                base_url=self.base_url,
                control_token=self.control_token,
                key_id=previous_key_id,
            )
            if not revoked:
                raise GatewayMintError(
                    "gateway superseded-key revocation was not acknowledged"
                )
        except Exception:
            # The superseded credential still has its short TTL. Do not discard
            # the successfully minted replacement or expose control credentials.
            logger.warning(
                "gateway superseded-key revocation failed for key_id=%s",
                previous_key_id,
            )
        return True

    async def revoke(self) -> None:
        if self.revoked:
            return
        revoked = await self.client.revoke_key(
            base_url=self.base_url,
            control_token=self.control_token,
            key_id=self.key_id,
        )
        if not revoked:
            raise GatewayMintError("gateway key revocation was not acknowledged")
        self.revoked = True


class _RoutedHarnessEnv(dict[str, str]):
    """Env mapping with non-exported transport metadata for spawn boundaries."""

    __slots__ = ("transport", "_gateway_lease")

    def __init__(
        self,
        values: dict[str, str],
        *,
        transport: str,
        gateway_lease: _GatewayKeyLease | None = None,
    ) -> None:
        super().__init__(values)
        self.transport = transport
        self._gateway_lease = gateway_lease

    @property
    def key_id(self) -> str | None:
        return self._gateway_lease.key_id if self._gateway_lease is not None else None

    @property
    def expires_at(self) -> str | None:
        return (
            self._gateway_lease.expires_at if self._gateway_lease is not None else None
        )

    def __repr__(self) -> str:
        redacted = {
            key: "<redacted>" if key == "ANTHROPIC_AUTH_TOKEN" else value
            for key, value in self.items()
        }
        return (
            f"{type(self).__name__}({redacted!r}, transport={self.transport!r}, "
            f"key_id={self.key_id!r}, expires_at={self.expires_at!r})"
        )

    __str__ = __repr__


async def renew_gateway_key_if_needed(
    harness_env: dict[str, str], *, min_validity_seconds: float
) -> bool:
    """Renew a gateway lease only when it cannot cover another attempt."""

    if not isinstance(harness_env, _RoutedHarnessEnv):
        return False
    lease = harness_env._gateway_lease
    if lease is None:
        return False
    renewed = await lease.renew_if_needed(min_validity_seconds=min_validity_seconds)
    if renewed:
        harness_env["ANTHROPIC_AUTH_TOKEN"] = lease.credential.token
    return renewed


async def revoke_gateway_key(harness_env: dict[str, str]) -> None:
    """Best-effort close of a per-spawn gateway lease; TTL remains fallback."""

    if not isinstance(harness_env, _RoutedHarnessEnv):
        return
    lease = harness_env._gateway_lease
    if lease is None:
        return
    try:
        await lease.revoke()
    except Exception:
        # Cleanup must never mask the worker's result or original exception.
        logger.warning(
            "gateway key revocation failed for key_id=%s",
            lease.key_id,
        )
