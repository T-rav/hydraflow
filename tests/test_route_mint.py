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
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from driver_contracts import ModelRequirementKind, WorkerRole
from hydraflow_gateway.accounts import AdministrativeState
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.models import (
    ProviderBinding,
    RepoClass,
    binding_for_model,
    legacy_account_id,
)
from hydraflow_gateway.route_mint import (
    CredentialState,
    MintAttemptConflict,
    MintRefusal,
    MintV2Request,
    RouteMintStore,
)
from hydraflow_gateway.routing_account_admin import (
    ACCOUNT_ADMIN_AUDIT_FILENAME,
    AccountAdminStore,
)
from hydraflow_gateway.routing_account_state import AccountRuntimeState
from hydraflow_gateway.routing_accounts import (
    AccountPool,
    GatewayAccount,
    build_account_registry,
)
from hydraflow_gateway.routing_fallback import (
    FallbackRefusal,
    TerminalDecisionIndex,
)
from hydraflow_gateway.routing_policy import (
    AccountRejectionReason,
    DecisionOutcome,
    FallbackCondition,
    RequestFace,
)
from hydraflow_gateway.settings import UpstreamAuthStyle, UpstreamSettings

_ALL_BINDINGS = frozenset(ProviderBinding)


def _upstream(base_url: str) -> UpstreamSettings:
    return UpstreamSettings(
        base_url=base_url,
        api_key=SecretStr("route-mint-test-key"),
        auth_style=UpstreamAuthStyle.BEARER,
    )


def _pool(
    configured_bindings: frozenset[ProviderBinding] = _ALL_BINDINGS,
) -> AccountPool:
    """A legacy-only pool whose configured lanes are exactly *configured_bindings*.

    One account per lane, which is the shape every deployment has before an
    accounts file exists — so the invariants below are asserted against the
    default configuration rather than against a pool the tests invented.
    """
    upstreams = {
        binding: _upstream(f"https://{binding.value}.test")
        for binding in configured_bindings
    }
    return AccountPool(
        build_account_registry(upstreams=upstreams),
        {
            legacy_account_id(binding): upstream
            for binding, upstream in upstreams.items()
        },
    )


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
        pool=overrides.pop("pool", None)
        or _pool(
            overrides.pop("configured_bindings", _ALL_BINDINGS)  # type: ignore[arg-type]
        ),
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
        pool=_pool(),
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
        pool=_pool(),
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
        pool=_pool(),
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
        pool=_pool(),
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


# --------------------------------------------------------------------------
# ADR-0142 AC1/AC2 — more than one account per lane, chosen deterministically
# --------------------------------------------------------------------------


_SECONDARY = "zai-secondary"


def _declared(**overrides: object) -> GatewayAccount:
    payload: dict[str, object] = {
        "id": _SECONDARY,
        "provider_binding": "zai-harness",
        "base_url": "https://api2.z.ai",
        "auth_style": "bearer",
        "credential_env": "GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY",
    }
    payload.update(overrides)
    return GatewayAccount.model_validate(payload)


def _pooled(
    *declared: GatewayAccount, configured: frozenset[str] | None = None
) -> AccountPool:
    """A pool with the legacy accounts plus *declared*, all configured by default."""
    upstreams = {
        binding: _upstream(f"https://{binding.value}.test") for binding in _ALL_BINDINGS
    }
    resolved: dict[str, UpstreamSettings] = {
        legacy_account_id(binding): upstream for binding, upstream in upstreams.items()
    }
    for account in declared:
        resolved[account.account_id] = _upstream(account.base_url)
    if configured is not None:
        resolved = {
            account_id: upstream
            for account_id, upstream in resolved.items()
            if account_id in configured
        }
    return AccountPool(
        build_account_registry(upstreams=upstreams, declared=declared), resolved
    )


