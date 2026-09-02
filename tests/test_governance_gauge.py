"""#11992 (P6c): the runtime gauge for governed direct-provider bypass.

The architecture gauge (#11987) proves no code path execs an agent without the
resolver. This proves no *execution* reached a provider without a route, which
is a different claim: a governed code path still produces an ungoverned row if
the route resolved to nothing and the spawn went ahead.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hydraflow_gateway.governance_gauge import measure_governance
from hydraflow_gateway.ledger import GatewayLedgerRow
from hydraflow_gateway.models import Principal, PrincipalKind, RepoClass

_WHEN = datetime(2026, 9, 1, tzinfo=UTC)
_GOVERNED = "acme/hydraflow"


def _row(
    *,
    request_id: str = "r1",
    repo_slug: str = _GOVERNED,
    route_decision_id: str | None = None,
    mint_decision_id: str | None = None,
) -> GatewayLedgerRow:
    return GatewayLedgerRow(
        request_id=request_id,
        key_id="key-1",
        principal=Principal(
            kind=PrincipalKind.SPAWN, id="implementer", spawn_id="child-1"
        ),
        repo_slug=repo_slug,
        repo_class=RepoClass.HYDRAFLOW,
        body_capture_policy="metadata-only",
        timestamp=_WHEN,
        latency_ms=12.5,
        status_code=200,
        status="completed",
        upstream_provider="anthropic",
        model_requested="m",
        model_served="m",
        input_tokens=1,
        output_tokens=1,
        completed=True,
        client_aborted=False,
        usage_complete=True,
        cost_usd=0.001,
        cost_unknown=False,
        route_decision_id=route_decision_id,
        mint_decision_id=mint_decision_id,
    )


def _governs(repo_slug: str) -> bool:
    return repo_slug == _GOVERNED


class TestABypassIsCountedAndNamed:
    def test_a_governed_row_with_no_route_is_ungoverned(self) -> None:
        gauge = measure_governance([_row()], governs=_governs)

        assert gauge.ungoverned == 1
        assert gauge.offenders[0].request_id == "r1"

    def test_the_offender_names_the_provider_it_actually_reached(self) -> None:
        """ "Something bypassed" is not actionable; "reached anthropic" is."""
        gauge = measure_governance([_row()], governs=_governs)

        assert gauge.offenders[0].upstream_provider == "anthropic"

    def test_a_minted_key_with_no_route_is_reported_as_the_narrower_fault(
        self,
    ) -> None:
        gauge = measure_governance([_row(mint_decision_id="mint-1")], governs=_governs)

        assert gauge.offenders[0].mint_decision_id == "mint-1"

    def test_a_routed_row_is_governed_and_not_an_offender(self) -> None:
        gauge = measure_governance([_row(route_decision_id="rd-1")], governs=_governs)

        assert (gauge.governed, gauge.ungoverned) == (1, 0)


class TestItCountsRatherThanSamples:
    def test_every_row_is_examined_including_ungoverned_repositories(self) -> None:
        rows = [_row(request_id="r1"), _row(request_id="r2", repo_slug="other/repo")]

        gauge = measure_governance(rows, governs=_governs)

        assert gauge.examined == 2

    def test_a_row_for_an_ungoverned_repo_is_never_an_offender(self) -> None:
        """The gauge measures the governed claim, not every request on the host."""
        gauge = measure_governance([_row(repo_slug="other/repo")], governs=_governs)

        assert (gauge.governed, gauge.ungoverned) == (0, 0)

    def test_all_offenders_are_reported_not_the_first(self) -> None:
        rows = [_row(request_id=f"r{n}") for n in range(1, 4)]

        gauge = measure_governance(rows, governs=_governs)

        assert [o.request_id for o in gauge.offenders] == ["r1", "r2", "r3"]


class TestAnEmptyWindowIsNotAPass:
    """ "Nothing bypassed" and "nothing ran" are the same number, opposite facts."""

    def test_no_rows_at_all_is_not_clean(self) -> None:
        assert measure_governance([], governs=_governs).clean is False

    def test_rows_for_only_ungoverned_repositories_is_not_clean(self) -> None:
        gauge = measure_governance([_row(repo_slug="other/repo")], governs=_governs)

        assert gauge.clean is False

    def test_a_governed_routed_row_is_clean(self) -> None:
        gauge = measure_governance([_row(route_decision_id="rd-1")], governs=_governs)

        assert gauge.clean is True

    def test_one_bypass_among_many_governed_rows_is_not_clean(self) -> None:
        rows = [_row(request_id="r1", route_decision_id="rd-1"), _row(request_id="r2")]

        gauge = measure_governance(rows, governs=_governs)

        assert gauge.clean is False


class TestTheLivePredicateIsAsked:
    def test_the_gauge_asks_the_predicate_rather_than_a_copied_set(self) -> None:
        """A gauge holding its own copy goes stale the moment an operator edits."""
        asked: list[str] = []

        def recording(repo_slug: str) -> bool:
            asked.append(repo_slug)
            return True

        measure_governance([_row(repo_slug="whatever/repo")], governs=recording)

        assert asked == ["whatever/repo"]
