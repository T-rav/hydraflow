"""#11990 (P6a): a brokered child's lineage reaches the mint, not just the receipt.

The receipt has carried :class:`driver_contracts.WorkerLineage` since #11541,
but the *mint* never learned any of it. Two consequences, both tested here: the
gateway invented its own ``spawn_id``, so a receipt claimed a child id that no
ledger row shared and the two could not be joined; and no ledger row named the
driver that asked for the work at all.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest

from gateway_mint_client import GatewayMintRequest, GatewayMintV2Request
from hydraflow_gateway.active_routes import (
    ActiveRouteRegistry,
    InFlightRoute,
    InFlightRouteView,
    LeaseView,
    TerminalRoute,
    TerminalRouteView,
    build_active_routes_view,
    build_recent_routes_view,
    lease_view,
)
from hydraflow_gateway.models import (
    GatewayRequestStatus,
    MintKeyRequest,
    Principal,
    PrincipalKind,
)
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


class TestTheOperatorSurfaceCarriesLineage:
    """#11990: the console must be able to group a driver's children.

    Five records and views describe one identity at three ages — a lease, an
    in-flight request, a finished one — and each is built by its own function.
    Five writers is where a field gets added to four of them, so the set is
    derived from :class:`Principal` rather than spelled here.
    """

    _LINEAGE = ("spawn_id", "driver_id", "parent_spawn_id")

    @pytest.mark.parametrize(
        "model",
        [InFlightRoute, TerminalRoute, LeaseView, InFlightRouteView, TerminalRouteView],
    )
    def test_the_route_record_carries_lineage(self, model: Any) -> None:
        if dataclasses.is_dataclass(model):
            fields = {f.name for f in dataclasses.fields(model)}
        else:
            fields = set(model.model_fields)

        assert set(self._LINEAGE) <= fields

    def test_lineage_is_optional_so_a_v1_route_still_constructs(self) -> None:
        """Every existing caller predates these fields and must keep working."""
        route = InFlightRoute(
            request_id="r1",
            provider_binding="anthropic",
            repo_slug="o/r",
            repo_class="hydraflow",
            principal_kind=PrincipalKind.SPAWN,
            principal_id="implementer",
            issue_number=None,
            pr_number=None,
            path="/v1/messages",
            started_at=datetime(2026, 9, 1, tzinfo=UTC),
        )

        assert route.driver_id is None
        assert route.spawn_id is None


class TestLineageSurvivesProjectionToTheView:
    """Field presence is not propagation.

    The record and the view are built by different functions, so a view can
    carry a ``driver_id`` column that its projector never fills — the column
    reads as "this route had no driver", which is a real answer to a question
    nobody asked. Dropping the forwarding line from both projectors passes a
    presence check, so this drives the real projectors instead.
    """

    _WHEN = datetime(2026, 9, 1, tzinfo=UTC)

    def _route(self, **kwargs: Any) -> InFlightRoute:
        return InFlightRoute(
            request_id="r1",
            provider_binding="anthropic",
            repo_slug="o/r",
            repo_class="hydraflow",
            principal_kind=PrincipalKind.SPAWN,
            principal_id="implementer",
            issue_number=None,
            pr_number=None,
            path="/v1/messages",
            started_at=self._WHEN,
            **kwargs,
        )

    def test_an_in_flight_route_keeps_its_lineage_through_the_projector(self) -> None:
        route = self._route(
            spawn_id="child-1", driver_id="drv-7", parent_spawn_id="parent-3"
        )

        view = build_active_routes_view(
            leases=(),
            in_flight=(route,),
            now=self._WHEN,
            evidence_since=self._WHEN,
        )

        projected = view.in_flight[0]
        assert (projected.spawn_id, projected.driver_id, projected.parent_spawn_id) == (
            "child-1",
            "drv-7",
            "parent-3",
        )

    def test_a_terminal_route_keeps_its_lineage_through_the_projector(self) -> None:
        route = TerminalRoute(
            request_id="r1",
            provider_binding="anthropic",
            repo_slug="o/r",
            repo_class="hydraflow",
            principal_kind=PrincipalKind.SPAWN,
            principal_id="implementer",
            issue_number=None,
            pr_number=None,
            path="/v1/messages",
            model_requested="m",
            model_served="m",
            status=GatewayRequestStatus.COMPLETED,
            status_code=200,
            latency_ms=1.0,
            started_at=self._WHEN,
            cost_usd=None,
            cost_unknown=False,
            spawn_id="child-1",
            driver_id="drv-7",
            parent_spawn_id="parent-3",
        )

        view = build_recent_routes_view(
            routes=(route,),
            now=self._WHEN,
            evidence_since=self._WHEN,
            capacity=10,
            truncated=False,
        )

        projected = view.routes[0]
        assert (projected.spawn_id, projected.driver_id, projected.parent_spawn_id) == (
            "child-1",
            "drv-7",
            "parent-3",
        )


def _identity(**lineage: Any) -> Any:
    """One resolved key whose principal carries child lineage."""
    from hydraflow_gateway.models import GatewayIdentity, RepoClass

    when = datetime(2026, 9, 1, tzinfo=UTC)
    return GatewayIdentity(
        key_id="key-1",
        principal=Principal(
            kind=PrincipalKind.SPAWN, id="implementer", spawn_id="child-1", **lineage
        ),
        repo_slug="o/r",
        repo_class=RepoClass.HYDRAFLOW,
        provider_binding="anthropic",
        body_capture_policy="metadata-only",
        issued_at=when,
        expires_at=when,
    )


class TestTheRecordBuildersReadLineageOffThePrincipal:
    """The other half: a projector can only forward what the builder recorded.

    ``_track`` and ``lease_view`` copy field-by-field off ``identity.principal``
    rather than passing the principal along, so a lineage field that is never
    copied is lost before any view is built — and a view-level check cannot see
    it, because the record it projects genuinely has no driver.
    """

    _WHEN = datetime(2026, 9, 1, tzinfo=UTC)

    def test_a_lease_view_reads_the_driver_off_the_principal(self) -> None:
        view = lease_view(_identity(driver_id="drv-7"), now=self._WHEN)

        assert view.driver_id == "drv-7"
        assert view.spawn_id == "child-1"

    def test_tracking_a_request_records_the_driver(self) -> None:
        registry = ActiveRouteRegistry()

        registry.register(
            request_id="r1",
            identity=_identity(driver_id="drv-7", parent_spawn_id="parent-3"),
            path="/v1/messages",
            started_at=self._WHEN,
        )

        view = build_active_routes_view(
            leases=(),
            in_flight=registry.in_flight(),
            now=self._WHEN,
            evidence_since=self._WHEN,
        )
        assert view.in_flight[0].driver_id == "drv-7"
        assert view.in_flight[0].parent_spawn_id == "parent-3"

    def test_releasing_a_request_keeps_the_driver_on_the_terminal_route(self) -> None:
        """``_terminal_route`` re-reads the principal; the row is not the record."""
        from hydraflow_gateway.ledger import GatewayLedgerRow

        identity = _identity(driver_id="drv-7", parent_spawn_id="parent-3")
        registry = ActiveRouteRegistry()
        registry.register(
            request_id="r1",
            identity=identity,
            path="/v1/messages",
            started_at=self._WHEN,
        )

        registry.release(
            GatewayLedgerRow(
                request_id="r1",
                key_id=identity.key_id,
                principal=identity.principal,
                repo_slug=identity.repo_slug,
                repo_class=identity.repo_class,
                body_capture_policy=identity.body_capture_policy,
                timestamp=self._WHEN,
                latency_ms=12.5,
                status_code=200,
                status="completed",
                upstream_provider=identity.provider_binding,
                model_requested="m",
                model_served="m",
                input_tokens=2,
                output_tokens=3,
                completed=True,
                client_aborted=False,
                usage_complete=True,
                cost_usd=0.001,
                cost_unknown=False,
            )
        )

        view = build_recent_routes_view(
            routes=registry.recent(),
            now=self._WHEN,
            evidence_since=self._WHEN,
            capacity=10,
            truncated=False,
        )
        assert view.routes[0].driver_id == "drv-7"
        assert view.routes[0].parent_spawn_id == "parent-3"
