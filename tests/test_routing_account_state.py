"""Live per-account admission: capacity that releases exactly once, and a circuit.

Two claims live here and both are about *counting*, which is the part of a pool
that goes wrong quietly. A lease slot taken twice for one key, or released twice
for one key, oversubscribes or under-subscribes an account with no error
anywhere — so reservation is keyed on the holder rather than on a bare counter,
and both directions are idempotent by construction.

The circuit is passive: it is fed by terminal outcomes the proxy already
records, never by a probe, and an account with no evidence is never "open".
"""

from __future__ import annotations

import threading

import pytest
from pydantic import SecretStr

from hydraflow_gateway.accounts import AdministrativeState, CircuitStateName
from hydraflow_gateway.models import ProviderBinding, legacy_account_id
from hydraflow_gateway.routing_account_state import (
    CIRCUIT_COOLDOWN_SECONDS,
    CIRCUIT_FAILURE_THRESHOLD,
    AccountRuntimeState,
    AccountSelection,
    CircuitState,
    live_facts,
    select_account,
)
from hydraflow_gateway.routing_accounts import (
    AccountPool,
    AccountRegistry,
    GatewayAccount,
    build_account_registry,
)
from hydraflow_gateway.routing_policy import (
    AccountRejectionReason,
    FallbackCondition,
)
from hydraflow_gateway.settings import UpstreamAuthStyle, UpstreamSettings

_ZAI = legacy_account_id(ProviderBinding.ZAI_HARNESS)
_SECONDARY = "zai-secondary"


def _account(**overrides: object) -> GatewayAccount:
    payload: dict[str, object] = {
        "id": _SECONDARY,
        "provider_binding": "zai-harness",
        "base_url": "https://api2.z.ai",
        "auth_style": "bearer",
        "credential_env": "GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY",
    }
    payload.update(overrides)
    return GatewayAccount.model_validate(payload)


def _registry(*declared: GatewayAccount) -> AccountRegistry:
    return build_account_registry(upstreams={}, declared=declared)


def _state(*declared: GatewayAccount, now: float = 1_000.0) -> AccountRuntimeState:
    clock = {"now": now}
    state = AccountRuntimeState(_registry(*declared), wall_clock=lambda: clock["now"])
    state._test_clock = clock  # type: ignore[attr-defined]
    return state


def _advance(state: AccountRuntimeState, seconds: float) -> None:
    state._test_clock["now"] += seconds  # type: ignore[attr-defined]


# -- lease capacity ----------------------------------------------------------


def test_an_account_with_no_declared_ceiling_admits_every_lease() -> None:
    state = _state(_account(lease_capacity=None))
    assert all(state.reserve_lease(_SECONDARY, holder=f"k{n}") for n in range(64))


def test_a_declared_ceiling_refuses_the_lease_past_it() -> None:
    state = _state(_account(lease_capacity=2))
    taken = [state.reserve_lease(_SECONDARY, holder=f"k{n}") for n in range(3)]
    assert taken == [True, True, False]


def test_a_refused_lease_consumes_no_slot() -> None:
    state = _state(_account(lease_capacity=1))
    state.reserve_lease(_SECONDARY, holder="k0")
    state.reserve_lease(_SECONDARY, holder="k1")
    assert state.lease_count(_SECONDARY) == 1


def test_releasing_a_lease_returns_its_slot() -> None:
    state = _state(_account(lease_capacity=1))
    state.reserve_lease(_SECONDARY, holder="k0")
    state.release_lease("k0")
    assert state.reserve_lease(_SECONDARY, holder="k1") is True


@pytest.mark.parametrize("releases", [1, 2, 5], ids=["once", "twice", "five-times"])
def test_a_lease_slot_is_released_exactly_once_however_often_it_is_asked(
    releases: int,
) -> None:
    state = _state(_account(lease_capacity=4))
    state.reserve_lease(_SECONDARY, holder="k0")
    state.reserve_lease(_SECONDARY, holder="k1")
    for _ in range(releases):
        state.release_lease("k0")
    assert state.lease_count(_SECONDARY) == 1


def test_reserving_one_holder_twice_consumes_one_slot() -> None:
    state = _state(_account(lease_capacity=4))
    state.reserve_lease(_SECONDARY, holder="k0")
    state.reserve_lease(_SECONDARY, holder="k0")
    assert state.lease_count(_SECONDARY) == 1


