"""Route-aware resolve-and-mint: identity in, one decision out (ADR-0141).

The v2 mint's whole claim is that a caller states *who it is and what it needs*
and the gateway decides which account serves it. These tests hold that claim
from both sides: the request shape cannot express a provider choice, and the
store's own invariants (one decision, at most one key, never a second token)
survive replay and concurrency.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from driver_contracts import ModelRequirementKind, WorkerRole
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.models import ProviderBinding, RepoClass, binding_for_model
from hydraflow_gateway.route_mint import (
    CredentialState,
    MintAttemptConflict,
    MintRefusal,
    MintV2Request,
    RouteMintStore,
)
from hydraflow_gateway.routing_policy import DecisionOutcome, RequestFace

_ALL_BINDINGS = frozenset(ProviderBinding)


def _request(**overrides: object) -> MintV2Request:
    payload: dict[str, object] = {
        "mint_attempt_id": "att-1",
        "dispatch_id": "disp-1",
        "principal_kind": "spawn",
        "principal_id": "implementer",
        "spawn_id": "spawn-1",
        "repo": "acme/hydraflow",
        "repo_slug": "acme-hydraflow",
        "repo_class": RepoClass.HYDRAFLOW,
        "worker_role": WorkerRole.IMPLEMENTER,
        "request_face": RequestFace.AGENTIC,
        "requirement_kind": ModelRequirementKind.CAPABILITY,
        "requirement_value": "balanced",
        "requested_model": "claude-sonnet-4-6",
        "effective_model": "glm-5.3",
        "route_decision_id": "dec_abc",
        "policy_id": "project-x-zai",
        "policy_revision": 4,
        "snapshot_hash": "sha256:feed",
        "capture_bodies": False,
        "ttl_seconds": 600,
    }
    payload.update(overrides)
    return MintV2Request.model_validate(payload)


def _store(**overrides: object) -> RouteMintStore:
    key_store = overrides.pop("key_store", None) or VirtualKeyStore(
        max_ttl_seconds=86_400
    )
    return RouteMintStore(
        key_store=key_store,
        configured_bindings=overrides.pop("configured_bindings", _ALL_BINDINGS),  # type: ignore[arg-type]
        wall_clock=overrides.pop("wall_clock", lambda: 1_700_000_000.0),  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------
# AC1 — identity and intent, never a caller-selected provider binding
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        pytest.param("provider_binding", id="a-provider-binding-cannot-be-asked-for"),
        pytest.param("account_id", id="an-account-cannot-be-asked-for"),
        pytest.param("upstream", id="an-upstream-cannot-be-asked-for"),
    ],
)
def test_the_v2_request_cannot_express_a_route_choice(field: str) -> None:
    """``extra="forbid"`` makes the absence structural, not documentary."""
    with pytest.raises(ValidationError):
        _request(**{field: "anthropic"})


def test_the_v2_request_declares_no_binding_field_at_all() -> None:
    """The schema-level statement of AC1, readable without a round trip."""
    assert "provider_binding" not in MintV2Request.model_fields


@pytest.mark.parametrize(
    ("effective_model", "expected"),
    [
        pytest.param("glm-5.3", ProviderBinding.ZAI_HARNESS, id="a-glm-id-binds-zai"),
        pytest.param(
            "claude-opus-4-8",
            ProviderBinding.ANTHROPIC,
            id="an-anthropic-id-binds-anthropic",
        ),
    ],
)
def test_the_account_is_derived_from_the_model_the_policy_chose(
    effective_model: str, expected: ProviderBinding
) -> None:
    """The caller states a model; the gateway decides which account serves it."""
    response = _store().resolve_and_mint(
        _request(
            effective_model=effective_model,
            requirement_kind=ModelRequirementKind.CONCRETE_MODEL,
            requirement_value=effective_model,
        )
    )

    assert response.decision.provider_binding is expected


# --------------------------------------------------------------------------
# AC2 — one attempt, one decision, at most one lease
# --------------------------------------------------------------------------


def test_a_selected_attempt_mints_exactly_one_key() -> None:
    """The affirmative case the invariants below are measured against."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    _store(key_store=key_store).resolve_and_mint(_request())

    assert key_store.active_count == 1


