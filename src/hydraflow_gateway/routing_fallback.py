"""Bounded fallback: what licenses a hop, and what a hop may never do.

A fallback is a **new attempt** that cites a prior decision. It is not a retry
of a paid request, and nothing here ever re-sends one: the proxy still performs
exactly one upstream attempt and forwards its outcome verbatim. What this module
decides is whether a *fresh* mint may start scanning the candidate list past the
account a prior decision already used.

Four rules, and each exists because its absence is a specific failure:

* **The gateway's own terminal ledger is the only authority.** A caller cites a
  decision id; it does not get to say what happened to it.
  :func:`condition_for_terminal` classifies the row the proxy already wrote, and
  a hop is licensed only when that classification is a qualifying failure
  class. Caller-supplied error text has no standing, so a worker cannot invent a
  429 to reach an account it prefers.
* **The prior lease must already be gone.** ``lease_held`` is checked *before*
  anything is reserved, so the protocol is revoke-then-remint and never
  mint-then-hope. Two live leases for one dispatch is the duplicate-billing
  failure the whole v2 mint exists to prevent, and a fallback is the one place
  that would otherwise create it deliberately.
* **A hop never widens the boundary.** The verdict returns a *position*, and
  nothing else: the candidate list is recomputed from the same effective model
  by the same registry, and every live filter still applies. An account the
  policy or the registry would have refused at position 0 is refused just as
  hard at position 3 — a fallback can only ever reach further down a list it did
  not choose.
* **The lineage must be the same intent.** Same dispatch, same repository, same
  effective model. A citation that does not match is refused rather than
  silently restarted at position 0, because restarting could re-select the very
  account whose failure was being cited — a retry storm wearing a fallback's
  clothes.

``supersedes`` is the same machinery with the advance switched off: it recovers
a lost mint response by re-minting at the *same* position after an acknowledged
revoke, so it is a replacement rather than a hop and consumes no budget.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from hydraflow_gateway.models import GatewayRequestStatus
from hydraflow_gateway.routing_policy import DecisionOutcome, FallbackCondition

if TYPE_CHECKING:
    from collections.abc import Iterator

DEFAULT_MAX_TRACKED_TERMINALS = 10_000
"""Ceiling on the terminal-evidence index. Oldest evidence is evicted first."""

_RATE_LIMITED_STATUS = 429
_CREDIT_EXHAUSTED_STATUS = 402


class FallbackRefusal(StrEnum):
    """Why a cited lineage did not license a hop."""

    LINEAGE_UNKNOWN = "fallback-lineage-unknown"
    LINEAGE_MISMATCH = "fallback-lineage-mismatch"
    CITED_DECISION_NOT_SELECTED = "fallback-cited-decision-not-selected"
    LEASE_STILL_HELD = "fallback-lease-still-held"
    NOT_AUTHORISED = "fallback-not-authorised"
    BUDGET_EXHAUSTED = "fallback-budget-exhausted"
    RESPONSE_WAS_NOT_LOST = "fallback-response-was-not-lost"


FALLBACK_REJECTIONS: frozenset[FallbackRefusal] = frozenset(
    {
        FallbackRefusal.LINEAGE_MISMATCH,
        FallbackRefusal.CITED_DECISION_NOT_SELECTED,
        # The cited decision demonstrably produced a response, so "I lost it" is
        # not a claim about the world that could later become true.
        FallbackRefusal.RESPONSE_WAS_NOT_LOST,
    }
)
"""Refusals that are the caller's error, and therefore rejections.

Everything else is a **hold**: an unknown citation, a lease not yet given back,
missing terminal evidence and an exhausted budget are all states of the world
that a later attempt may legitimately find different. Reporting an operational
state as a policy rejection would send an operator to edit a policy that was
never wrong — the same distinction ADR-0141 §D3 drew for the mint's own refusals.
"""


def outcome_for(refusal: FallbackRefusal) -> DecisionOutcome:
    """The disposition one fallback refusal produces."""
    return (
        DecisionOutcome.REJECTED
        if refusal in FALLBACK_REJECTIONS
        else DecisionOutcome.HELD
    )


def condition_for_terminal(
    *, status_code: int, status: GatewayRequestStatus
) -> FallbackCondition | None:
    """Classify one terminal request row into a qualifying failure class, or ``None``.

    Deliberately narrow, and the exclusions carry as much weight as the
    inclusions:

    * a **client abort** says nothing about the account — the same reason
      ``accounts.derive_health`` excludes it from a health verdict — so it is
      never a licence to move somewhere else;
    * an ordinary **4xx** is the caller's own malformed request. Licensing a hop
      on one would let a worker walk a whole pool by sending four bad bodies,
      spending a lease against every account on the way;
    * a **2xx** is a success, and it resets the account's circuit run.

    Credit exhaustion is recognised only from a status code (``402``). Providers
    also signal it in a response *body*, and this deliberately does not look:
    the body of a governed request or response is a prompt, and a fallback rule
    that had to read one would put prompt content into a routing decision.
    Unrecognised credit exhaustion presents as whatever status it carried —
    usually no hop — which is the safe direction.
    """
    if status is GatewayRequestStatus.CLIENT_ABORTED:
        return None
    if status_code == _RATE_LIMITED_STATUS:
        return FallbackCondition.RATE_LIMITED
    if status_code == _CREDIT_EXHAUSTED_STATUS:
        return FallbackCondition.CREDIT_EXHAUSTED
    if status_code >= 500:
        return FallbackCondition.UNAVAILABLE
    return None


@dataclass(frozen=True, slots=True)
class TerminalEvidence:
    """How one governed decision's most recent request actually ended."""

    account_id: str
    condition: FallbackCondition | None
    recorded_epoch: float


