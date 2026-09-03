"""Scenario: a real factory spawn reaches Anthropic on a Claude subscription.

ADR-0148. The unit tests prove the header builder and the credential source;
this drives the whole path — `run_lightweight_agent` mints a virtual key
through the gateway's real control endpoint, spawns with the gateway as its
base URL, and the gateway swaps the virtual key for the subscription's OAuth
bearer token before reaching the origin.

That swap is the part no unit test can see. `replace_request_headers` can be
perfect while the proxy forgets to resolve a token, or resolves one and sends
the worker's virtual key anyway, and the only place both are visible at once is
what the external boundary actually received.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hydraflow_gateway.subscription_credential import OAUTH_BETA_FLAG
from tests.helpers import ConfigFactory
from tests.scenarios.helpers.gateway_turn import (
    gateway_ledger_path,
    run_gateway_turn,
)

pytestmark = [pytest.mark.scenario, pytest.mark.asyncio]

_CONTROL_TOKEN = "s" * 40
_PROVIDER_KEY = "scenario-provider-key"
_VIRTUAL_SECRET = "scenario-virtual-secret"


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.delenv("HYDRAFLOW_DATA_ROOT", raising=False)
    monkeypatch.delenv("HYDRAFLOW_HOME", raising=False)
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", _CONTROL_TOKEN)
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        repo="acme/hydraflow",
        pin_role_dials=False,
    )


async def _turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    return await run_gateway_turn(
        config=_config(tmp_path, monkeypatch),
        control_token=_CONTROL_TOKEN,
        provider_key=_PROVIDER_KEY,
        virtual_secret=_VIRTUAL_SECRET,
        subscription_upstream=True,
    )


class TestASpawnOnTheSubscriptionLane:
    async def test_the_spawn_completes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anti-vacuity floor: the assertions below need a turn to have run."""
        turn = await _turn(tmp_path, monkeypatch)

        assert turn.returncode == 0
        assert turn.exchanges, "the origin was never reached"

    async def test_the_origin_receives_the_subscription_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        turn = await _turn(tmp_path, monkeypatch)

        assert turn.headers[0]["authorization"] == f"Bearer {_PROVIDER_KEY}-oauth"

    async def test_the_origin_receives_the_oauth_beta_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without it Anthropic refuses an OAuth token outright."""
        turn = await _turn(tmp_path, monkeypatch)

        assert OAUTH_BETA_FLAG in turn.headers[0].get("anthropic-beta", "")

    async def test_the_workers_virtual_key_never_reaches_the_origin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The swap, from the outside: one credential in, a different one out."""
        turn = await _turn(tmp_path, monkeypatch)
        sent = turn.headers[0]

        assert "x-api-key" not in sent
        assert _VIRTUAL_SECRET not in sent.get("authorization", "")

    async def test_the_ledger_row_is_flat_rate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A subscription request is priced but not owed; the row says so."""
        config = _config(tmp_path, monkeypatch)
        await run_gateway_turn(
            config=config,
            control_token=_CONTROL_TOKEN,
            provider_key=_PROVIDER_KEY,
            virtual_secret=_VIRTUAL_SECRET,
            subscription_upstream=True,
        )

        rows = [
            json.loads(line)
            for line in gateway_ledger_path(config).read_text().splitlines()
            if line.strip()
        ]
        assert rows, "the gateway wrote no observation"
        assert {row["billing_kind"] for row in rows} == {"flat_rate"}

    async def test_a_metered_turn_is_still_metered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Decoy: the lane follows the upstream, not the scenario harness.

        Without this, hardcoding `flat_rate` on every row would satisfy the
        assertion above and silently misreport every metered deployment.
        """
        config = _config(tmp_path, monkeypatch)
        await run_gateway_turn(
            config=config,
            control_token=_CONTROL_TOKEN,
            provider_key=_PROVIDER_KEY,
            virtual_secret=_VIRTUAL_SECRET,
        )

        rows = [
            json.loads(line)
            for line in gateway_ledger_path(config).read_text().splitlines()
            if line.strip()
        ]
        assert {row["billing_kind"] for row in rows} == {"metered"}

    async def test_a_metered_turn_sends_the_api_key_not_a_bearer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half of the decoy: the static lane is untouched."""
        turn = await run_gateway_turn(
            config=_config(tmp_path, monkeypatch),
            control_token=_CONTROL_TOKEN,
            provider_key=_PROVIDER_KEY,
            virtual_secret=_VIRTUAL_SECRET,
        )
        sent = turn.headers[0]

        assert sent["x-api-key"] == _PROVIDER_KEY
        assert OAUTH_BETA_FLAG not in sent.get("anthropic-beta", "")