def test_a_selected_attempt_returns_a_usable_token() -> None:
    """A withheld token on the ORIGINAL response would be a silent outage."""
    response = _store().resolve_and_mint(_request())

    assert response.credential_state is CredentialState.ISSUED


def test_the_key_carries_the_decision_it_was_minted_under() -> None:
    """The binding is stamped on the identity, so the data plane can read it."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    _store(key_store=key_store).resolve_and_mint(_request())
    identity = key_store.lease_identities()[0]

    assert identity.route_binding is not None
    assert identity.route_binding.route_decision_id == "dec_abc"


def test_the_key_is_bound_to_the_effective_model() -> None:
    """What the data plane checks every request body against."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    _store(key_store=key_store).resolve_and_mint(_request())
    binding = key_store.lease_identities()[0].route_binding

    assert binding is not None
    assert binding.effective_model == "glm-5.3"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param(
            {
                "requirement_kind": ModelRequirementKind.LITERAL_FAMILY,
                "requirement_value": "claude-opus",
                "effective_model": "glm-5.3",
            },
            MintRefusal.LITERAL_FAMILY_UNSATISFIABLE,
            id="a-literal-family-can-never-be-served-by-glm",
        ),
        pytest.param(
            {
                "requirement_kind": ModelRequirementKind.LITERAL_FAMILY,
                "requirement_value": "claude-opus",
                "effective_model": "claude-sonnet-4-6",
            },
            MintRefusal.LITERAL_FAMILY_UNSATISFIABLE,
            id="a-literal-family-is-not-satisfied-by-the-wrong-family",
        ),
        pytest.param(
            {"repo": "acme-hydraflow"},
            MintRefusal.REPO_IDENTITY_NOT_CANONICAL,
            id="a-lossy-slug-can-never-identify-a-governed-repository",
        ),
        pytest.param(
            {"request_face": RequestFace.UNKNOWN},
            MintRefusal.UNBINDABLE_REQUEST_FACE,
            id="an-unclassified-face-cannot-be-bound",
        ),
        pytest.param(
            {"repo_slug": "acme-somewhere-else"},
            MintRefusal.REPO_IDENTITY_MISMATCH,
            id="the-two-repository-fields-must-name-one-repository",
        ),
    ],
)
def test_a_refused_attempt_is_a_decision_with_a_code(
    overrides: dict[str, object], expected: MintRefusal
) -> None:
    """Refusals are typed answers, not exceptions and not generic failures."""
    response = _store().resolve_and_mint(_request(**overrides))

    assert response.decision.reason == expected.value


def test_a_refused_attempt_mints_no_key_at_all() -> None:
    """AC5's server half: a rejected route never produces a credential."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    _store(key_store=key_store).resolve_and_mint(
        _request(
            requirement_kind=ModelRequirementKind.LITERAL_FAMILY,
            requirement_value="claude-opus",
        )
    )

    assert key_store.active_count == 0


def test_a_refused_attempt_returns_no_token() -> None:
    """Nothing a refused caller receives can reach an upstream."""
    response = _store().resolve_and_mint(
        _request(
            requirement_kind=ModelRequirementKind.LITERAL_FAMILY,
            requirement_value="claude-opus",
        )
    )

    assert response.token is None


def test_an_unconfigured_account_holds_rather_than_rejecting() -> None:
    """A missing upstream credential is an operational gap, not a policy verdict."""
    response = _store(
        configured_bindings=frozenset({ProviderBinding.ANTHROPIC})
    ).resolve_and_mint(_request())

    assert response.decision.outcome is DecisionOutcome.HELD


def test_an_unconfigured_account_names_the_account_it_could_not_use() -> None:
    """An operator needs to know which credential to go and set."""
    response = _store(
        configured_bindings=frozenset({ProviderBinding.ANTHROPIC})
    ).resolve_and_mint(_request())

    assert response.decision.reason == MintRefusal.ACCOUNT_NOT_CONFIGURED.value


# --------------------------------------------------------------------------
# AC3 — same-attempt replay never returns a token again, never a second lease
# --------------------------------------------------------------------------


def test_a_replayed_attempt_creates_no_second_lease() -> None:
    """The duplicate-mint failure mode, stated directly."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    store = _store(key_store=key_store)
    store.resolve_and_mint(_request())
    store.resolve_and_mint(_request())

    assert key_store.active_count == 1