def _pooled_store(
    *declared: GatewayAccount,
    pool: AccountPool | None = None,
    key_store: VirtualKeyStore | None = None,
    account_state: AccountRuntimeState | None = None,
    admin: object | None = None,
    terminals: TerminalDecisionIndex | None = None,
    max_fallback_hops: int = 1,
) -> RouteMintStore:
    resolved_pool = pool or _pooled(*declared)
    return RouteMintStore(
        key_store=key_store or VirtualKeyStore(max_ttl_seconds=86_400),
        pool=resolved_pool,
        account_state=account_state or AccountRuntimeState(resolved_pool.registry),
        admin=admin,  # type: ignore[arg-type]
        terminals=terminals,
        max_fallback_hops=max_fallback_hops,
        wall_clock=lambda: 1_700_000_000.0,
    )


def test_a_pooled_lane_still_selects_its_first_account() -> None:
    """Adding a second account moves nothing on its own — the pool is additive."""
    response = _pooled_store(_declared()).resolve_and_mint(_request())

    assert response.decision.account_id == legacy_account_id(
        ProviderBinding.ZAI_HARNESS
    )


def test_the_selected_account_is_what_the_key_is_bound_to() -> None:
    """A decision that named one account and a key bound to another is a lie."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    response = _pooled_store(_declared(), key_store=key_store).resolve_and_mint(
        _request()
    )
    binding = key_store.lease_identities()[0].route_binding

    assert binding is not None
    assert binding.account_id == response.decision.account_id


def test_selection_reports_the_position_it_landed_on() -> None:
    assert (
        _pooled_store(_declared())
        .resolve_and_mint(_request())
        .decision.fallback_position
        == 0
    )


def test_the_same_intent_selects_the_same_account_every_time() -> None:
    """Determinism, asserted over repeated attempts rather than argued for."""
    store = _pooled_store(_declared())
    chosen = {
        store.resolve_and_mint(
            _request(mint_attempt_id=f"att-{index}")
        ).decision.account_id
        for index in range(8)
    }

    assert chosen == {legacy_account_id(ProviderBinding.ZAI_HARNESS)}


def test_a_full_account_hands_the_lane_to_the_next_one() -> None:
    """Capacity is what makes a pool a pool rather than a list.

    Both accounts here are *declared*, because a legacy account deliberately has
    no ceiling — imposing one on the accounts that already serve today's traffic
    is precisely what an additive registry must not do.
    """
    first = _declared(id="zai-a", lease_capacity=1)
    second = _declared(id="zai-b")
    pool = _pooled(
        first,
        second,
        configured=frozenset({"zai-a", "zai-b"}),
    )
    state = AccountRuntimeState(pool.registry)
    state.reserve_lease("zai-a", holder="someone-else")
    store = _pooled_store(pool=pool, account_state=state)

    assert store.resolve_and_mint(_request()).decision.account_id == "zai-b"


def test_a_full_account_is_reported_with_a_capacity_code() -> None:
    """An operator reading a hop needs to know it was capacity, not a circuit."""
    pool = _pooled(
        _declared(id="zai-a", lease_capacity=1),
        _declared(id="zai-b"),
        configured=frozenset({"zai-a", "zai-b"}),
    )
    state = AccountRuntimeState(pool.registry)
    state.reserve_lease("zai-a", holder="someone-else")
    response = _pooled_store(pool=pool, account_state=state).resolve_and_mint(
        _request()
    )

    passed_over = {
        rejection.account_id: rejection.reason
        for rejection in response.decision.rejected_accounts
    }

    assert passed_over["zai-a"] is AccountRejectionReason.LEASE_CAPACITY_EXHAUSTED


def test_a_decision_names_every_account_it_passed_over() -> None:
    """Explainability: a pool nobody can audit is a lookup with extra risk."""
    pool = _pooled(_declared(), configured=frozenset({_SECONDARY}))
    response = _pooled_store(pool=pool).resolve_and_mint(_request())

    assert [
        rejection.account_id for rejection in response.decision.rejected_accounts
    ] == [legacy_account_id(ProviderBinding.ZAI_HARNESS)]


def test_a_lane_with_no_eligible_account_holds_rather_than_rejecting() -> None:
    pool = _pooled(_declared(), configured=frozenset())
    response = _pooled_store(pool=pool).resolve_and_mint(_request())

    assert response.decision.outcome is DecisionOutcome.HELD


def test_pool_membership_changing_between_attempts_never_makes_two_leases() -> None:
    """A replay answers from the record, so live state cannot mint a second key."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    pool = _pooled(_declared())
    state = AccountRuntimeState(pool.registry)
    store = _pooled_store(pool=pool, key_store=key_store, account_state=state)
    store.resolve_and_mint(_request())
    state.reserve_lease(legacy_account_id(ProviderBinding.ZAI_HARNESS), holder="x")
    store.resolve_and_mint(_request())

    assert key_store.active_count == 1


