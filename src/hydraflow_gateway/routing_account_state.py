"""Live per-account admission: lease slots, request slots, and a passive circuit.

The registry says which accounts *could* serve a model. This says which of them
can serve it *right now*, and it is the only mutable state a route decision
reads. Three properties, each chosen because its failure mode is silent:

* **Reservation is keyed on a holder, not on a counter.** ``reserve_lease`` takes
  the key id and ``reserve_request`` takes the request id, and both are recorded
  in a set. Reserving one holder twice consumes one slot; releasing one holder
  five times returns one slot; releasing a holder that never reserved does
  nothing. Cancellation, expiry, revocation, reaping and shutdown all release the
  same way, so "exactly once" is a property of the data structure rather than of
  every call site remembering to be careful — which is what the design's
  "reservation, release, expiry, revoke, and crash recovery are tested as one
  lifecycle" has to mean in code.
* **Lease and request admission are separate ceilings.** A burst of minted keys
  that never sends a request must not consume an account's concurrent-request
  budget, and a long stream must not block a new lease. They are counted in two
  independent tables keyed by two different identifiers.
* **The circuit is passive.** It is fed only by terminal outcomes the proxy
  already records; nothing here spends a paid call to ask how an account is. An
  account with no evidence is ``closed`` — never "open" and never "healthy" —
  and a single success resets the run, because a circuit that stays open on the
  strength of stale evidence is an outage this module invented.

Thresholds are module constants rather than settings, following ADR-0138's
reasoning about ``DEGRADED_MIN_ERRORS``: these are a first calibration over
passive evidence with no field data behind them, and making them env knobs
invites tuning a number nobody has measured.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from hydraflow_gateway.accounts import AdministrativeState
from hydraflow_gateway.routing_policy import (
    AccountRejection,
    AccountRejectionReason,
    FallbackCondition,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from hydraflow_gateway.routing_accounts import AccountPool, AccountRegistry

CIRCUIT_FAILURE_THRESHOLD = 3
"""Consecutive qualifying failures before an account stops being selected."""

CIRCUIT_COOLDOWN_SECONDS = 60.0
"""How long an opened circuit refuses selection before it is tried again."""


class CircuitState(StrEnum):
    """Whether passive evidence currently rules an account out of selection."""

    CLOSED = "closed"
    OPEN = "open"


@dataclass(frozen=True, slots=True)
class CircuitView:
    """One account's bounded, non-secret circuit evidence."""

    state: CircuitState
    consecutive_failures: int
    last_condition: FallbackCondition | None = None
    reset_at: float | None = None


@dataclass(slots=True)
class _Circuit:
    consecutive_failures: int = 0
    last_condition: FallbackCondition | None = None
    open_until: float | None = None