@dataclass(frozen=True, slots=True)
class CitedDecision:
    """The facts a fallback needs about the decision it cites.

    A flat record rather than the decision view itself, so the pure verdict below
    has no dependency on the mint that produces it — and so a test can state one
    lineage without constructing a whole mint request.
    """

    selected: bool
    dispatch_id: str
    repo: str
    effective_model: str
    account_id: str | None
    fallback_position: int
    fallback_hops: int
    key_id: str | None


@dataclass(frozen=True, slots=True)
class FallbackVerdict:
    """Where a new attempt may start scanning, or why it may not start at all."""

    start_position: int = 0
    hops: int = 0
    refusal: FallbackRefusal | None = None

    @property
    def authorised(self) -> bool:
        """Whether this citation licensed the attempt it was made on."""
        return self.refusal is None


class TerminalDecisionIndex:
    """Bounded, process-local record of how each governed decision ended.

    Process-local for the same reason ADR-0141 accepted a process-local attempt
    table: a restart forgets it, an unknown citation *holds* rather than
    advancing, and the failure direction is a spawn that starts at position 0
    instead of one that hops without evidence. A durable index is the follow-up
    if the slice ever widens past one repository.

    Only the **latest** terminal for a decision is kept. A key that failed and
    then succeeded has an account that is working, and licensing a hop off a
    superseded failure would move traffic away from a healthy account.
    """

    def __init__(self, *, max_tracked: int = DEFAULT_MAX_TRACKED_TERMINALS) -> None:
        if max_tracked <= 0:
            raise ValueError("max_tracked must be positive")
        self._max_tracked = max_tracked
        self._entries: OrderedDict[str, TerminalEvidence] = OrderedDict()
        self._lock = threading.Lock()

    def record(
        self,
        mint_decision_id: str,
        *,
        account_id: str,
        condition: FallbackCondition | None,
        now: float,
    ) -> None:
        """Record the terminal outcome of one governed request. Never a body."""
        with self._lock:
            self._entries.pop(mint_decision_id, None)
            self._entries[mint_decision_id] = TerminalEvidence(
                account_id=account_id, condition=condition, recorded_epoch=now
            )
            while len(self._entries) > self._max_tracked:
                self._entries.popitem(last=False)

    def get(self, mint_decision_id: str) -> TerminalEvidence | None:
        """The latest terminal evidence for this decision, or ``None``."""
        with self._lock:
            return self._entries.get(mint_decision_id)

    @property
    def tracked(self) -> int:
        """How many decisions currently carry evidence. Never a credential."""
        with self._lock:
            return len(self._entries)


def authorise_fallback(
    *,
    cited: CitedDecision | None,
    evidence: TerminalEvidence | None,
    lease_held: bool,
    dispatch_id: str,
    repo: str,
    effective_model: str,
    advance: bool,
    max_hops: int,
) -> FallbackVerdict:
    """Decide where a citing attempt may start. Pure and total; never raises.

    The order of the clauses is the order of severity, and it matters: an
    inadmissible citation is refused before the world is consulted, so a caller
    bug can never be reported as a transient operational hold that a retry loop
    would then hammer.
    """
    refusal = next(
        _refusals(
            cited=cited,
            evidence=evidence,
            lease_held=lease_held,
            dispatch_id=dispatch_id,
            repo=repo,
            effective_model=effective_model,
            advance=advance,
            max_hops=max_hops,
        ),
        None,
    )
    if refusal is not None or cited is None:
        return FallbackVerdict(refusal=refusal or FallbackRefusal.LINEAGE_UNKNOWN)
    if not advance:
        # A supersede replaces a lost response at the same position. It consumes
        # no budget because it moves nowhere, and it needs no terminal evidence
        # because the thing it recovers from is the *absence* of a response.
        return FallbackVerdict(
            start_position=cited.fallback_position, hops=cited.fallback_hops
        )
    return FallbackVerdict(
        start_position=cited.fallback_position + 1, hops=cited.fallback_hops + 1
    )


def _refusals(
    *,
    cited: CitedDecision | None,
    evidence: TerminalEvidence | None,
    lease_held: bool,
    dispatch_id: str,
    repo: str,
    effective_model: str,
    advance: bool,
    max_hops: int,
) -> Iterator[FallbackRefusal]:
    """Yield every reason this citation licenses nothing, most severe first."""
    if cited is None:
        yield FallbackRefusal.LINEAGE_UNKNOWN
        return
    if not cited.selected:
        yield FallbackRefusal.CITED_DECISION_NOT_SELECTED
    if (
        cited.dispatch_id != dispatch_id
        or cited.repo != repo
        or cited.effective_model != effective_model
    ):
        yield FallbackRefusal.LINEAGE_MISMATCH
    if lease_held:
        # Revoke-then-remint, enforced rather than documented: while the prior
        # key can still reach an upstream, a successor is a second live lease for
        # one dispatch and both of them can spend.
        yield FallbackRefusal.LEASE_STILL_HELD
    if not advance:
        # A supersede recovers a mint response that was LOST, and the gateway can
        # tell: terminal evidence for the cited decision proves its key reached
        # an upstream, which proves the caller received the credential. Without
        # this clause a supersede is an unbounded, evidence-free re-mint that
        # pins every successor to a position chosen against a pool state that may
        # be long gone — including past an account an operator has since
        # re-enabled.
        if evidence is not None:
            yield FallbackRefusal.RESPONSE_WAS_NOT_LOST
        return
    if evidence is None or evidence.condition is None:
        yield FallbackRefusal.NOT_AUTHORISED
    if cited.fallback_hops + 1 > max_hops:
        yield FallbackRefusal.BUDGET_EXHAUSTED
