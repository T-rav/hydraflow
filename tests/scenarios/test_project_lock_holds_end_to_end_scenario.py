"""MockWorld scenario (#11993, Gateway P6d): the lock holds through a real spawn.

The unit proof beside this (`tests/test_issue_11993_project_lock_holds.py`)
resolves contexts directly. It cannot see the thing that actually breaks: an
operator writes a lock through the HTTP write plane and a *real* spawn then
resolves somewhere else, because the spawn path and the resolver disagree about
what repository it is in.

Everything on the path here is real — the dashboard policy routes, the operator
write gate, the atomic snapshot replace, the shadow resolver, the gateway
control plane, the mint, the streaming proxy and the ledger. Only the Claude
subprocess and the external origin are deterministic fakes.

The retry clause is discharged by running the turn twice against one written
revision: a retry re-enters the spawn path, so a second turn IS the retry, and
both decisions must name the same lane. The control at the bottom removes the
policy and shows the identical spawn reaching Anthropic — without it, "always
z.ai" could be true of a spawn that had nowhere else to go.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_routes._gateway_policy_routes import build_gateway_policy_router
from hydraflow_gateway.routing_audit import RoutingAuditLog
from operator_identity import OPERATOR_ID_ENV, OPERATOR_TOKEN_ENV
from route_shadow import shadow_decision_log_path
from tests.helpers import ConfigFactory
from tests.scenarios.helpers.gateway_turn import TURN_MODEL, run_gateway_turn

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.scenario

_CONTROL_TOKEN = "p6d-scenario-control-token-0123456789abcd"
_PROVIDER_KEY = "p6d-scenario-real-provider-key"
_VIRTUAL_SECRET = "p6d-scenario-virtual-secret"
_OPERATOR_TOKEN = "hfop_" + "p" * 40
_REPO = "acme/project-x"
_NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=UTC)
_AUTH = {"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
_ENV = {OPERATOR_TOKEN_ENV: _OPERATOR_TOKEN, OPERATOR_ID_ENV: "travis"}

#: "Project X always uses z.ai", in the form an operator actually writes it.
#: The lock alone may not move an Anthropic request off its lane (ADR-0139 D4),
#: so the mapping says out loud which model answers this spawn's request.
_ZAI_LOCK = {
    "id": "project-x-zai",
    "priority": 100,
    "match": {"repo_ids": [_REPO]},
    "action": {
        "provider_lock": "zai-harness",
        "requirement_map": [
            {
                "requirement": {"kind": "concrete_model", "value": TURN_MODEL},
                "effective_model": "glm-5.3",
            }
        ],
    },
}


@dataclass(slots=True)
class _Operator:
    client: TestClient
    config: Any

    def write_lock(self) -> Any:
        return self.client.post(
            "/api/gateway/policies/mutations",
            json={"kind": "create", "expected_revision": 0, "policy": _ZAI_LOCK},
            headers=_AUTH,
        )


def _operator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Operator:
    monkeypatch.delenv("HYDRAFLOW_DATA_ROOT", raising=False)
    monkeypatch.delenv("HYDRAFLOW_HOME", raising=False)
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", _CONTROL_TOKEN)
    monkeypatch.setenv("ZAI_API_KEY", "p6d-scenario-zai-key")

    config = ConfigFactory.create(repo_root=tmp_path / "repo", repo=_REPO)
    config.gateway_route_shadow_enabled = True
    app = FastAPI()
    app.include_router(
        build_gateway_policy_router(config, env=_ENV, clock=lambda: _NOW)
    )
    return _Operator(client=TestClient(app), config=config)


async def _turn(config: Any, *, key_id: str = "p6d-scenario-key") -> Any:
    # `zai_upstream=True`: a lock can only select an account that EXISTS. With
    # no z.ai upstream configured the resolver answers `no-eligible-account`,
    # which is correct behaviour and proves nothing about the lock — the
    # deployment simply had one lane.
    return await run_gateway_turn(
        config=config,
        control_token=_CONTROL_TOKEN,
        provider_key=_PROVIDER_KEY,
        virtual_secret=_VIRTUAL_SECRET,
        key_id=key_id,
        zai_upstream=True,
    )


def _decisions(config: Any) -> list[dict[str, Any]]:
    path = shadow_decision_log_path(config)
    if not path.exists():
        return []
    return [record.payload for record in RoutingAuditLog(path).read_all()]


def _proposed_bindings(config: Any) -> list[str | None]:
    return [d["proposed"].get("provider_binding") for d in _decisions(config)]


class TestTheLockHoldsThroughARealSpawn:
    async def test_a_spawn_under_the_lock_resolves_to_zai(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The epic's sentence, at the external boundary."""
        operator = _operator(tmp_path, monkeypatch)
        assert operator.write_lock().status_code == 200

        await _turn(operator.config)

        assert _proposed_bindings(operator.config) == ["zai-harness"]

    async def test_the_spawn_cites_the_lock_rather_than_landing_there_by_luck(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anti-vacuity: assert the REASON, not the provider string.

        A decision that reached z.ai for any other reason — a default, a
        fallback, an unmapped request resolving to itself — would satisfy the
        assertion above and mean the lock was never consulted.
        """
        operator = _operator(tmp_path, monkeypatch)
        operator.write_lock()

        await _turn(operator.config)

        proposed = _decisions(operator.config)[0]["proposed"]
        assert proposed["policy_id"] == "project-x-zai"
        assert proposed["reason"] == "matched-policy"

    async def test_a_retry_stays_on_zai(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A retry re-enters the spawn path, so a second turn IS the retry.

        Asserted over every attempt rather than the last: a lock that held on
        the first call and drifted on the second is the failure this clause
        exists for, and it would leave the final decision looking correct.
        """
        operator = _operator(tmp_path, monkeypatch)
        operator.write_lock()

        await _turn(operator.config, key_id="p6d-attempt-1")
        await _turn(operator.config, key_id="p6d-attempt-2")

        bindings = _proposed_bindings(operator.config)
        assert len(bindings) == 2, "the second attempt recorded no decision"
        assert set(bindings) == {"zai-harness"}


class TestTheLockIsWhatDoesTheWork:
    """The control. Without it the suite above proves nothing."""

    async def test_without_the_lock_the_same_spawn_reaches_anthropic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Identical spawn, no policy written — it must resolve to the other lane.

        If this spawn could never have reached Anthropic, "always z.ai" would be
        a statement about the fixture rather than about the lock.
        """
        operator = _operator(tmp_path, monkeypatch)

        await _turn(operator.config)

        assert "zai-harness" not in _proposed_bindings(operator.config)
