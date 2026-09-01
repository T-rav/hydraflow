"""#11992 (P6c): the governance gauge is reachable and reads the durable ledger.

The engine is tested in ``test_gateway_governance_gauge.py``. This is the half
a correct engine does not give you: that something serves it, that it sits
behind the same control boundary as the other v2 reads, and that it reads the
ledger on disk rather than the in-flight ring — a ring evicts, and a gauge that
went green because the evidence aged out is worse than no gauge.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import SecretStr

from hydraflow_gateway.app import create_app
from hydraflow_gateway.ledger import GatewayLedgerRow
from hydraflow_gateway.models import (
    Principal,
    PrincipalKind,
    ProviderBinding,
    RepoClass,
)
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)

_CONTROL_TOKEN = "test-control-token-0123456789abcdef"
_AUTH = {"Authorization": f"Bearer {_CONTROL_TOKEN}"}
_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_GOVERNED = "acme/hydraflow"


class _EmptyStream(httpx.AsyncByteStream):
    async def __aiter__(self):  # noqa: ANN204
        return
        yield b""


def _settings(tmp_path: Path, *, governed: frozenset[str]) -> GatewaySettings:
    return GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            ProviderBinding.ANTHROPIC: UpstreamSettings(
                base_url="https://upstream.test/prefix",
                api_key=SecretStr("real-anthropic-key"),
                auth_style=UpstreamAuthStyle.X_API_KEY,
            )
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
        governed_repo_slugs=governed,
    )


def _row(*, request_id: str, route_decision_id: str | None) -> GatewayLedgerRow:
    return GatewayLedgerRow(
        request_id=request_id,
        key_id="key-1",
        principal=Principal(
            kind=PrincipalKind.SPAWN, id="implementer", spawn_id="child-1"
        ),
        repo_slug=_GOVERNED,
        repo_class=RepoClass.HYDRAFLOW,
        body_capture_policy="metadata-only",
        timestamp=_NOW,
        latency_ms=1.0,
        status_code=200,
        status="completed",
        upstream_provider=ProviderBinding.ANTHROPIC,
        model_requested="m",
        model_served="m",
        input_tokens=1,
        output_tokens=1,
        completed=True,
        client_aborted=False,
        usage_complete=True,
        cost_usd=0.0,
        cost_unknown=False,
        route_decision_id=route_decision_id,
    )


def _write_ledger(tmp_path: Path, rows: list[GatewayLedgerRow]) -> None:
    path = tmp_path / "gateway.jsonl"
    path.write_text(
        "".join(json.dumps(row.to_json_dict()) + "\n" for row in rows),
        encoding="utf-8",
    )


def _client(tmp_path: Path, *, governed: frozenset[str]) -> httpx.AsyncClient:
    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_EmptyStream())

    app = create_app(
        _settings(tmp_path, governed=governed),
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        wall_clock=_NOW.timestamp,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    )


async def test_the_gauge_sits_behind_the_control_boundary(tmp_path: Path) -> None:
    async with _client(tmp_path, governed=frozenset({_GOVERNED})) as client:
        response = await client.get("/control/v2/routes/governance")

    assert response.status_code == 401


async def test_a_routed_spawn_reads_clean(tmp_path: Path) -> None:
    _write_ledger(tmp_path, [_row(request_id="r1", route_decision_id="rd-1")])

    async with _client(tmp_path, governed=frozenset({_GOVERNED})) as client:
        body = (await client.get("/control/v2/routes/governance", headers=_AUTH)).json()

    assert (body["governed"], body["ungoverned"]) == (1, 0)


async def test_a_bypass_is_served_with_the_offending_request_named(
    tmp_path: Path,
) -> None:
    _write_ledger(
        tmp_path,
        [
            _row(request_id="r1", route_decision_id="rd-1"),
            _row(request_id="r2", route_decision_id=None),
        ],
    )

    async with _client(tmp_path, governed=frozenset({_GOVERNED})) as client:
        body = (await client.get("/control/v2/routes/governance", headers=_AUTH)).json()

    assert body["ungoverned"] == 1
    assert [o["request_id"] for o in body["offenders"]] == ["r2"]


async def test_the_gauge_reads_the_ledger_on_disk_not_the_in_flight_ring(
    tmp_path: Path,
) -> None:
    """Nothing was ever tracked in-process; the evidence is the ledger file."""
    _write_ledger(tmp_path, [_row(request_id="r1", route_decision_id=None)])

    async with _client(tmp_path, governed=frozenset({_GOVERNED})) as client:
        body = (await client.get("/control/v2/routes/governance", headers=_AUTH)).json()

    assert body["examined"] == 1
    assert body["ungoverned"] == 1


async def test_an_ungoverned_deployment_reports_zero_governed_not_clean(
    tmp_path: Path,
) -> None:
    """No governed repo configured: the denominator, not the numerator, is why."""
    _write_ledger(tmp_path, [_row(request_id="r1", route_decision_id=None)])

    async with _client(tmp_path, governed=frozenset()) as client:
        body = (await client.get("/control/v2/routes/governance", headers=_AUTH)).json()

    assert (body["examined"], body["governed"], body["ungoverned"]) == (1, 0, 0)
