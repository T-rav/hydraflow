"""The operator write boundary for the dashboard's control surfaces (ADR-0140).

ADR-0138 §D5 recorded a precondition rather than a convenience: HydraFlow's
dashboard has no in-process authentication, so its operator boundary *is* the
loopback socket bind. That was acceptable while every gateway route was
read-only and every payload non-secret. The first write route changes the
threat model, and §D5 named the two conditions it must satisfy:

* it must gate on an **authenticated operator identity**, and
* it must be **disabled when the dashboard binds beyond loopback**.

They are deliberately independent, and the order they are reported in matters.
A valid credential does not open the gate on a dashboard bound to ``0.0.0.0``:
the credential says *who is asking*, the bind says *who can ask*, and the second
is the one an operator has to fix first. So :func:`write_gate` reports the bind
before it reports a missing credential.

The credential is **env-only** (:data:`OPERATOR_TOKEN_ENV`), never a config
field and never persisted — the same shape as the gateway control token, and for
the same reason: a settings screen that could show it is a settings screen that
could leak it. The *actor* recorded on an audit record comes from this boundary
(:data:`OPERATOR_ID_ENV`), never from a request body, so provenance cannot be
claimed by the caller. Nothing here derives the actor from the credential: a
truncated digest of a token is a stable credential fingerprint, which ADR-0138
§D1 forbids exactly as firmly as the credential itself.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

OPERATOR_TOKEN_ENV = "HYDRAFLOW_OPERATOR_TOKEN"
"""Env-only operator credential. Deliberately not a config field (see module doc)."""

OPERATOR_TOKEN_PREFIX = "hfop_"
"""The RECOMMENDED grammar: ``hfop_`` + ``secrets.token_urlsafe(32)``.

There is no minter, exactly as there is none for the gateway control token —
any value long enough to resist guessing authenticates. The prefix is a
convention with one job: it makes a leaked token detectable **on its own**, with
no surrounding variable name, by ``secret_scrub``'s canonical pattern set. A
token minted any other way is still accepted here, and is still caught in the
``OPERATOR_TOKEN=...`` assignment form — but a bare bearer value echoed into a
transcript is only redacted if it carries the prefix. Mint one with::

    python -c "import secrets; print('hfop_' + secrets.token_urlsafe(32))"
"""

OPERATOR_ID_ENV = "HYDRAFLOW_OPERATOR_ID"
"""Env-only, non-secret label recorded as the actor on every audited mutation."""

DEFAULT_OPERATOR_ID = "operator"
"""Provenance for a deployment that authenticated an operator but named none."""

_LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})


class WriteGate(StrEnum):
    """Whether the operator write plane is open, and if not, why not."""

    ENABLED = "enabled"
    WORKSPACE_DISABLED = "workspace-disabled"
    DASHBOARD_NOT_LOOPBACK = "dashboard-not-loopback"
    NO_OPERATOR_IDENTITY = "no-operator-identity"


@dataclass(frozen=True, slots=True)
class OperatorIdentity:
    """Who the authenticated boundary says is making a mutation.

    Carries a label and nothing else. There is no token field, no digest, and
    no truncation of one: an identity object that could be logged beside a
    mutation must be safe to log.
    """

    actor: str


def is_loopback(host: str) -> bool:
    """Whether *host* is unreachable from another machine.

    A name is matched against the known loopback names; anything else is parsed
    as an address so the whole ``127.0.0.0/8`` range and ``::1`` are covered
    rather than the one literal an operator happened to type. An unparseable or
    empty host is **not** loopback: failing closed is the point.
    """
    candidate = host.strip().lower()
    if not candidate:
        return False
    if candidate in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(candidate.strip("[]")).is_loopback
    except ValueError:
        return False


def write_gate(config: Any, *, env: Mapping[str, str] | None = None) -> WriteGate:
    """Return whether the policy write plane may serve a request at all.

    Reported reasons are ordered by what an operator must fix first: the kill
    switch they set deliberately, then the bind that makes authentication
    meaningful, then the credential.
    """
    environment = os.environ if env is None else env
    if not getattr(config, "gateway_policy_workspace_enabled", False):
        return WriteGate.WORKSPACE_DISABLED
    if not is_loopback(str(getattr(config, "dashboard_host", "") or "")):
        return WriteGate.DASHBOARD_NOT_LOOPBACK
    if not environment.get(OPERATOR_TOKEN_ENV, "").strip():
        return WriteGate.NO_OPERATOR_IDENTITY
    return WriteGate.ENABLED


def authenticate_operator(
    authorization: str | None, *, env: Mapping[str, str] | None = None
) -> OperatorIdentity | None:
    """Return the operator this ``Authorization`` header proves, or ``None``.

    An unconfigured credential authenticates nobody — never the caller who also
    presented nothing. The comparison is constant-time, because a bearer check
    that leaks its own prefix length is a bearer check an attacker can walk.
    """
    environment = os.environ if env is None else env
    expected = environment.get(OPERATOR_TOKEN_ENV, "").strip()
    if not expected:
        return None
    presented = _bearer_token(authorization)
    # Compared as BYTES, and encoded with ``surrogateescape`` on BOTH sides.
    # ``compare_digest`` on ``str`` requires ASCII and raises ``TypeError``
    # otherwise, so a non-ASCII bearer header would surface as an unhandled 500
    # rather than the 401 it is — a worse answer, and a signal an attacker can
    # probe with. Plain ``encode`` closes only half of it: ``os.environ`` decodes
    # with ``surrogateescape``, so a token whose bytes are not valid UTF-8 yields
    # lone surrogates that ``encode`` refuses on the *expected* side. The
    # error handler is lossless in both directions, so equality is unchanged.
    if presented is None or not secrets.compare_digest(
        presented.encode("utf-8", "surrogateescape"),
        expected.encode("utf-8", "surrogateescape"),
    ):
        return None
    return OperatorIdentity(
        actor=(environment.get(OPERATOR_ID_ENV, "").strip() or DEFAULT_OPERATOR_ID)[:64]
    )


def _bearer_token(authorization: str | None) -> str | None:
    """Extract the bearer value, or ``None`` when the header is not one."""
    if not authorization:
        return None
    scheme, separator, token = authorization.strip().partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    return token.strip() or None