class AccountRuntimeState:
    """Capacity and circuit for every account in one registry. Thread-safe."""

    def __init__(
        self,
        registry: AccountRegistry,
        *,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._registry = registry
        self._wall_clock = wall_clock
        self._lease_holders: dict[str, str] = {}
        self._request_holders: dict[str, str] = {}
        self._circuits: dict[str, _Circuit] = {}
        self._lock = threading.Lock()

    # -- lease admission ----------------------------------------------------

    def reserve_lease(self, account_id: str, *, holder: str) -> bool:
        """Take one lease slot for *holder*. Idempotent per holder."""
        return self._reserve(self._lease_holders, account_id, holder, _LEASE)

    def release_lease(self, holder: str) -> bool:
        """Return *holder*'s lease slot. Returns whether one was held."""
        with self._lock:
            return self._lease_holders.pop(holder, None) is not None

    def lease_held(self, holder: str) -> bool:
        """Whether this key still holds a lease slot.

        The gateway's answer to "has the prior decision's key actually been
        given back?" — the precondition a bounded fallback checks before it
        reserves anything, so a hop can never hold two leases of one dispatch.
        """
        with self._lock:
            return holder in self._lease_holders

    def lease_count(self, account_id: str) -> int:
        """How many lease slots this account currently has out."""
        return self._count(self._lease_holders, account_id)

    def lease_slot_available(self, account_id: str) -> bool:
        """Whether a lease slot is free right now. Advisory, never a reservation.

        Selection asks this; only :meth:`reserve_lease` decides. Two attempts
        racing the last slot both see it free and exactly one takes it, so a
        caller must still treat a failed reservation as a refusal rather than as
        an impossibility — the check is for the *explanation*, not the guarantee.
        """
        target = account_id.strip().lower()
        account = self._registry.get(target)
        if account is None:
            return False
        if account.lease_capacity is None:
            return True
        return self.lease_count(target) < account.lease_capacity

    def lease_account(self, holder: str) -> str | None:
        """Which account this key's lease slot belongs to, if any."""
        with self._lock:
            return self._lease_holders.get(holder)

    # -- request admission --------------------------------------------------

    def reserve_request(self, account_id: str, *, holder: str) -> bool:
        """Take one concurrent-request slot for *holder*. Idempotent per holder."""
        return self._reserve(self._request_holders, account_id, holder, _REQUEST)

    def release_request(self, holder: str) -> bool:
        """Return *holder*'s request slot. Returns whether one was held."""
        with self._lock:
            return self._request_holders.pop(holder, None) is not None

    def in_flight_count(self, account_id: str) -> int:
        """How many concurrent-request slots this account currently has out."""
        return self._count(self._request_holders, account_id)

    # -- passive circuit ----------------------------------------------------

    def record_terminal(
        self, account_id: str, *, condition: FallbackCondition | None
    ) -> None:
        """Feed one terminal outcome. ``None`` is a success and resets the run."""
        target = account_id.strip().lower()
        with self._lock:
            circuit = self._circuits.setdefault(target, _Circuit())
            if condition is None:
                circuit.consecutive_failures = 0
                circuit.last_condition = None
                circuit.open_until = None
                return
            circuit.consecutive_failures += 1
            circuit.last_condition = condition
            if circuit.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
                circuit.open_until = self._wall_clock() + CIRCUIT_COOLDOWN_SECONDS

    def circuit(self, account_id: str) -> CircuitView:
        """This account's current circuit evidence. Never raises for an unknown id."""
        target = account_id.strip().lower()
        now = self._wall_clock()
        with self._lock:
            circuit = self._circuits.get(target)
            if circuit is None:
                return CircuitView(state=CircuitState.CLOSED, consecutive_failures=0)
            if circuit.open_until is not None and now >= circuit.open_until:
                # The cooldown expired. The run is cleared as well as the gate:
                # keeping the count would re-open the circuit on the very next
                # failure forever, which is a permanent outage wearing a
                # cooldown's clothes.
                circuit.open_until = None
                circuit.consecutive_failures = 0
            open_now = circuit.open_until is not None
            return CircuitView(
                state=CircuitState.OPEN if open_now else CircuitState.CLOSED,
                consecutive_failures=circuit.consecutive_failures,
                last_condition=circuit.last_condition,
                reset_at=circuit.open_until,
            )

    # -- internals ----------------------------------------------------------

    def _reserve(
        self,
        holders: dict[str, str],
        account_id: str,
        holder: str,
        kind: _Kind,
    ) -> bool:
        target = account_id.strip().lower()
        account = self._registry.get(target)
        if account is None:
            return False
        ceiling = kind.ceiling(account)
        with self._lock:
            if holder in holders:
                return True
            if ceiling is not None:
                taken = sum(1 for owner in holders.values() if owner == target)
                if taken >= ceiling:
                    return False
            holders[holder] = target
            return True

    def _count(self, holders: dict[str, str], account_id: str) -> int:
        target = account_id.strip().lower()
        with self._lock:
            return sum(1 for owner in holders.values() if owner == target)


@dataclass(frozen=True, slots=True)
class _Kind:
    """Which of an account's two independent ceilings a reservation counts against."""

    attribute: str

    def ceiling(self, account: object) -> int | None:
        value = getattr(account, self.attribute)
        return None if value is None else int(value)


_LEASE = _Kind("lease_capacity")
_REQUEST = _Kind("request_capacity")


@dataclass(frozen=True, slots=True)
class AccountSelection:
    """Which account was chosen from a pool, at which position, and who was not.

    ``rejected`` carries a code per candidate the selection passed over, so a
    held decision explains itself: an operator can tell "I drained it" from "it
    is rate-limited" from "it is full" without reading the gateway's logs.
    """

    account_id: str | None
    position: int | None
    rejected: tuple[AccountRejection, ...] = ()


def select_account(
    *,
    pool: AccountPool,
    state: AccountRuntimeState,
    administrative: Mapping[str, AdministrativeState],
    model: str,
    start_position: int = 0,
) -> AccountSelection:
    """Choose one account for *model*, deterministically, from *start_position*.

    The candidate list is the registry's static answer for this model, so the
    positions are stable and replayable; *start_position* is where scanning
    begins, which is how a bounded fallback advances **past** the account that
    failed rather than merely to "the next eligible one" — a hop that could
    re-select the account whose terminal failure licensed it is not a fallback.

    Every candidate before the start, and every candidate ruled out by a live
    fact, is reported rather than silently dropped. The first survivor wins:
    the order is the registry's declaration order, which no live state can
    reorder, so two attempts with the same inputs cannot disagree.
    """
    rejected: list[AccountRejection] = []
    for position, account_id in enumerate(pool.candidates_for_model(model)):
        if position < start_position:
            rejected.append(
                AccountRejection(
                    account_id=account_id,
                    reason=AccountRejectionReason.BEFORE_FALLBACK_POSITION,
                )
            )
            continue
        reason = _live_rejection(
            account_id, pool=pool, state=state, administrative=administrative
        )
        if reason is None:
            return AccountSelection(
                account_id=account_id, position=position, rejected=tuple(rejected)
            )
        rejected.append(AccountRejection(account_id=account_id, reason=reason))
    return AccountSelection(account_id=None, position=None, rejected=tuple(rejected))


def _live_rejection(
    account_id: str,
    *,
    pool: AccountPool,
    state: AccountRuntimeState,
    administrative: Mapping[str, AdministrativeState],
) -> AccountRejectionReason | None:
    """The first live fact that rules this account out of a new lease, or None.

    Ordered cheapest-and-most-permanent first: a missing credential is a
    deployment fact, an administrative state is an operator's decision, and a
    circuit or a full lease table is a transient. Reporting the *first* one is
    what makes the code actionable — an account that is both disabled and full
    needs the operator to re-enable it, not to wait.
    """
    if not pool.configured(account_id):
        return AccountRejectionReason.NOT_CONFIGURED
    admin = administrative.get(account_id, AdministrativeState.ENABLED)
    if admin is AdministrativeState.DISABLED:
        return AccountRejectionReason.ADMINISTRATIVE_DISABLED
    if admin is AdministrativeState.DRAINING:
        # Draining refuses NEW leases and leaves existing ones alone, which is
        # automatic: an existing lease is never re-selected, only released.
        return AccountRejectionReason.ADMINISTRATIVE_DRAINING
    if state.circuit(account_id).state is CircuitState.OPEN:
        return AccountRejectionReason.CIRCUIT_OPEN
    if not state.lease_slot_available(account_id):
        return AccountRejectionReason.LEASE_CAPACITY_EXHAUSTED
    return None
