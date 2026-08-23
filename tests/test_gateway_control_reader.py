"""``gateway_control_reader`` — the dashboard's gateway control client (ADR-0138).

Unit-level: the reader's own contract — source-state honesty, payload validation,
and the canonical role join — plus the module's one mutation seam (ADR-0142),
without a FastAPI route in the way. The route-level envelope and the operator
write gate are covered by ``tests/test_dashboard_gateway_routes.py``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from gateway_control_reader import (
    GATEWAY_CONTROL_TOKEN_ENV,
    GatewayControlReader,
    GatewayControlWriter,
    GatewayReadResult,
    GatewaySourceState,
    GatewayWriteState,
    annotate_active_routes,
    annotate_recent_routes,
    canonical_worker_role,
    reader_from_config,
    writer_from_config,
)
from hydraflow_gateway.accounts import AdministrativeState
from hydraflow_gateway.active_routes import ActiveRouteRegistry
from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.models import MintKeyRequest, ProviderBinding, RepoClass
from hydraflow_gateway.routing_account_admin import AdminRejection
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from tests.helpers import ConfigFactory

_CONTROL_TOKEN = "test-control-token-0123456789abcdef"
_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)


class _EmptyStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        return
        yield b""

    async def aclose(self) -> None:
        return None


def _gateway(tmp_path: Path) -> object:
    settings = GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            ProviderBinding.ANTHROPIC: UpstreamSettings(
                base_url="https://upstream.test",
                api_key=SecretStr("real-anthropic-key"),
                auth_style=UpstreamAuthStyle.X_API_KEY,
            )
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
    )
    store = VirtualKeyStore(max_ttl_seconds=600, id_factory=lambda: "key-1")
    store.mint(
        MintKeyRequest(
            principal_kind="spawn",
            principal_id="implementer",
            spawn_id="spawn-1",
            session_id="session-1",
            repo_slug="acme/hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ANTHROPIC,
            capture_bodies=False,
            ttl_seconds=300,
        )
    )

    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_EmptyStream())

    return create_app(
        settings,
        key_store=store,
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        active_routes=ActiveRouteRegistry(started_at=_NOW),
        wall_clock=_NOW.timestamp,
    )


def _reader(
    tmp_path: Path,
    *,
    base_url: str = "http://gateway.test",
    control_token: str = _CONTROL_TOKEN,
    handler: object | None = None,
) -> GatewayControlReader:
    app = _gateway(tmp_path)

    def client_factory() -> httpx.AsyncClient:
        if handler is not None:
            return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app))  # type: ignore[arg-type]

    return GatewayControlReader(
        base_url=base_url,
        control_token=control_token,
        client_factory=client_factory,
    )


async def test_a_successful_read_is_reported_as_available(tmp_path: Path) -> None:
    """The happy path is an explicit state, not merely the absence of an error."""
    result = await _reader(tmp_path).accounts()

    assert result.state is GatewaySourceState.AVAILABLE


async def test_an_available_read_carries_the_gateway_payload(tmp_path: Path) -> None:
    """Validation must pass the gateway's model through, not a reshaped copy."""
    result = await _reader(tmp_path).accounts()

    assert len(result.data["accounts"]) == 2  # type: ignore[index]


async def test_a_missing_control_token_is_not_configured(tmp_path: Path) -> None:
    """Without the env-only credential the source is unconfigured, not empty."""
    result = await _reader(tmp_path, control_token="").accounts()

    assert result.state is GatewaySourceState.NOT_CONFIGURED


async def test_a_missing_base_url_is_not_configured(tmp_path: Path) -> None:
    """A gateway that was never deployed is not a gateway that is down."""
    result = await _reader(tmp_path, base_url="").accounts()

    assert result.state is GatewaySourceState.NOT_CONFIGURED


async def test_an_unconfigured_read_returns_no_fabricated_data(
    tmp_path: Path,
) -> None:
    """An unavailable source must never present an invented payload."""
    result = await _reader(tmp_path, control_token="").accounts()

    assert result.data is None


