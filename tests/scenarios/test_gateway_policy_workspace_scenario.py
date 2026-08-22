"""MockWorld scenario: an operator edits routing policy, and nothing reroutes.

Everything on the path is real — the dashboard policy routes, the operator write
gate, the write-ahead journal, the atomic snapshot replace, the hash-linked
mutation chain, the shadow resolver, the gateway control plane, the mint, the
streaming proxy, and the ledger. Only the Claude subprocess and the external
Anthropic origin are deterministic fakes; no port is an ``AsyncMock``.

The claim being proven is the one a unit test cannot make: an operator drives a
policy through the **HTTP write plane**, the next real spawn resolves against the
revision they wrote, the decision chain records the disagreement — and the live
turn still reaches Anthropic with byte-identical traffic. That is "shadow mode
remains authoritative", stated at the external boundary rather than asserted.
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
from hydraflow_gateway.routing_workspace import POLICY_AUDIT_FILENAME
from operator_identity import OPERATOR_ID_ENV, OPERATOR_TOKEN_ENV
from route_shadow import (
    ShadowDivergence,
    policy_snapshot_path,
    routing_dir,
    shadow_decision_log_path,
)
from tests.helpers import ConfigFactory
from tests.scenarios.helpers.gateway_turn import TURN_MODEL, run_gateway_turn

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.scenario

_CONTROL_TOKEN = "workspace-scenario-control-token-0123456789"
_PROVIDER_KEY = "workspace-scenario-real-provider-key"
_VIRTUAL_SECRET = "workspace-scenario-virtual-secret"
_OPERATOR_TOKEN = "hfop_" + "w" * 40
_REPO = "acme/project-x"
_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
_AUTH = {"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
_ENV = {OPERATOR_TOKEN_ENV: _OPERATOR_TOKEN, OPERATOR_ID_ENV: "travis"}

_ZAI_POLICY = {
    "id": "project-x-zai",
    "priority": 100,
    "match": {"repo_ids": [_REPO]},
    "action": {
        "provider_lock": "zai-harness",
        # The honest form of "project X always uses z.ai": the lock alone may not
        # move an Anthropic request off its lane (ADR-0139 D4), so the operator
        # says out loud which model answers this one.
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
    """The dashboard as an operator drives it: one client, one credential."""

    client: TestClient
    config: Any

    def read(self) -> dict[str, Any]:
        return self.client.get("/api/gateway/policies").json()

    def effective(self) -> dict[str, Any]:
        return self.client.get("/api/gateway/policies/effective").json()

    def audit(self) -> dict[str, Any]:
        return self.client.get("/api/gateway/policies/audit").json()

    def preview(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.client.post("/api/gateway/policies/preview", json=body).json()

    def save(self, body: dict[str, Any]):
        return self.client.post(
            "/api/gateway/policies/mutations", json=body, headers=_AUTH
        )

    def create_zai_policy(self, *, revision: int = 0):
        return self.save(
            {
                "kind": "create",
                "expected_revision": revision,
                "policy": _ZAI_POLICY,
            }
        )


def _operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, host: str = "127.0.0.1"
) -> _Operator:
    """A real dashboard policy router over a real per-repo workspace."""
    monkeypatch.delenv("HYDRAFLOW_DATA_ROOT", raising=False)
    monkeypatch.delenv("HYDRAFLOW_HOME", raising=False)
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", _CONTROL_TOKEN)

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo", repo=_REPO, dashboard_host=host
    )
    config.gateway_route_shadow_enabled = True
    app = FastAPI()
    app.include_router(
        build_gateway_policy_router(config, env=_ENV, clock=lambda: _NOW)
    )
    return _Operator(client=TestClient(app), config=config)


async def _turn(config: Any) -> tuple[int, list[tuple[str, bytes]]]:
    turn = await run_gateway_turn(
        config=config,
        control_token=_CONTROL_TOKEN,
        provider_key=_PROVIDER_KEY,
        virtual_secret=_VIRTUAL_SECRET,
        key_id="workspace-scenario-key",
    )
    return turn.returncode, turn.exchanges


def _decisions(config: Any) -> list[dict[str, Any]]:
    path = shadow_decision_log_path(config)
    if not path.exists():
        return []
    return [record.payload for record in RoutingAuditLog(path).read_all()]


class TestGatewayPolicyWorkspaceScenario:
    """One operator, one policy, one real turn — and no route moves."""

    def test_a_repository_with_no_policy_reads_as_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The starting state is a fact, not a degraded one."""
        payload = _operator(tmp_path, monkeypatch).read()

        assert (payload["state"], payload["revision"]) == ("absent", 0)

    def test_the_builder_shows_the_routes_an_edit_would_move_before_it_writes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC3, at the boundary: the before/after matrix precedes the write."""
        operator = _operator(tmp_path, monkeypatch)

        payload = operator.preview(
            {"kind": "create", "expected_revision": 0, "policy": _ZAI_POLICY}
        )

        assert [cell["changed"] for cell in payload["cells"]].count(True) > 0

    def test_the_preview_leaves_no_snapshot_behind(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dry run that wrote a file would be a write with better manners."""
        operator = _operator(tmp_path, monkeypatch)

        operator.preview(
            {"kind": "create", "expected_revision": 0, "policy": _ZAI_POLICY}
        )

        assert not policy_snapshot_path(operator.config).exists()

    def test_an_operator_write_lands_on_revision_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The write plane works end to end before anything else is asserted."""
        operator = _operator(tmp_path, monkeypatch)

        response = operator.create_zai_policy()

        assert (response.status_code, response.json()["revision"]) == (200, 1)

    def test_the_write_lands_where_the_shadow_resolver_reads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One authority: the file the operator edits IS the file a spawn resolves."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()

        assert policy_snapshot_path(operator.config).exists()

    async def test_the_next_real_spawn_resolves_against_the_written_revision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The operator's edit reaches the resolver without a restart or a reload."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()

        await _turn(operator.config)

        assert _decisions(operator.config)[0]["proposed"]["policy_revision"] == 1

    async def test_the_spawn_cites_the_policy_the_operator_wrote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A divergence nobody can trace back to a rule is not evidence."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()

        await _turn(operator.config)

        assert (
            _decisions(operator.config)[0]["proposed"]["policy_id"] == "project-x-zai"
        )

    async def test_the_edit_is_recorded_as_a_divergence_not_a_reroute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The measurement this phase exists to produce: what enforcement would do."""
        monkeypatch.setenv("ZAI_API_KEY", "scenario-zai-key")
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()

        await _turn(operator.config)

        assert (
            _decisions(operator.config)[0]["divergence"]
            == ShadowDivergence.PROVIDER_AND_MODEL.value
        )

    async def test_the_live_turn_reaches_the_same_upstream_bytes_after_the_edit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC8 at the external boundary: shadow mode is still authoritative."""
        monkeypatch.setenv("ZAI_API_KEY", "scenario-zai-key")
        unedited = _operator(tmp_path / "unedited", monkeypatch)
        edited = _operator(tmp_path / "edited", monkeypatch)
        edited.create_zai_policy()

        _, before = await _turn(unedited.config)
        _, after = await _turn(edited.config)

        assert after == before

    async def test_the_turn_still_succeeds_after_the_edit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A policy that broke a spawn would be enforcement by accident."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()

        returncode, _ = await _turn(operator.config)

        assert returncode == 0

    def test_a_second_tab_saving_against_the_old_revision_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC4 at the boundary: no lost update between two operator sessions."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()

        response = operator.save(
            {
                "kind": "create",
                "expected_revision": 0,
                "policy": {**_ZAI_POLICY, "id": "project-x-second"},
            }
        )

        assert (response.status_code, response.json()["actual_revision"]) == (409, 1)

    def test_the_refused_save_leaves_the_winning_revision_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC5's other half: a rejected edit is a no-op on the durable state."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()
        before = policy_snapshot_path(operator.config).read_text(encoding="utf-8")

        operator.save(
            {
                "kind": "create",
                "expected_revision": 0,
                "policy": {**_ZAI_POLICY, "id": "project-x-second"},
            }
        )

        assert (
            policy_snapshot_path(operator.config).read_text(encoding="utf-8") == before
        )

    async def test_a_rollback_creates_a_new_revision_the_next_spawn_resolves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC5: rollback moves forward into the past, and the resolver follows."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()
        operator.save(
            {
                "kind": "rollback",
                "expected_revision": 1,
                "target_revision": 0,
            }
        )

        await _turn(operator.config)

        assert _decisions(operator.config)[0]["proposed"]["policy_revision"] == 2

    async def test_the_rolled_back_route_is_unmanaged_again(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rollback has to actually remove the rule, not merely bump a number."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()
        operator.save(
            {"kind": "rollback", "expected_revision": 1, "target_revision": 0}
        )

        await _turn(operator.config)

        assert (
            _decisions(operator.config)[0]["proposed"]["policy_source"]
            == "legacy-compatibility"
        )

    def test_every_mutation_is_recorded_in_one_verifiable_chain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC5: mutation and audit append are one transaction, per revision."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()
        operator.save(
            {"kind": "disable", "expected_revision": 1, "policy_id": "project-x-zai"}
        )

        payload = operator.audit()

        assert (len(payload["records"]), payload["verified"]) == (2, True)

    def test_the_audit_names_the_authenticated_operator(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Provenance comes from the boundary, never from the mutation body."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()

        assert operator.audit()["records"][0]["payload"]["actor"] == "travis"

    def test_the_effective_matrix_shows_the_edit_the_operator_made(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC1: the workspace renders the routes the written revision implies."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()

        payload = operator.effective()

        assert {cell["policy_revision"] for cell in payload["cells"]} == {1}

    def test_the_write_plane_is_closed_on_a_dashboard_bound_beyond_loopback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR-0138 §D5, spent at the boundary rather than in a unit."""
        operator = _operator(tmp_path, monkeypatch, host="0.0.0.0")  # noqa: S104

        response = operator.create_zai_policy()

        assert (response.status_code, response.json()["code"]) == (
            403,
            "dashboard-not-loopback",
        )

    def test_no_credential_reaches_any_policy_payload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC7: the operator credential is never echoed by the plane it opens."""
        operator = _operator(tmp_path, monkeypatch)
        created = operator.create_zai_policy().text
        reads = "\n".join(
            operator.client.get(f"/api/gateway/policies{suffix}").text
            for suffix in ("", "/effective", "/audit")
        )

        assert _OPERATOR_TOKEN not in f"{created}\n{reads}"

    def test_no_credential_reaches_the_durable_policy_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The snapshot and the chain outlive the session that wrote them."""
        operator = _operator(tmp_path, monkeypatch)
        operator.create_zai_policy()
        stored = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                policy_snapshot_path(operator.config),
                routing_dir(operator.config) / POLICY_AUDIT_FILENAME,
            )
        )

        assert _OPERATOR_TOKEN not in stored
