"""The effective-route matrix: one revision, every cell, nothing guessed."""

from __future__ import annotations

import pytest

from driver_contracts import ModelRequirement, ModelRequirementKind, WorkerRole
from hydraflow_gateway.accounts import AdministrativeState
from hydraflow_gateway.models import ProviderBinding, RepoClass
from hydraflow_gateway.routing_policy import (
    AccountAvailability,
    DecisionReason,
    PolicySnapshot,
    RequestFace,
    RequirementMapping,
    RoutingAction,
    RoutingMatch,
    RoutingPolicy,
    SnapshotState,
    hash_policies,
)
from routing_matrix import (
    DEFAULT_MATRIX_REQUIREMENT,
    CellState,
    build_effective_matrix,
    diff_matrices,
)

_REPO = "acme/hydraflow"
_BALANCED = DEFAULT_MATRIX_REQUIREMENT
_OPUS = ModelRequirement(kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-opus")

_ACCOUNTS = (
    AccountAvailability(
        account_id="legacy-anthropic",
        provider_binding=ProviderBinding.ANTHROPIC,
        configured=True,
        administrative_state=AdministrativeState.ENABLED,
    ),
    AccountAvailability(
        account_id="legacy-zai-harness",
        provider_binding=ProviderBinding.ZAI_HARNESS,
        configured=True,
        administrative_state=AdministrativeState.ENABLED,
    ),
)


def _snapshot(*policies: RoutingPolicy, revision: int = 1) -> PolicySnapshot:
    return PolicySnapshot(
        revision=revision,
        policies=policies,
        content_hash=hash_policies(policies),
    )


def _matrix(
    snapshot: PolicySnapshot,
    *,
    state: SnapshotState = SnapshotState.OK,
    requirements: tuple[ModelRequirement, ...] = (_BALANCED,),
):
    return build_effective_matrix(
        repo=_REPO,
        repo_class=RepoClass.HYDRAFLOW,
        accounts=_ACCOUNTS,
        snapshot=snapshot,
        snapshot_state=state,
        requirements=requirements,
    )


def _mapped_zai_policy() -> RoutingPolicy:
    """ "Project X always uses z.ai" in its honest form: lock plus a mapping."""
    return RoutingPolicy(
        id="pin-zai",
        match=RoutingMatch(repo_ids=(_REPO,)),
        action=RoutingAction(
            provider_lock=ProviderBinding.ZAI_HARNESS,
            requirement_map=(
                RequirementMapping(requirement=_BALANCED, effective_model="glm-5.3"),
            ),
        ),
    )


def test_the_default_matrix_covers_every_canonical_worker_role() -> None:
    """A role missing from the grid is a route nobody reviewed."""
    matrix = _matrix(_snapshot())

    assert {cell.role for cell in matrix.cells} == set(WorkerRole)


def test_the_default_matrix_covers_both_request_faces() -> None:
    """Transport differs by face, so governability does too (ADR-0139 D7)."""
    matrix = _matrix(_snapshot())

    assert {cell.request_face for cell in matrix.cells} == {
        RequestFace.AGENTIC,
        RequestFace.ONE_SHOT,
    }


def test_every_cell_is_pinned_to_one_revision() -> None:
    """A matrix whose rows saw different revisions is a race, not a matrix."""
    matrix = _matrix(_snapshot(_mapped_zai_policy(), revision=7))

    assert {cell.decision.policy_revision for cell in matrix.cells} == {7}


def test_a_route_no_policy_claims_is_unmanaged_rather_than_broken() -> None:
    """Shadow mode is still authoritative: "no policy" means legacy decides."""
    matrix = _matrix(_snapshot())

    assert {cell.state for cell in matrix.cells} == {CellState.UNMANAGED}


def test_a_mapped_provider_lock_selects_the_locked_account() -> None:
    """The honest "project X always uses z.ai" form resolves, and says which account."""
    matrix = _matrix(_snapshot(_mapped_zai_policy()))

    assert {cell.decision.account_id for cell in matrix.cells} == {"legacy-zai-harness"}


def _bare_zai_lock() -> RoutingPolicy:
    """The tempting-but-dishonest form: a lock with no requirement mapping."""
    return RoutingPolicy(
        id="pin-zai",
        match=RoutingMatch(repo_ids=(_REPO,)),
        action=RoutingAction(provider_lock=ProviderBinding.ZAI_HARNESS),
    )


def test_a_bare_provider_lock_holds_rather_than_routing() -> None:
    """The builder shows ADR-0139 D4's guard BEFORE the policy is saved."""
    matrix = _matrix(_snapshot(_bare_zai_lock()))

    assert {cell.state for cell in matrix.cells} == {CellState.HELD}


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        pytest.param(
            _BALANCED,
            DecisionReason.CAPABILITY_UNMAPPED,
            id="a-provider-neutral-capability-needs-an-explicit-mapping",
        ),
        pytest.param(
            _OPUS,
            DecisionReason.LITERAL_FAMILY_UNSATISFIABLE,
            id="an-opus-request-may-never-quietly-become-glm",
        ),
    ],
)
def test_a_held_cell_names_which_guard_held_it(
    requirement: ModelRequirement, expected: DecisionReason
) -> None:
    """Two different refusals wear the same badge; only the reason distinguishes them."""
    matrix = _matrix(_snapshot(_bare_zai_lock()), requirements=(requirement,))

    assert {cell.decision.reason for cell in matrix.cells} == {expected}