def test_a_replayed_attempt_never_returns_the_token_again() -> None:
    """The raw token exists only on the original response path."""
    store = _store()
    store.resolve_and_mint(_request())

    assert store.resolve_and_mint(_request()).token is None


def test_a_replayed_attempt_says_why_the_token_is_absent() -> None:
    """``withheld-replay`` is what tells the client to revoke and start over."""
    store = _store()
    store.resolve_and_mint(_request())

    assert (
        store.resolve_and_mint(_request()).credential_state
        is CredentialState.WITHHELD_REPLAY
    )


def test_a_replayed_attempt_replays_the_original_decision_id() -> None:
    """One attempt appends exactly one decision, however often it is retried."""
    store = _store()
    first = store.resolve_and_mint(_request())

    assert store.resolve_and_mint(_request()).decision.mint_decision_id == (
        first.decision.mint_decision_id
    )


def test_a_replayed_refusal_replays_its_decision_verbatim() -> None:
    """Held and rejected results replay too — they are durable answers."""
    store = _store()
    refused = _request(
        requirement_kind=ModelRequirementKind.LITERAL_FAMILY,
        requirement_value="claude-opus",
    )
    first = store.resolve_and_mint(refused)

    assert store.resolve_and_mint(refused).decision == first.decision


def test_reusing_an_attempt_id_for_different_intent_is_a_conflict() -> None:
    """An idempotency key that silently covers two intents is not one."""
    store = _store()
    store.resolve_and_mint(_request())

    with pytest.raises(MintAttemptConflict):
        store.resolve_and_mint(_request(effective_model="claude-opus-4-8"))


def test_a_conflicting_replay_mints_nothing() -> None:
    """The conflict is detected before the key store is touched."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    store = _store(key_store=key_store)
    store.resolve_and_mint(_request())
    with pytest.raises(MintAttemptConflict):
        store.resolve_and_mint(_request(effective_model="claude-opus-4-8"))

    assert key_store.active_count == 1


def test_two_threads_racing_one_attempt_id_mint_one_key() -> None:
    """Atomicity, measured rather than asserted from the shape of the code."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    store = _store(key_store=key_store)
    barrier = threading.Barrier(2)

    def attempt() -> None:
        barrier.wait(timeout=5)
        store.resolve_and_mint(_request())

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert key_store.active_count == 1


def test_distinct_attempts_of_one_dispatch_each_mint_their_own_key() -> None:
    """Idempotency is keyed on the attempt, not on the dispatch it belongs to."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    store = _store(key_store=key_store)
    store.resolve_and_mint(_request())
    store.resolve_and_mint(_request(mint_attempt_id="att-2"))

    assert key_store.active_count == 2


# --------------------------------------------------------------------------
# AC8 — the identities correlate, and none of them is credential material
# --------------------------------------------------------------------------


def test_the_decision_view_carries_the_key_it_authorised() -> None:
    """Decision ↔ key is the join the ledger and the active registry both use."""
    response = _store().resolve_and_mint(_request())

    assert response.decision.key_id == response.key_id


def test_the_decision_view_declares_no_credential_shaped_field() -> None:
    """ADR-0138 §D4's schema guard, applied where the token is nearest."""
    forbidden = ("token", "secret", "api_key", "apikey", "digest", "fingerprint")
    from hydraflow_gateway.route_mint import MintDecisionView

    named = [
        field
        for field in MintDecisionView.model_fields
        if any(marker in field.lower() for marker in forbidden)
    ]

    assert named == []