def test_releasing_a_holder_that_never_reserved_changes_nothing() -> None:
    state = _state(_account(lease_capacity=4))
    state.reserve_lease(_SECONDARY, holder="k0")
    state.release_lease("never-seen")
    assert state.lease_count(_SECONDARY) == 1


def test_a_lease_is_still_held_while_its_key_lives() -> None:
    state = _state(_account(lease_capacity=4))
    state.reserve_lease(_SECONDARY, holder="k0")
    assert state.lease_held("k0") is True


def test_a_released_lease_is_no_longer_held() -> None:
    state = _state(_account(lease_capacity=4))
    state.reserve_lease(_SECONDARY, holder="k0")
    state.release_lease("k0")
    assert state.lease_held("k0") is False


def test_an_unknown_account_can_never_take_a_lease() -> None:
    assert _state().reserve_lease("no-such-account", holder="k0") is False


def test_two_threads_racing_the_last_lease_slot_take_it_once() -> None:
    state = _state(_account(lease_capacity=1))
    outcomes: list[bool] = []
    barrier = threading.Barrier(2)

    def take(holder: str) -> None:
        barrier.wait()
        outcomes.append(state.reserve_lease(_SECONDARY, holder=holder))

    threads = [threading.Thread(target=take, args=(f"k{n}",)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == [False, True]


# -- request capacity, which is a separate ceiling ---------------------------


def test_request_capacity_is_counted_apart_from_lease_capacity() -> None:
    state = _state(_account(lease_capacity=1, request_capacity=2))
    state.reserve_lease(_SECONDARY, holder="k0")
    assert all(state.reserve_request(_SECONDARY, holder=f"r{n}") for n in range(2))


def test_a_declared_request_ceiling_refuses_the_request_past_it() -> None:
    state = _state(_account(request_capacity=1))
    state.reserve_request(_SECONDARY, holder="r0")
    assert state.reserve_request(_SECONDARY, holder="r1") is False


@pytest.mark.parametrize("releases", [1, 3], ids=["once", "three-times"])
def test_a_request_slot_is_released_exactly_once(releases: int) -> None:
    state = _state(_account(request_capacity=4))
    state.reserve_request(_SECONDARY, holder="r0")
    state.reserve_request(_SECONDARY, holder="r1")
    for _ in range(releases):
        state.release_request("r0")
    assert state.in_flight_count(_SECONDARY) == 1


def test_releasing_a_lease_does_not_release_a_request_of_the_same_name() -> None:
    state = _state(_account(lease_capacity=4, request_capacity=4))
    state.reserve_request(_SECONDARY, holder="shared-id")
    state.release_lease("shared-id")
    assert state.in_flight_count(_SECONDARY) == 1


# -- the passive circuit -----------------------------------------------------


def test_an_account_with_no_evidence_is_closed() -> None:
    assert _state(_account()).circuit(_SECONDARY).state is CircuitState.CLOSED


def test_consecutive_qualifying_failures_open_the_circuit() -> None:
    state = _state(_account())
    for _ in range(CIRCUIT_FAILURE_THRESHOLD):
        state.record_terminal(_SECONDARY, condition=FallbackCondition.RATE_LIMITED)
    assert state.circuit(_SECONDARY).state is CircuitState.OPEN


def test_one_failure_short_of_the_threshold_leaves_the_circuit_closed() -> None:
    state = _state(_account())
    for _ in range(CIRCUIT_FAILURE_THRESHOLD - 1):
        state.record_terminal(_SECONDARY, condition=FallbackCondition.UNAVAILABLE)
    assert state.circuit(_SECONDARY).state is CircuitState.CLOSED


def test_a_success_between_failures_resets_the_run() -> None:
    state = _state(_account())
    for _ in range(CIRCUIT_FAILURE_THRESHOLD - 1):
        state.record_terminal(_SECONDARY, condition=FallbackCondition.RATE_LIMITED)
    state.record_terminal(_SECONDARY, condition=None)
    state.record_terminal(_SECONDARY, condition=FallbackCondition.RATE_LIMITED)
    assert state.circuit(_SECONDARY).state is CircuitState.CLOSED


def test_an_open_circuit_closes_again_after_its_cooldown() -> None:
    state = _state(_account())
    for _ in range(CIRCUIT_FAILURE_THRESHOLD):
        state.record_terminal(_SECONDARY, condition=FallbackCondition.UNAVAILABLE)
    _advance(state, CIRCUIT_COOLDOWN_SECONDS + 1)
    assert state.circuit(_SECONDARY).state is CircuitState.CLOSED


def test_an_open_circuit_publishes_when_it_will_reset() -> None:
    state = _state(_account(), now=5_000.0)
    for _ in range(CIRCUIT_FAILURE_THRESHOLD):
        state.record_terminal(_SECONDARY, condition=FallbackCondition.CREDIT_EXHAUSTED)
    assert state.circuit(_SECONDARY).reset_at == 5_000.0 + CIRCUIT_COOLDOWN_SECONDS


def test_an_open_circuit_names_the_condition_that_opened_it() -> None:
    state = _state(_account())
    for _ in range(CIRCUIT_FAILURE_THRESHOLD):
        state.record_terminal(_SECONDARY, condition=FallbackCondition.CREDIT_EXHAUSTED)
    assert (
        state.circuit(_SECONDARY).last_condition is FallbackCondition.CREDIT_EXHAUSTED
    )


def test_one_account_s_failures_never_open_another_s_circuit() -> None:
    state = _state(_account())
    for _ in range(CIRCUIT_FAILURE_THRESHOLD):
        state.record_terminal(_SECONDARY, condition=FallbackCondition.RATE_LIMITED)
    assert state.circuit(_ZAI).state is CircuitState.CLOSED


def test_the_consecutive_failure_count_is_published() -> None:
    state = _state(_account())
    state.record_terminal(_SECONDARY, condition=FallbackCondition.RATE_LIMITED)
    assert state.circuit(_SECONDARY).consecutive_failures == 1


# -- deterministic ordered selection: the other half of "pool" ---------------


def _pool(*declared: GatewayAccount, configured: bool = True) -> AccountPool:
    upstreams = {
        ProviderBinding.ANTHROPIC: UpstreamSettings(
            base_url="https://anthropic.test",
            api_key=SecretStr("selection-anthropic-key"),
            auth_style=UpstreamAuthStyle.X_API_KEY,
        ),
        ProviderBinding.ZAI_HARNESS: UpstreamSettings(
            base_url="https://zai.test",
            api_key=SecretStr("selection-upstream-key"),
            auth_style=UpstreamAuthStyle.BEARER,
        ),
    }
    resolved = dict(upstreams)
    account_upstreams: dict[str, UpstreamSettings] = {
        legacy_account_id(binding): upstream for binding, upstream in resolved.items()
    }
    if configured:
        for account in declared:
            account_upstreams[account.account_id] = UpstreamSettings(
                base_url=account.base_url,
                api_key=SecretStr(f"{account.account_id}-key"),
                auth_style=account.auth_style,
            )
    return AccountPool(
        build_account_registry(upstreams=upstreams, declared=declared),
        account_upstreams,
    )


def _select(
    *declared: GatewayAccount,
    state: AccountRuntimeState | None = None,
    administrative: dict[str, AdministrativeState] | None = None,
    start_position: int = 0,
    configured: bool = True,
) -> AccountSelection:
    pool = _pool(*declared, configured=configured)
    return select_account(
        pool=pool,
        state=state or AccountRuntimeState(pool.registry),
        administrative=administrative or {},
        model="glm-5.3",
        start_position=start_position,
    )


def test_selection_takes_the_first_candidate_in_registry_order() -> None:
    assert _select(_account()).account_id == _ZAI


def test_selection_reports_the_position_it_chose() -> None:
    assert _select(_account()).position == 0


def test_a_fallback_start_skips_the_account_that_failed() -> None:
    assert _select(_account(), start_position=1).account_id == _SECONDARY


def test_a_skipped_candidate_is_reported_with_its_own_code() -> None:
    selection = _select(_account(), start_position=1)
    assert (
        selection.rejected[0].reason is AccountRejectionReason.BEFORE_FALLBACK_POSITION
    )


def test_a_start_past_the_last_candidate_selects_nothing() -> None:
    assert _select(_account(), start_position=2).account_id is None


@pytest.mark.parametrize(
    ("administrative", "reason"),
    [
        pytest.param(
            AdministrativeState.DISABLED,
            AccountRejectionReason.ADMINISTRATIVE_DISABLED,
            id="disabled",
        ),
        pytest.param(
            AdministrativeState.DRAINING,
            AccountRejectionReason.ADMINISTRATIVE_DRAINING,
            id="draining",
        ),
    ],
)
def test_an_administratively_withdrawn_account_is_passed_over(
    administrative: AdministrativeState, reason: AccountRejectionReason
) -> None:
    selection = _select(_account(), administrative={_ZAI: administrative})
    assert (selection.account_id, selection.rejected[0].reason) == (_SECONDARY, reason)


def test_an_account_with_an_open_circuit_is_passed_over() -> None:
    declared = _account()
    pool = _pool(declared)
    state = AccountRuntimeState(pool.registry)
    for _ in range(CIRCUIT_FAILURE_THRESHOLD):
        state.record_terminal(_ZAI, condition=FallbackCondition.RATE_LIMITED)
    selection = select_account(
        pool=pool, state=state, administrative={}, model="glm-5.3"
    )
    assert selection.account_id == _SECONDARY


def test_a_full_account_is_passed_over_with_a_capacity_code() -> None:
    declared = _account(lease_capacity=1)
    pool = _pool(declared)
    state = AccountRuntimeState(pool.registry)
    state.reserve_lease(_SECONDARY, holder="k0")
    selection = select_account(
        pool=pool,
        state=state,
        administrative={_ZAI: AdministrativeState.DISABLED},
        model="glm-5.3",
    )
    assert selection.account_id is None
    assert selection.rejected[-1].reason is (
        AccountRejectionReason.LEASE_CAPACITY_EXHAUSTED
    )


def test_an_unconfigured_account_is_never_selected() -> None:
    selection = _select(_account(), start_position=1, configured=False)
    assert selection.account_id is None
    assert selection.rejected[-1].reason is AccountRejectionReason.NOT_CONFIGURED


def test_selection_never_leaves_the_model_s_own_lane() -> None:
    pool = _pool(_account())
    selection = select_account(
        pool=pool,
        state=AccountRuntimeState(pool.registry),
        administrative={},
        model="claude-sonnet-4-6",
    )
    assert selection.account_id == legacy_account_id(ProviderBinding.ANTHROPIC)


def test_selection_is_the_same_answer_on_every_call() -> None:
    pool = _pool(_account())
    state = AccountRuntimeState(pool.registry)
    answers = {
        select_account(
            pool=pool, state=state, administrative={}, model="glm-5.3"
        ).account_id
        for _ in range(16)
    }
    assert answers == {_ZAI}


# -- the two spellings of one circuit vocabulary -----------------------------


def test_the_read_model_and_the_live_state_publish_one_circuit_vocabulary() -> None:
    """Two enums, one wire contract, and a guard so they cannot drift apart.

    ``accounts.CircuitStateName`` exists only so the read model stays a leaf the
    live-state module can import; if the two ever publish different strings, a
    dashboard renders a state the gateway never emits.
    """
    assert {state.value for state in CircuitState} == {
        state.value for state in CircuitStateName
    }


def test_live_facts_publish_an_accounts_declared_ceilings() -> None:
    pool = _pool(_account(lease_capacity=3, request_capacity=7))
    facts = live_facts(pool=pool, state=AccountRuntimeState(pool.registry))

    assert (
        facts[_SECONDARY].lease_capacity,
        facts[_SECONDARY].request_capacity,
    ) == (3, 7)


def test_live_facts_publish_an_open_circuit() -> None:
    pool = _pool(_account())
    state = AccountRuntimeState(pool.registry)
    for _ in range(CIRCUIT_FAILURE_THRESHOLD):
        state.record_terminal(_SECONDARY, condition=FallbackCondition.UNAVAILABLE)

    facts = live_facts(pool=pool, state=state)

    assert facts[_SECONDARY].circuit_state is CircuitStateName.OPEN


def test_live_facts_cover_every_registered_account() -> None:
    pool = _pool(_account())
    facts = live_facts(pool=pool, state=AccountRuntimeState(pool.registry))

    assert set(facts) == set(pool.registry.account_ids)


def test_a_holder_that_already_has_a_slot_keeps_it_at_a_full_account() -> None:
    """Re-reserving an existing holder is a no-op, never a spurious refusal.

    Without the holder check the second call would count the holder's *own*
    existing slot against the ceiling and answer False — turning an idempotent
    reservation into a capacity failure for a key that is already inside the
    limit. The dict keying alone does not catch this: it makes the *count*
    idempotent, not the *answer*.
    """
    state = _state(_account(lease_capacity=1))
    state.reserve_lease(_SECONDARY, holder="k0")

    assert state.reserve_lease(_SECONDARY, holder="k0") is True


def test_a_request_holder_that_already_has_a_slot_keeps_it_too() -> None:
    state = _state(_account(request_capacity=1))
    state.reserve_request(_SECONDARY, holder="r0")

    assert state.reserve_request(_SECONDARY, holder="r0") is True
