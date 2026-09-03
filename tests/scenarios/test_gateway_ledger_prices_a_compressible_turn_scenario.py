"""Scenario: a real spawn's ledger row is priced even when the client wants gzip.

The layer that would have caught this and did not exist. The usage observer is
fed `aiter_raw()`, so a compressed upstream stream is unparseable and the row
lands with no model, no tokens and no cost — the ledger ADR-0147 routed every
spawn through the gateway to populate, empty for the traffic it measures.

A unit test of the observer proves gzip-in-nothing-out, and a header test proves
the gateway asks for `identity`. Neither can see the two ends joined: that a
REAL spawn, whose HTTP client negotiates compression the way every common client
does, still produces a row with tokens on it. The fake origin honours
`accept-encoding` exactly so this scenario can observe that.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import ConfigFactory
from tests.scenarios.helpers.gateway_turn import (
    gateway_ledger_path,
    run_gateway_turn,
)

pytestmark = [pytest.mark.scenario, pytest.mark.asyncio]

_CONTROL_TOKEN = "z" * 40
_PROVIDER_KEY = "compressible-turn-key"
_VIRTUAL_SECRET = "compressible-turn-secret"


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.delenv("HYDRAFLOW_DATA_ROOT", raising=False)
    monkeypatch.delenv("HYDRAFLOW_HOME", raising=False)
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", _CONTROL_TOKEN)
    return ConfigFactory.create(
        repo_root=tmp_path / "repo", repo="acme/hydraflow", pin_role_dials=False
    )


def _rows(config: Any) -> list[dict[str, Any]]:
    path = gateway_ledger_path(config)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestARealSpawnIsStillPriced:
    async def test_the_upstream_is_asked_for_an_uncompressed_stream(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The mechanism, observed at the external boundary."""
        turn = await run_gateway_turn(
            config=_config(tmp_path, monkeypatch),
            control_token=_CONTROL_TOKEN,
            provider_key=_PROVIDER_KEY,
            virtual_secret=_VIRTUAL_SECRET,
        )

        assert turn.headers, "the origin was never reached"
        assert turn.headers[0].get("accept-encoding") == "identity"

    async def test_the_ledger_row_carries_usage_and_a_price(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The outcome that matters: a row you can bill against.

        Before the fix this row had model_served=None, zero tokens,
        usage_complete=False and cost_unknown=True, while the spawn itself
        succeeded — a green pipeline and a blind ledger.
        """
        config = _config(tmp_path, monkeypatch)
        await run_gateway_turn(
            config=config,
            control_token=_CONTROL_TOKEN,
            provider_key=_PROVIDER_KEY,
            virtual_secret=_VIRTUAL_SECRET,
        )

        rows = _rows(config)
        assert rows, "the gateway wrote no observation"
        row = rows[0]
        assert row["usage_complete"] is True
        assert row["input_tokens"] > 0
        assert row["model_served"]

    async def test_the_spawn_itself_still_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Decoy: pinning identity must not break the turn it observes.

        Without this, a gateway that refused every compressible request would
        satisfy the assertions above by serving nothing at all.
        """
        turn = await run_gateway_turn(
            config=_config(tmp_path, monkeypatch),
            control_token=_CONTROL_TOKEN,
            provider_key=_PROVIDER_KEY,
            virtual_secret=_VIRTUAL_SECRET,
        )

        assert turn.returncode == 0
        assert turn.exchanges, "the upstream was never reached"