def test_a_selected_attempt_takes_exactly_one_lease_slot() -> None:
    pool = _pooled(_declared())
    state = AccountRuntimeState(pool.registry)
    _pooled_store(pool=pool, account_state=state).resolve_and_mint(_request())

    assert state.lease_count(legacy_account_id(ProviderBinding.ZAI_HARNESS)) == 1


def test_a_refused_attempt_takes_no_lease_slot_at_all() -> None:
    pool = _pooled(_declared(), configured=frozenset())
    state = AccountRuntimeState(pool.registry)
    _pooled_store(pool=pool, account_state=state).resolve_and_mint(_request())

    assert state.lease_count(legacy_account_id(ProviderBinding.ZAI_HARNESS)) == 0


def test_revoking_a_lease_returns_the_slot_it_held() -> None:
    """The exactly-once release, joined end to end at the seam that owns it."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    pool = _pooled(_declared())
    state = AccountRuntimeState(pool.registry)
    key_store.on_release(state.release_lease)
    store = _pooled_store(pool=pool, key_store=key_store, account_state=state)
    response = store.resolve_and_mint(_request())
    key_store.revoke(str(response.key_id))

    assert state.lease_count(legacy_account_id(ProviderBinding.ZAI_HARNESS)) == 0


# --------------------------------------------------------------------------
# ADR-0142 AC4/AC5 — bounded fallback advances only on authoritative evidence
# --------------------------------------------------------------------------


def _hop_setup() -> tuple[
    RouteMintStore, AccountRuntimeState, TerminalDecisionIndex, VirtualKeyStore
]:
    """One selected lease on the primary, its key released, ready to be cited."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    pool = _pooled(_declared())
    state = AccountRuntimeState(pool.registry)
    key_store.on_release(state.release_lease)
    terminals = TerminalDecisionIndex()
    store = _pooled_store(
        pool=pool, key_store=key_store, account_state=state, terminals=terminals
    )
    return store, state, terminals, key_store


def _first_hop(
    store: RouteMintStore,
    terminals: TerminalDecisionIndex,
    key_store: VirtualKeyStore,
    *,
    condition: FallbackCondition | None = FallbackCondition.RATE_LIMITED,
    release: bool = True,
) -> str:
    """Mint on the primary, record its terminal outcome, and hand back its id."""
    first = store.resolve_and_mint(_request())
    terminals.record(
        first.decision.mint_decision_id,
        account_id=str(first.decision.account_id),
        condition=condition,
        now=1_700_000_000.0,
    )
    if release:
        key_store.revoke(str(first.key_id))
    return first.decision.mint_decision_id


def test_a_qualifying_failure_moves_the_next_attempt_to_the_next_account() -> None:
    store, _state, terminals, key_store = _hop_setup()
    cited = _first_hop(store, terminals, key_store)

    second = store.resolve_and_mint(
        _request(mint_attempt_id="att-2", retry_of_mint_decision_id=cited)
    )

    assert second.decision.account_id == _SECONDARY


def test_a_hop_records_the_lineage_that_authorised_it() -> None:
    store, _state, terminals, key_store = _hop_setup()
    cited = _first_hop(store, terminals, key_store)

    second = store.resolve_and_mint(
        _request(mint_attempt_id="att-2", retry_of_mint_decision_id=cited)
    )

    assert (second.decision.fallback_hops, second.decision.fallback_position) == (1, 1)