def test_a_corrupt_snapshot_makes_every_cell_unavailable() -> None:
    """Missing evidence never presents as a coherent "no policies applies"."""
    matrix = _matrix(_snapshot(), state=SnapshotState.CORRUPT)

    assert {cell.state for cell in matrix.cells} == {CellState.UNAVAILABLE}


def test_a_cell_carries_the_explanation_that_produced_it() -> None:
    """ "Pinned explanation" means returned with the matrix, not re-resolved later."""
    matrix = _matrix(_snapshot(_mapped_zai_policy()))

    assert {
        cell.decision.explanation.context.worker_role for cell in matrix.cells
    } == set(WorkerRole)


def test_a_caller_supplied_requirement_adds_its_own_rows() -> None:
    """The builder asks about the families it cares about; nothing is guessed."""
    matrix = _matrix(_snapshot(), requirements=(_BALANCED, _OPUS))

    assert {cell.requirement for cell in matrix.cells} == {_BALANCED, _OPUS}


@pytest.mark.parametrize(
    ("before_policies", "after_policies", "any_changed"),
    [
        pytest.param(
            (),
            (_mapped_zai_policy(),),
            True,
            id="adding-a-policy-moves-the-routes-it-claims",
        ),
        pytest.param(
            (_mapped_zai_policy(),),
            (_mapped_zai_policy(),),
            False,
            id="an-identical-snapshot-moves-nothing",
        ),
        pytest.param(
            (_mapped_zai_policy(),),
            (_mapped_zai_policy().model_copy(update={"id": "renamed"}),),
            False,
            id="renaming-a-rule-that-resolves-the-same-is-not-a-route-change",
        ),
    ],
)
def test_the_diff_reports_only_routes_that_actually_move(
    before_policies: tuple[RoutingPolicy, ...],
    after_policies: tuple[RoutingPolicy, ...],
    any_changed: bool,
) -> None:
    """A before/after view that shouted about renames would train operators to ignore it."""
    diff = diff_matrices(
        _matrix(_snapshot(*before_policies)),
        _matrix(_snapshot(*after_policies, revision=2)),
    )

    assert any(cell.changed for cell in diff) is any_changed


def test_the_diff_names_the_field_that_moved() -> None:
    """ "Something changed" is not actionable; "the account changed" is."""
    diff = diff_matrices(
        _matrix(_snapshot()),
        _matrix(_snapshot(_mapped_zai_policy(), revision=2)),
    )

    assert {field for cell in diff for field in cell.changed_fields} == {
        "state",
        "account_id",
        "provider_binding",
        "effective_model",
    }


def test_the_diff_pairs_every_cell_exactly_once() -> None:
    """A diff that dropped or duplicated a cell would misreport the blast radius."""
    diff = diff_matrices(
        _matrix(_snapshot()),
        _matrix(_snapshot(_mapped_zai_policy(), revision=2)),
    )

    assert len(diff) == len(_matrix(_snapshot()).cells)
