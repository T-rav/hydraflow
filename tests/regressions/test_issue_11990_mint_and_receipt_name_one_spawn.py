"""#11990: the mint must use the child id it is given, not invent its own.

``ImplementWorkerRunner._run_child`` generated a ``child_spawn_id``, stamped it
onto the receipt's :class:`driver_contracts.WorkerLineage`, and then spawned
without passing it down. :func:`runner_utils.resolve_harness_env` fell through
to ``spawn_id or uuid.uuid4().hex`` and minted the virtual key under an id that
existed nowhere else, so a receipt and the ledger rows it accounted for could
not be joined. Nothing named the driver at all.

Pinned at the mint rather than at the runner because that is where the id was
lost: a caller that passes an id must get that id on the wire. The regression
was silent — both halves were internally consistent and every test passed —
so only a check that compares the id in against the id out can see it.
"""

from __future__ import annotations

import pytest

from config import HydraFlowConfig
from gateway_mint_client import GatewayMintCredential, GatewayMintRequest
import runner_utils
from runner_utils import resolve_harness_env, revoke_gateway_key


class _RecordingGatewayClient:
    """Records the mint request instead of reaching a gateway."""

    def __init__(self) -> None:
        self.requests: list[GatewayMintRequest] = []

    async def mint_key(
        self, *, base_url: str, control_token: str, request: GatewayMintRequest
    ) -> GatewayMintCredential:
        self.requests.append(request)
        return GatewayMintCredential(
            key_id="key-1",
            token="hfgw_virtual-1",
            expires_at="2099-08-19T12:05:00Z",
        )

    async def revoke_key(
        self, *, base_url: str, control_token: str, key_id: str
    ) -> bool:
        return True


@pytest.mark.asyncio
class TestTheMintHonoursTheChildIdItIsGiven:
    async def _mint(
        self, monkeypatch: pytest.MonkeyPatch, **kwargs: object
    ) -> GatewayMintRequest:
        monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "control-secret")
        config = HydraFlowConfig(
            gateway_base_url="http://gateway:8080", gateway_key_ttl_seconds=300
        )
        client = _RecordingGatewayClient()

        env = await resolve_harness_env(
            "gateway",
            config,
            model="sonnet",
            gateway_client=client,  # type: ignore[arg-type]
            **kwargs,  # type: ignore[arg-type]
        )
        await revoke_gateway_key(env)
        return client.requests[0]

    async def test_a_supplied_child_id_reaches_the_wire_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        request = await self._mint(monkeypatch, spawn_id="child-abc")

        assert request.spawn_id == "child-abc"

    async def test_the_driver_that_asked_is_recorded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        request = await self._mint(
            monkeypatch, spawn_id="child-abc", driver_id="drv-7"
        )

        assert request.driver_id == "drv-7"
        assert request.wire_payload()["driver_id"] == "drv-7"

    async def test_a_classic_spawn_states_no_driver_rather_than_an_empty_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """"No parent" and "parent unknown" must not collapse to one value."""
        request = await self._mint(monkeypatch, spawn_id="child-abc")

        assert request.driver_id is None
        assert "driver_id" not in request.wire_payload()


@pytest.mark.asyncio
class TestTheLightweightSpawnForwardsLineageToTheMint:
    """The link that was actually missing.

    :func:`resolve_harness_env` always honoured a ``spawn_id`` it was given —
    the defect was that nothing on the brokered child's path ever gave it one.
    Pinning the mint alone would therefore pin a property that never broke, so
    this asserts the hand-off itself: what a caller passes to
    ``run_lightweight_agent`` reaches the mint.
    """

    async def test_spawn_id_and_driver_id_reach_resolve_harness_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, object] = {}

        async def _record(*args: object, **kwargs: object) -> dict[str, str]:
            seen.update(kwargs)
            return {}

        monkeypatch.setattr(runner_utils, "resolve_harness_env", _record)

        await runner_utils.run_lightweight_agent(
            runner=_StubRunner(),  # type: ignore[arg-type]
            config=HydraFlowConfig(),
            tool="claude",
            model="sonnet",
            prompt="do the thing",
            source="implementer",
            timeout=5.0,
            spawn_id="child-abc",
            driver_id="drv-7",
        )

        assert seen, "resolve_harness_env was never reached"
        assert seen["spawn_id"] == "child-abc"
        assert seen["driver_id"] == "drv-7"


class _StubRunner:
    """Returns a trivial success without starting a process."""

    async def run_simple(self, *args: object, **kwargs: object) -> object:
        from models import SimpleResult

        return SimpleResult(stdout="ok", returncode=0)
