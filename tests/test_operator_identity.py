"""The operator write boundary ADR-0138 §D5 made a precondition on this phase.

Two independent conditions gate every routing-policy write, and the test that
matters most is the one proving they are *independent*: a perfectly valid
operator credential must not open the gate on a dashboard bound beyond loopback,
because the credential proves who is asking and the bind proves who can ask.
"""

from __future__ import annotations

import pytest

from operator_identity import (
    DEFAULT_OPERATOR_ID,
    OPERATOR_ID_ENV,
    OPERATOR_TOKEN_ENV,
    WriteGate,
    authenticate_operator,
    is_loopback,
    write_gate,
)
from tests.helpers import ConfigFactory

_TOKEN = "hfop_" + "t" * 40


def _config(*, host: str = "127.0.0.1", enabled: bool = True):
    config = ConfigFactory.create(dashboard_host=host)
    object.__setattr__(config, "gateway_policy_workspace_enabled", enabled)
    return config


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        pytest.param("127.0.0.1", True, id="ipv4-loopback"),
        pytest.param("localhost", True, id="localhost-name"),
        pytest.param("::1", True, id="ipv6-loopback"),
        pytest.param("127.5.5.5", True, id="ipv4-loopback-range"),
        pytest.param("0.0.0.0", False, id="all-interfaces"),  # noqa: S104
        pytest.param("192.168.1.10", False, id="lan-address"),
        pytest.param("", False, id="unset-host"),
        pytest.param("dashboard.example.com", False, id="public-name"),
    ],
)
def test_loopback_classification(host: str, loopback: bool) -> None:
    """Only an address that cannot be reached from another machine is loopback."""
    assert is_loopback(host) is loopback


def test_a_loopback_bind_with_an_operator_token_opens_the_write_gate() -> None:
    """The one combination D5 permits, so the closed cases are not vacuous."""
    gate = write_gate(_config(), env={OPERATOR_TOKEN_ENV: _TOKEN})

    assert gate is WriteGate.ENABLED


@pytest.mark.parametrize(
    ("config_kwargs", "env", "expected"),
    [
        pytest.param(
            {"host": "0.0.0.0"},  # noqa: S104
            {OPERATOR_TOKEN_ENV: _TOKEN},
            WriteGate.DASHBOARD_NOT_LOOPBACK,
            id="a-valid-token-cannot-open-a-gate-bound-beyond-loopback",
        ),
        pytest.param(
            {},
            {},
            WriteGate.NO_OPERATOR_IDENTITY,
            id="loopback-alone-is-not-an-operator-identity",
        ),
        pytest.param(
            {},
            {OPERATOR_TOKEN_ENV: "   "},
            WriteGate.NO_OPERATOR_IDENTITY,
            id="a-blank-token-is-not-a-credential",
        ),
        pytest.param(
            {"enabled": False},
            {OPERATOR_TOKEN_ENV: _TOKEN},
            WriteGate.WORKSPACE_DISABLED,
            id="the-kill-switch-closes-the-gate-first",
        ),
    ],
)
def test_the_write_gate_is_closed(
    config_kwargs: dict[str, object], env: dict[str, str], expected: WriteGate
) -> None:
    """Every closed disposition names its own reason rather than one blanket no."""
    assert write_gate(_config(**config_kwargs), env=env) is expected


def test_a_non_loopback_bind_outranks_a_missing_token() -> None:
    """The reported reason is the one an operator must fix first (D5's hard rule)."""
    gate = write_gate(_config(host="10.0.0.4"), env={})

    assert gate is WriteGate.DASHBOARD_NOT_LOOPBACK


@pytest.mark.parametrize(
    ("presented", "authenticated"),
    [
        pytest.param(f"Bearer {_TOKEN}", True, id="the-configured-bearer-token"),
        pytest.param(f"bearer {_TOKEN}", True, id="a-lowercase-scheme"),
        pytest.param(f"Bearer {_TOKEN}x", False, id="a-token-with-one-extra-byte"),
        pytest.param("Bearer ", False, id="an-empty-bearer-value"),
        pytest.param(_TOKEN, False, id="a-bare-token-without-the-scheme"),
        pytest.param(f"Basic {_TOKEN}", False, id="the-wrong-scheme"),
        pytest.param(None, False, id="no-authorization-header-at-all"),
    ],
)
def test_operator_authentication(presented: str | None, authenticated: bool) -> None:
    """Only an exact bearer match against the env credential authenticates."""
    identity = authenticate_operator(presented, env={OPERATOR_TOKEN_ENV: _TOKEN})

    assert (identity is not None) is authenticated


def test_an_unconfigured_credential_authenticates_nobody() -> None:
    """An absent token must never be matched by an absent header."""
    assert authenticate_operator("Bearer ", env={}) is None


def test_the_actor_is_named_by_the_boundary_not_the_caller() -> None:
    """Audit provenance comes from the authenticated environment, never a body."""
    identity = authenticate_operator(
        f"Bearer {_TOKEN}",
        env={OPERATOR_TOKEN_ENV: _TOKEN, OPERATOR_ID_ENV: "travis"},
    )

    assert identity is not None and identity.actor == "travis"


def test_an_unnamed_operator_falls_back_to_a_generic_actor() -> None:
    """A deployment that names no operator still records a non-empty provenance."""
    identity = authenticate_operator(
        f"Bearer {_TOKEN}", env={OPERATOR_TOKEN_ENV: _TOKEN}
    )

    assert identity is not None and identity.actor == DEFAULT_OPERATOR_ID


def test_the_identity_carries_no_credential_material() -> None:
    """An actor label that embedded the token would be a credential fingerprint."""
    identity = authenticate_operator(
        f"Bearer {_TOKEN}", env={OPERATOR_TOKEN_ENV: _TOKEN}
    )

    assert identity is not None and _TOKEN not in repr(identity)