@pytest.mark.parametrize(
    ("condition", "release", "reason"),
    [
        pytest.param(
            None,
            True,
            FallbackRefusal.NOT_AUTHORISED.value,
            id="the-prior-request-succeeded",
        ),
        pytest.param(
            FallbackCondition.RATE_LIMITED,
            False,
            FallbackRefusal.LEASE_STILL_HELD.value,
            id="the-prior-lease-was-never-revoked",
        ),
    ],
)
def test_an_unlicensed_hop_is_refused_with_its_own_code(
    condition: FallbackCondition | None, release: bool, reason: str
) -> None:
    store, _state, terminals, key_store = _hop_setup()
    cited = _first_hop(
        store, terminals, key_store, condition=condition, release=release
    )

    second = store.resolve_and_mint(
        _request(mint_attempt_id="att-2", retry_of_mint_decision_id=cited)
    )

    assert second.decision.reason == reason


def test_an_unlicensed_hop_mints_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    del monkeypatch
    store, _state, terminals, key_store = _hop_setup()
    cited = _first_hop(store, terminals, key_store, condition=None)
    before = key_store.active_count

    store.resolve_and_mint(
        _request(mint_attempt_id="att-2", retry_of_mint_decision_id=cited)
    )

    assert key_store.active_count == before


def test_the_hop_ceiling_is_a_hard_stop() -> None:
    """One hop is licensed; the second is refused however qualifying it looks."""
    store, _state, terminals, key_store = _hop_setup()
    cited = _first_hop(store, terminals, key_store)
    second = store.resolve_and_mint(
        _request(mint_attempt_id="att-2", retry_of_mint_decision_id=cited)
    )
    terminals.record(
        second.decision.mint_decision_id,
        account_id=str(second.decision.account_id),
        condition=FallbackCondition.RATE_LIMITED,
        now=1_700_000_000.0,
    )
    key_store.revoke(str(second.key_id))

    third = store.resolve_and_mint(
        _request(
            mint_attempt_id="att-3",
            retry_of_mint_decision_id=second.decision.mint_decision_id,
        )
    )

    assert third.decision.reason == FallbackRefusal.BUDGET_EXHAUSTED.value


def test_a_deployment_may_refuse_every_hop() -> None:
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    pool = _pooled(_declared())
    state = AccountRuntimeState(pool.registry)
    key_store.on_release(state.release_lease)
    terminals = TerminalDecisionIndex()
    store = _pooled_store(
        pool=pool,
        key_store=key_store,
        account_state=state,
        terminals=terminals,
        max_fallback_hops=0,
    )
    cited = _first_hop(store, terminals, key_store)

    second = store.resolve_and_mint(
        _request(mint_attempt_id="att-2", retry_of_mint_decision_id=cited)
    )

    assert second.decision.reason == FallbackRefusal.BUDGET_EXHAUSTED.value


