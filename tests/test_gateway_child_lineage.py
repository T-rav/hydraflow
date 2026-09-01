"""#11990 (P6a): a brokered child's lineage reaches the mint, not just the receipt.

The receipt has carried :class:`driver_contracts.WorkerLineage` since #11541,
but the *mint* never learned any of it. Two consequences, both tested here: the
gateway invented its own ``spawn_id``, so a receipt claimed a child id that no
ledger row shared and the two could not be joined; and no ledger row named the
driver that asked for the work at all.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from gateway_mint_client import GatewayMintRequest, GatewayMintV2Request
from hydraflow_gateway.models import MintKeyRequest, Principal, PrincipalKind
from hydraflow_gateway.route_mint import MintV2Request


class TestAbsentLineageIsExplicit:
    """ "No parent" and "parent unknown" are different facts."""

    def test_a_classic_spawn_records_none_not_empty_string(self) -> None:
        principal = Principal(kind=PrincipalKind.SPAWN, id="planner", spawn_id="s1")

        assert principal.driver_id is None
        assert principal.parent_spawn_id is None

    @pytest.mark.parametrize("field", ["driver_id", "parent_spawn_id"])
    def test_an_empty_lineage_string_is_refused(self, field: str) -> None:
        with pytest.raises(ValueError, match=field):
            Principal(
                kind=PrincipalKind.SPAWN, id="planner", spawn_id="s1", **{field: ""}
            )


class TestEveryWireModelCarriesEveryPrincipalField:
    """Two wire models build a :class:`Principal`; neither may drop a field.

    Derived from the model rather than spelled out: a hand-written list would
    itself need updating for a new field, which is the drift it is meant to
    catch. Omitting a kwarg on a Pydantic builder is silent — the field takes
    its default and nothing raises — so only a check keyed on the real field
    set can see it.
    """

    _WIRE_ONLY = {"kind", "id"}  # spelled principal_kind / principal_id on the wire

    @pytest.mark.parametrize("model", [MintKeyRequest, MintV2Request])
    def test_the_wire_model_accepts_every_principal_field(self, model: Any) -> None:
        expected = set(Principal.model_fields) - self._WIRE_ONLY

        assert expected <= set(model.model_fields)

    @pytest.mark.parametrize("model", [MintKeyRequest, MintV2Request])
    def test_the_builder_propagates_every_principal_field(self, model: Any) -> None:
        common: dict[str, Any] = {
            "principal_kind": PrincipalKind.SPAWN,
            "principal_id": "implementer",
            "spawn_id": "child-1",
            "session_id": "sess-1",
            "driver_id": "driver-7",
            "parent_spawn_id": "parent-3",
            "issue_number": 11990,
            "pr_number": 42,
            "repo_slug": "o/r",
            "repo_class": "hydraflow",
            "ttl_seconds": 60,
        }
        if model is MintKeyRequest:
            request = model(**common, provider_binding="anthropic")
        else:
            request = model(
                **common,
                mint_attempt_id="a1",
                dispatch_id="d1",
                repo="o/r",
                request_face="agentic",
                requirement_kind="capability",
                requirement_value="balanced",
                requested_model="m",
                effective_model="m",
                route_decision_id="rd1",
                policy_id="p1",
                policy_revision=1,
                snapshot_hash="h1",
            )

        principal = request.principal()

        for field in set(Principal.model_fields) - self._WIRE_ONLY:
            assert getattr(principal, field) == common[field], (
                f"{model.__name__}.principal() dropped {field!r}"
            )


class TestTheRunnerSideContractCanCarryEveryPrincipalField:
    """The client dataclasses are a second pair of writers, and they drifted.

    Adding lineage to the gateway's own models left these two untouched, and
    nothing failed until a mint actually ran: the runner builds these, not the
    Pydantic wire models. Derived from :class:`Principal` for the same reason
    as the check above -- a spelled list is one more place to forget.
    """

    _WIRE_ONLY = {"kind", "id"}

    @pytest.mark.parametrize("model", [GatewayMintRequest, GatewayMintV2Request])
    def test_the_runner_contract_has_every_principal_field(self, model: Any) -> None:
        expected = set(Principal.model_fields) - self._WIRE_ONLY

        assert expected <= {f.name for f in dataclasses.fields(model)}

    def test_lineage_reaches_the_wire_when_set(self) -> None:
        request = GatewayMintRequest(
            principal_kind="spawn",
            principal_id="implementer",
            spawn_id="child-1",
            session_id=None,
            repo_slug="o/r",
            repo_class="hydraflow",
            provider_binding="anthropic",
            capture_bodies=False,
            ttl_seconds=60,
            driver_id="driver-7",
            parent_spawn_id="parent-3",
        )

        payload = request.wire_payload()

        assert payload["driver_id"] == "driver-7"
        assert payload["parent_spawn_id"] == "parent-3"

    def test_a_classic_spawn_omits_lineage_from_the_wire(self) -> None:
        """An older gateway forbids extras; an absent driver sends no key."""
        request = GatewayMintRequest(
            principal_kind="spawn",
            principal_id="planner",
            spawn_id="s1",
            session_id=None,
            repo_slug="o/r",
            repo_class="hydraflow",
            provider_binding="anthropic",
            capture_bodies=False,
            ttl_seconds=60,
        )

        payload = request.wire_payload()

        assert "driver_id" not in payload
        assert "parent_spawn_id" not in payload