async def test_a_transport_failure_is_unreachable(tmp_path: Path) -> None:
    """A gateway that cannot be reached is distinguishable from a quiet one."""

    async def dead(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("gateway down")

    result = await _reader(tmp_path, handler=dead).accounts()

    assert result.state is GatewaySourceState.UNREACHABLE


async def test_an_unrecognised_payload_fails_closed_as_invalid(
    tmp_path: Path,
) -> None:
    """Schema drift must not reach the browser unchecked."""

    async def drifted(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"accounts": "not-a-list"})

    result = await _reader(tmp_path, handler=drifted).accounts()

    assert result.state is GatewaySourceState.INVALID


async def test_a_non_2xx_control_response_is_unreachable(tmp_path: Path) -> None:
    """A rejected control read is a source failure, not an empty view."""

    async def refused(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid control credential"})

    result = await _reader(tmp_path, handler=refused).accounts()

    assert result.state is GatewaySourceState.UNREACHABLE


async def test_the_requested_window_reaches_the_gateway(tmp_path: Path) -> None:
    """The operator's window is forwarded, not silently defaulted."""
    result = await _reader(tmp_path).accounts(window_seconds=600)

    assert result.data["window_seconds"] == 600  # type: ignore[index]


def test_an_unavailable_result_serialises_a_null_payload() -> None:
    """The dashboard envelope always states whether the source was real."""
    envelope = GatewayReadResult(GatewaySourceState.UNREACHABLE).to_json_dict()

    assert envelope == {
        "available": False,
        "source_state": "unreachable",
        "data": None,
    }


def test_reader_from_config_reads_the_env_only_control_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The credential is env-only by design; the reader must not invent a source."""
    monkeypatch.delenv(GATEWAY_CONTROL_TOKEN_ENV, raising=False)

    reader = reader_from_config(ConfigFactory.create())

    assert reader._control_token == ""  # noqa: SLF001 — the seam under test


@pytest.mark.parametrize(
    ("principal_id", "expected"),
    [
        ("implementer", "implementer"),
        ("REVIEWER", "reviewer"),
        (" planner ", "planner"),
        ("issue_controller", None),
        ("", None),
    ],
)
def test_canonical_worker_role_matches_exactly(
    principal_id: str, expected: str | None
) -> None:
    """The role join is an exact ADR-0137 catalog match, never a heuristic."""
    assert canonical_worker_role(principal_id) == expected


def test_active_route_annotation_covers_both_sections() -> None:
    """Leases and in-flight rows both need the canonical role for #11536."""
    payload = annotate_active_routes(
        {
            "leases": [{"principal_id": "reviewer"}],
            "in_flight": [{"principal_id": "adr_review"}],
        }
    )

    assert [row["worker_role"] for row in payload["leases"] + payload["in_flight"]] == [
        "reviewer",
        None,
    ]


def test_recent_route_annotation_leaves_the_payload_otherwise_intact() -> None:
    """Annotation is additive; it must not drop a field the gateway published."""
    payload = annotate_recent_routes(
        {
            "truncated": True,
            "routes": [{"principal_id": "planner", "status": "completed"}],
        }
    )

    assert payload["routes"][0]["status"] == "completed"


# --------------------------------------------------------------------------
# The one mutation seam (ADR-0142, #11540)
# --------------------------------------------------------------------------


def _writer(handler: object, *, control_token: str = _CONTROL_TOKEN) -> object:
    def client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]

    return GatewayControlWriter(
        base_url="http://gateway.test",
        control_token=control_token,
        client_factory=client_factory,
    )


async def _set_state(writer: object) -> object:
    return await writer.set_account_state(  # type: ignore[attr-defined]
        "legacy-anthropic",
        administrative_state=AdministrativeState.DRAINING,
        expected_revision=0,
        actor="travis",
    )


async def test_a_committed_mutation_is_reported_as_applied() -> None:
    """The happy path is an explicit state, not merely the absence of an error."""

    async def committed(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "account_id": "legacy-anthropic",
                "administrative_state": "draining",
                "revision": 1,
            },
        )

    result = await _set_state(_writer(committed))

    assert result.state is GatewayWriteState.APPLIED  # type: ignore[attr-defined]