def test_a_hop_can_never_reach_an_account_the_pool_refuses() -> None:
    """The boundary does not widen: an unconfigured target stays unreachable."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    pool = _pooled(
        _declared(),
        configured=frozenset(
            {
                legacy_account_id(ProviderBinding.ANTHROPIC),
                legacy_account_id(ProviderBinding.ZAI_HARNESS),
            }
        ),
    )
    state = AccountRuntimeState(pool.registry)
    key_store.on_release(state.release_lease)
    terminals = TerminalDecisionIndex()
    store = _pooled_store(
        pool=pool, key_store=key_store, account_state=state, terminals=terminals
    )
    cited = _first_hop(store, terminals, key_store)

    second = store.resolve_and_mint(
        _request(mint_attempt_id="att-2", retry_of_mint_decision_id=cited)
    )

    assert second.decision.account_id is None


def test_a_citation_naming_another_dispatch_is_rejected() -> None:
    store, _state, terminals, key_store = _hop_setup()
    cited = _first_hop(store, terminals, key_store)

    second = store.resolve_and_mint(
        _request(
            mint_attempt_id="att-2",
            dispatch_id="another-dispatch",
            retry_of_mint_decision_id=cited,
        )
    )

    assert second.decision.outcome is DecisionOutcome.REJECTED


def test_an_unknown_citation_holds_rather_than_starting_over() -> None:
    """Silently restarting could re-select the account that had just failed."""
    store, _state, terminals, key_store = _hop_setup()
    del terminals, key_store

    response = store.resolve_and_mint(
        _request(mint_attempt_id="att-2", retry_of_mint_decision_id="gwd_unknown")
    )

    assert response.decision.reason == FallbackRefusal.LINEAGE_UNKNOWN.value


def test_a_supersede_re_mints_on_the_same_account() -> None:
    """Lost-response recovery is a replacement, not a hop."""
    store, _state, terminals, key_store = _hop_setup()
    cited = _first_hop(store, terminals, key_store, condition=None)

    second = store.resolve_and_mint(
        _request(mint_attempt_id="att-2", supersedes_mint_decision_id=cited)
    )

    assert second.decision.account_id == legacy_account_id(ProviderBinding.ZAI_HARNESS)


def test_a_supersede_before_the_prior_key_is_revoked_is_refused() -> None:
    """Revoke-then-remint: never two live leases for one dispatch."""
    store, _state, terminals, key_store = _hop_setup()
    cited = _first_hop(store, terminals, key_store, condition=None, release=False)

    second = store.resolve_and_mint(
        _request(mint_attempt_id="att-2", supersedes_mint_decision_id=cited)
    )

    assert second.decision.reason == FallbackRefusal.LEASE_STILL_HELD.value


def test_a_hop_never_leaves_two_leases_behind() -> None:
    """The duplicate-billing failure, asserted on the store rather than argued."""
    store, _state, terminals, key_store = _hop_setup()
    cited = _first_hop(store, terminals, key_store)

    store.resolve_and_mint(
        _request(mint_attempt_id="att-2", retry_of_mint_decision_id=cited)
    )

    assert key_store.active_count == 1


def test_an_attempt_cannot_both_hop_and_supersede() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _request(retry_of_mint_decision_id="gwd_a", supersedes_mint_decision_id="gwd_b")


def test_an_ordinary_attempt_cites_nothing_and_starts_at_the_front() -> None:
    """Default-inert: an attempt with no citation is exactly the phase before."""
    assert _request().citation() is None


# --------------------------------------------------------------------------
# ADR-0142 D5 — an unreadable administrative overlay holds, never falls open
# --------------------------------------------------------------------------


def _tampered_admin(tmp_path: Path) -> AccountAdminStore:
    """An overlay whose chain has been edited after the fact, read afresh."""
    directory = tmp_path / "account-state"
    store = AccountAdminStore(directory)
    store.set_state(
        legacy_account_id(ProviderBinding.ZAI_HARNESS),
        AdministrativeState.DISABLED,
        expected_revision=0,
        actor="operator@example.test",
        recorded_at="2026-08-22T10:00:00+00:00",
        registry=build_account_registry(upstreams={}),
    )
    chain = directory / ACCOUNT_ADMIN_AUDIT_FILENAME
    chain.write_text(
        chain.read_text(encoding="utf-8").replace("disabled", "enabled"),
        encoding="utf-8",
    )
    return AccountAdminStore(directory)


def test_a_corrupt_administrative_overlay_holds_the_mint(tmp_path: Path) -> None:
    """Fail-closed in the only safe direction: an unreadable record of what an
    operator withdrew must never read as "nothing was withdrawn"."""
    store = _pooled_store(_declared(), admin=_tampered_admin(tmp_path))

    response = store.resolve_and_mint(_request())

    assert response.decision.reason == MintRefusal.ACCOUNT_STATE_UNAVAILABLE.value


def test_a_corrupt_administrative_overlay_mints_no_key(tmp_path: Path) -> None:
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    store = _pooled_store(
        _declared(), key_store=key_store, admin=_tampered_admin(tmp_path)
    )

    store.resolve_and_mint(_request())

    assert key_store.active_count == 0


def test_a_readable_administrative_overlay_still_mints(tmp_path: Path) -> None:
    """The contrast, so the two tests above are not passing for a second reason."""
    store = _pooled_store(
        _declared(), admin=AccountAdminStore(tmp_path / "untouched-state")
    )

    assert (
        store.resolve_and_mint(_request()).decision.outcome is DecisionOutcome.SELECTED
    )


def test_a_disabled_account_is_passed_over_by_the_mint(tmp_path: Path) -> None:
    """The overlay is not merely read — it decides."""
    admin = AccountAdminStore(tmp_path / "drain-state")
    pool = _pooled(_declared())
    admin.set_state(
        legacy_account_id(ProviderBinding.ZAI_HARNESS),
        AdministrativeState.DISABLED,
        expected_revision=0,
        actor="operator@example.test",
        recorded_at="2026-08-22T10:00:00+00:00",
        registry=pool.registry,
    )
    store = _pooled_store(pool=pool, admin=admin)

    assert store.resolve_and_mint(_request()).decision.account_id == _SECONDARY


def test_a_hop_records_where_it_landed_not_where_it_started_looking() -> None:
    """A skipped candidate must not let the next hop re-select this account.

    The successor computes its start as ``recorded + 1``. When a scan steps over
    an ineligible candidate it lands further down than it began, so recording the
    *start* would put the next hop on the account this decision actually used —
    a fallback that falls back onto the thing that just failed.
    """
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    # Three z.ai candidates; the middle one has no credential, so a hop that
    # starts at position 1 is forced onward and lands at position 2.
    pool = _pooled(
        _declared(id="zai-a"),
        _declared(id="zai-b"),
        configured=frozenset(
            {
                legacy_account_id(ProviderBinding.ANTHROPIC),
                legacy_account_id(ProviderBinding.ZAI_HARNESS),
                "zai-b",
            }
        ),
    )
    state = AccountRuntimeState(pool.registry)
    key_store.on_release(state.release_lease)
    terminals = TerminalDecisionIndex()
    store = _pooled_store(
        pool=pool,
        key_store=key_store,
        account_state=state,
        terminals=terminals,
        max_fallback_hops=2,
    )
    cited = _first_hop(store, terminals, key_store)

    second = store.resolve_and_mint(
        _request(mint_attempt_id="att-2", retry_of_mint_decision_id=cited)
    )

    assert (second.decision.account_id, second.decision.fallback_position) == (
        "zai-b",
        2,
    )


def test_a_second_hop_starts_past_the_account_the_first_one_landed_on() -> None:
    """The end-to-end consequence of recording the landing rather than the start."""
    key_store = VirtualKeyStore(max_ttl_seconds=86_400)
    pool = _pooled(
        _declared(id="zai-a"),
        _declared(id="zai-b"),
        configured=frozenset(
            {
                legacy_account_id(ProviderBinding.ANTHROPIC),
                legacy_account_id(ProviderBinding.ZAI_HARNESS),
                "zai-b",
            }
        ),
    )
    state = AccountRuntimeState(pool.registry)
    key_store.on_release(state.release_lease)
    terminals = TerminalDecisionIndex()
    store = _pooled_store(
        pool=pool,
        key_store=key_store,
        account_state=state,
        terminals=terminals,
        max_fallback_hops=2,
    )
    cited = _first_hop(store, terminals, key_store)
    second = store.resolve_and_mint(
        _request(mint_attempt_id="att-2", retry_of_mint_decision_id=cited)
    )
    terminals.record(
        second.decision.mint_decision_id,
        account_id=str(second.decision.account_id),
        condition=FallbackCondition.RATE_LIMITED,
        now=1_700_000_000.0,
    )
    key_store.revoke(str(second.key_id))

    third = store.resolve_and_mint(
        _request(
            mint_attempt_id="att-3",
            retry_of_mint_decision_id=second.decision.mint_decision_id,
        )
    )

    assert third.decision.account_id is None
