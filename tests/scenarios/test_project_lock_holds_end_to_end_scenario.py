"""MockWorld scenario (#11993, Gateway P6d): the lock holds through a real spawn.

The unit proof beside this (`tests/test_issue_11993_project_lock_holds.py`)
resolves contexts directly. It cannot see the thing that actually breaks: an
operator writes a lock and a *real* spawn then resolves somewhere else, because
the spawn path and the resolver disagree about what repository it is in.

Two things make this scenario worth having next to
`test_gateway_enforcement_canary_scenario.py`, which establishes the
single-turn wire claim:

* the lock arrives through the **operator HTTP write plane** — the dashboard
  route, the write gate, the atomic snapshot replace — rather than being seeded
  straight into the store, so the path an operator actually uses is covered;
* the **retry** clause is discharged as a second real turn, asserted over both
  attempts rather than the last.

Everything on that path is real: the write plane, the enforcement predicate,
the durable store and resolver, the control plane, the route-aware mint, the
strict pre-upstream binding, the streaming proxy and the ledger. Only the
Claude subprocess and the external origin are deterministic fakes, and the
origin records the bytes it was sent — so "the spawn reached z.ai" is a claim
about the wire, not about a log.

That distinction is the whole point. An earlier draft of this file asserted on
the ADR-0139 shadow decision log, which is an inert observer: `route_shadow`
"returns no route to the caller and cannot change one". Every assertion passed
while each spawn was in fact served by `anthropic.test`, and deleting the
enforcement path outright would not have reddened any of them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_routes._gateway_policy_routes import build_gateway_policy_router
from operator_identity import OPERATOR_ID_ENV, OPERATOR_TOKEN_ENV
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
_POLICY_MODEL = "glm-5.3"
_NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=UTC)
_AUTH = {"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
_ENV = {OPERATOR_TOKEN_ENV: _OPERATOR_TOKEN, OPERATOR_ID_ENV: "travis"}

#: "Project X always uses z.ai", in the form an operator actually writes it.
#:
#: Which half moves the transport, measured rather than assumed: with only the
#: `requirement_map` the spawn still reaches zai.test; with only the
#: `provider_lock` it cannot be served at all, because a lock may not move an
#: Anthropic request off its lane (ADR-0139 D4). So in THIS shape the mapping
#: is what routes and the lock is what forbids the alternative — mutating
#: `provider_lock` alone will not redden this file, and should not.
#: The lock's own behaviour (refuse, never downgrade) is pinned in the unit
#: proof, where making the resolver ignore it fails 20 assertions.
_ZAI_LOCK = {
    "id": "project-x-zai",
    "priority": 100,
    "match": {"repo_ids": [_REPO]},
    "action": {
        "provider_lock": "zai-harness",
        "requirement_map": [
            {
                "requirement": {"kind": "concrete_model", "value": TURN_MODEL},
                "effective_model": _POLICY_MODEL,
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
    # Arming the canary is what makes the resolver's answer BINDING. Without
    # it the spawn takes the ungoverned mint path, every turn is served by
    # anthropic.test, and each assertion below would pass against a decision
    # nothing consulted.
    config.gateway_enforcement_canary_repo = _REPO

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


def _served_host(turn: Any) -> str:
    """The exact upstream host the request actually reached.

    Parsed and compared whole rather than prefix-matched:
    ``https://zai.test.example.invalid`` starts with ``https://zai.test`` too.
    """
    assert turn.exchanges, "the origin was never reached"
    return urlsplit(str(turn.exchanges[-1][0])).netloc


def _served_model(turn: Any) -> str:
    assert turn.exchanges, "the origin was never reached"
    return str(json.loads(turn.exchanges[-1][1])["model"])


class TestTheLockHoldsThroughARealSpawn:
    async def test_a_spawn_under_the_written_lock_is_served_by_zai(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The epic's sentence, observed on the wire."""
        operator = _operator(tmp_path, monkeypatch)
        assert operator.write_lock().status_code == 200

        turn = await _turn(operator.config)

        assert _served_host(turn) == "zai.test"

    async def test_the_spawn_succeeded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A lock that broke the spawn would prove nothing about routing."""
        operator = _operator(tmp_path, monkeypatch)
        operator.write_lock()

        turn = await _turn(operator.config)

        assert turn.returncode == 0

    async def test_the_upstream_was_asked_for_the_model_the_lock_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reaching z.ai's host while still asking for a Claude model would be
        the "GLM reported as a Claude model" hazard wearing the right hostname."""
        operator = _operator(tmp_path, monkeypatch)
        operator.write_lock()

        turn = await _turn(operator.config)

        assert _served_model(turn) == _POLICY_MODEL

    async def test_the_spawn_cites_the_lock_rather_than_landing_there_by_luck(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anti-vacuity: assert the REASON, on the decision that authorised the
        mint — not on an observer that cannot change a route.

        A turn that reached z.ai for any other reason — a default, a fallback,
        an unmapped request resolving to itself — satisfies the host assertion
        above and would mean the lock was never consulted.
        """
        operator = _operator(tmp_path, monkeypatch)
        operator.write_lock()

        turn = await _turn(operator.config)

        assert turn.decisions[-1]["policy_id"] == "project-x-zai"

    async def test_a_retry_stays_on_zai(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A retry re-enters the spawn path, so a second turn IS the retry.

        Asserted over every attempt rather than the last: a lock that held on
        the first call and drifted on the second is the failure this clause
        exists for, and it would leave the final turn looking correct.
        """
        operator = _operator(tmp_path, monkeypatch)
        operator.write_lock()

        first = await _turn(operator.config, key_id="p6d-attempt-1")
        second = await _turn(operator.config, key_id="p6d-attempt-2")

        assert [_served_host(first), _served_host(second)] == ["zai.test", "zai.test"]


class TestTheLockIsWhatDoesTheWork:
    """The control. Without it the suite above proves nothing."""

    async def test_without_the_lock_the_same_spawn_is_served_by_anthropic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Identical spawn, no policy written — it must reach the other lane.

        If this spawn could never have reached Anthropic, "always z.ai" would be
        a statement about the fixture rather than about the lock.
        """
        operator = _operator(tmp_path, monkeypatch)

        turn = await _turn(operator.config)

        assert _served_host(turn) == "anthropic.test"