async def test_the_writer_sends_the_actor_it_was_given_and_no_other() -> None:
    """Provenance travels as an argument, so no body can substitute its own."""
    seen: list[dict[str, object]] = []

    async def capture(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "account_id": "legacy-anthropic",
                "administrative_state": "draining",
                "revision": 1,
            },
        )

    await _set_state(_writer(capture))

    assert seen[0]["actor"] == "travis"


async def test_an_unconfigured_writer_never_attempts_a_mutation() -> None:
    """No control token is "not configured", and emphatically not a silent no-op."""

    async def unreachable(_: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("an unconfigured writer must not open a request")

    result = await _set_state(_writer(unreachable, control_token=""))

    assert result.state is GatewayWriteState.NOT_CONFIGURED  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("status", "detail", "state", "rejection"),
    [
        pytest.param(
            409,
            "stale-revision",
            GatewayWriteState.REFUSED,
            AdminRejection.STALE_REVISION,
            id="a-lost-update-keeps-the-gateways-409",
        ),
        pytest.param(
            404,
            "unknown-account",
            GatewayWriteState.REFUSED,
            AdminRejection.UNKNOWN_ACCOUNT,
            id="a-phantom-account-keeps-the-gateways-404",
        ),
        pytest.param(
            503,
            "audit-chain-broken",
            GatewayWriteState.REFUSED,
            AdminRejection.AUDIT_CHAIN_BROKEN,
            id="an-unverifiable-chain-keeps-the-gateways-503",
        ),
        pytest.param(
            409,
            "some-future-code",
            GatewayWriteState.REFUSED,
            None,
            id="an-unrecognised-refusal-code-is-reported-never-echoed",
        ),
        pytest.param(
            401,
            "invalid control credential",
            GatewayWriteState.UNREACHABLE,
            None,
            id="this-proxys-own-credential-failure-is-not-the-operators",
        ),
        pytest.param(
            413,
            "body too large",
            GatewayWriteState.UNREACHABLE,
            None,
            id="this-proxys-own-bound-failure-is-not-the-operators",
        ),
    ],
)
async def test_a_gateway_refusal_is_mapped_rather_than_relayed(
    status: int,
    detail: str,
    state: GatewayWriteState,
    rejection: AdminRejection | None,
) -> None:
    """Only the three statuses that describe the OPERATOR's request pass through."""

    async def refused(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": detail})

    result = await _set_state(_writer(refused))

    assert (result.state, result.rejection) == (state, rejection)  # type: ignore[attr-defined]


async def test_a_transport_failure_on_a_write_is_unreachable_not_refused() -> None:
    """Nobody knows whether it committed, so it is never reported as a refusal."""

    async def dead(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("gateway down")

    result = await _set_state(_writer(dead))

    assert result.state is GatewayWriteState.UNREACHABLE  # type: ignore[attr-defined]


async def test_a_drifted_success_payload_fails_closed_as_invalid() -> None:
    """A mutation this dashboard could not verify is never reported as applied."""

    async def drifted(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"account_id": "legacy-anthropic"})

    result = await _set_state(_writer(drifted))

    assert result.state is GatewayWriteState.INVALID  # type: ignore[attr-defined]


async def test_a_revocation_reports_the_key_ids_the_gateway_ended() -> None:
    """The blast radius is published, because a count nobody can see is not one."""

    async def revoked(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "account_id": "legacy-anthropic",
                "revoked_key_ids": ["key-1", "key-2"],
                "revision": 3,
            },
        )

    result = await _writer(revoked).revoke_account_leases(  # type: ignore[attr-defined]
        "legacy-anthropic", expected_revision=2, actor="travis"
    )

    assert result.data["revoked_key_ids"] == ["key-1", "key-2"]


def test_writer_from_config_reads_the_same_env_only_control_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One credential for the control plane; the write seam does not get a second."""
    monkeypatch.setenv(GATEWAY_CONTROL_TOKEN_ENV, _CONTROL_TOKEN)

    writer = writer_from_config(ConfigFactory.create())

    assert writer._control_token == _CONTROL_TOKEN  # noqa: SLF001 — the seam under test