def test_the_attempt_store_reaps_records_it_no_longer_needs() -> None:
    """An unbounded idempotency table is a memory leak with a security story."""
    clock = 1_700_000_000.0
    store = RouteMintStore(
        key_store=VirtualKeyStore(max_ttl_seconds=86_400),
        configured_bindings=_ALL_BINDINGS,
        wall_clock=lambda: clock,
        attempt_retention_seconds=60,
    )
    store.resolve_and_mint(_request())
    clock += 3_600

    assert store.reap_expired_attempts() == 1


def test_a_reaped_attempt_is_no_longer_replayable() -> None:
    """Reaping is only safe once the lease it protected can no longer exist."""
    clock = 1_700_000_000.0

    def wall_clock() -> float:
        return clock

    store = RouteMintStore(
        key_store=VirtualKeyStore(max_ttl_seconds=86_400),
        configured_bindings=_ALL_BINDINGS,
        wall_clock=wall_clock,
        attempt_retention_seconds=60,
    )
    store.resolve_and_mint(_request())
    clock += 3_600
    store.reap_expired_attempts()

    assert store.resolve_and_mint(_request()).credential_state is (
        CredentialState.ISSUED
    )


def test_a_saturated_attempt_table_holds_rather_than_evicting() -> None:
    """Evicting a live attempt would licence exactly the second lease AC3 forbids."""
    store = RouteMintStore(
        key_store=VirtualKeyStore(max_ttl_seconds=86_400),
        configured_bindings=_ALL_BINDINGS,
        wall_clock=lambda: 1_700_000_000.0,
        max_tracked_attempts=1,
    )
    store.resolve_and_mint(_request())

    assert store.resolve_and_mint(
        _request(mint_attempt_id="att-2")
    ).decision.reason == (MintRefusal.MINT_CAPACITY_EXHAUSTED.value)


def test_a_capacity_refusal_does_not_itself_consume_capacity() -> None:
    """Otherwise the ceiling IS the growth: one record per refused attempt.

    A saturated table answers ``mint-capacity-exhausted`` without recording the
    attempt, because recording it would take a slot in the table that is already
    full. Nothing is lost: no lease was reserved, so there is no outcome a replay
    could need to be told about.
    """
    store = RouteMintStore(
        key_store=VirtualKeyStore(max_ttl_seconds=86_400),
        configured_bindings=_ALL_BINDINGS,
        wall_clock=lambda: 1_700_000_000.0,
        max_tracked_attempts=1,
    )
    store.resolve_and_mint(_request())
    for index in range(20):
        store.resolve_and_mint(_request(mint_attempt_id=f"att-{index + 2}"))

    assert store.tracked_attempts == 1


def test_the_expiry_reported_is_the_lease_the_key_store_issued() -> None:
    """A client that trusts a fabricated expiry would renew too late."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    response = _store(key_store=key_store).resolve_and_mint(_request())

    assert response.expires_at == key_store.lease_identities()[0].expires_at


def test_the_binding_helper_and_the_mint_agree_on_the_account() -> None:
    """One definition of model→lane, reused rather than re-derived."""
    response = _store().resolve_and_mint(_request())

    assert response.decision.provider_binding is binding_for_model("glm-5.3")


def test_a_decision_is_timestamped_from_the_injected_clock() -> None:
    """Never from the wall clock: a decision's time is part of its evidence."""
    response = _store().resolve_and_mint(_request())

    assert response.decision.recorded_at == datetime.fromtimestamp(
        1_700_000_000.0, tz=UTC
    )


def test_a_lease_is_never_attributable_to_a_repository_the_decision_omitted() -> None:
    """The mismatch is refused before a key exists, not merely recorded.

    ``repo`` is what the route was resolved against; ``repo_slug`` is what every
    downstream join uses — the key record, the ledger row, the lease view. A
    lease issued on two disagreeing names is worse than no lease.
    """
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    _store(key_store=key_store).resolve_and_mint(
        _request(repo_slug="acme-somewhere-else")
    )

    assert key_store.active_count == 0
