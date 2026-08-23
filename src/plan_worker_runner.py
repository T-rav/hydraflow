"""The brokered Plan canary's actuator: one admitted request, one child (#11541).

This is the module #11537 deliberately did not write. ``ShadowDispatchBroker``
still has no method that dispatches anything — its public surface is exactly
``admit`` and an architecture guard pins that — so the capability arrives here,
in a module whose whole reason to exist is to be the one place a brokered child
is started. Adding it *beside* the shadow broker rather than inside it keeps
"the shadow director cannot dispatch" a true statement about the shadow path
while the canary runs next to it.

**One admitted request becomes exactly one child process**, and each child gets
its own everything: its own spawn id, its own short-lived gateway key (minted
per spawn inside ``resolve_harness_env``), its own route decision, its own
wall-clock budget, and its own :class:`driver_contracts.WorkerReceipt` carrying
parent-driver lineage. The transport is pinned to the gateway rather than
dialled, because the key, the route decision and the ledger row are all gateway
properties: a brokered child on a direct lane could satisfy none of the issue's
third acceptance criterion.

**The served model is read back, never echoed.** ``run_lightweight_agent``
reports what it actually spawned through ``spawn_out``, and that is what the
receipt records — checked against the requirement before the receipt is built,
so a route that answered ``claude-opus`` with a GLM id produces a refusal rather
than a receipt claiming a model that never served. Asserting on the *requested*
tier instead would be blind to exactly the failure the invariant is named after.

**The fence is re-read immediately before each spawn, with no await between the
check and the claim.** That ordering is the whole of "crash, timeout, stale
label/epoch/policy, gateway outage, stop and resume-loss produce no duplicate
or late dispatch": a stop set, an epoch bumped or a label dragged in the window
between the broker's admission and the spawn refuses, and the idempotency key
is claimed before the process starts so a replay can never produce a second
child for the same key.

Air-gap: the spawn goes through ``runner_utils.run_lightweight_agent``, which
this module names lexically, so it carries a ``SANDBOX_SEAMS`` row. The seam
kind is ``config_disable`` because the sandbox pins
``execution_runtime=stage_subprocess``, under which nothing constructs a
director and therefore nothing constructs this runner; the sandbox additionally
clears ``fable_plan_canary_repo``, so even a director that did exist would
dispatch nothing.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, cast

from driver_contracts import (
    ReceiptStatus,
    RejectionReason,
    WorkerLineage,
    WorkerReceipt,
    WorkerTransport,
)
from exception_classify import reraise_on_credit_or_bug
from hydraflow_gateway.routing_policy import DecisionReason
from plan_broker import PlanRouteOutcome, PlanRouteReason, resolve_plan_model
from runner_utils import run_lightweight_agent

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from agent_cli import AgentTool
    from config import HydraFlowConfig
    from driver_contracts import DriverLease, DriverPhase, WorkerDispatchRequest
    from execution import SimpleResult, SubprocessRunner
    from gateway_mint_client import GatewayControlClient
    from models import Task
    from plan_broker import PlanRouteDecision

logger = logging.getLogger("plan_worker_runner")

MAX_ARTIFACT_CHARS = 20000
"""How much of a child's reply is retained. A receipt is evidence, not a store."""

MAX_RETAINED_RECORDS = 50
"""How many recent decisions and artifacts this runner keeps for diagnosis.

Bounded for the same reason :data:`MAX_DISPATCHED_KEYS` is. These are
diagnostics read by a human or a test; the durable evidence is the receipt on
the shadow log, and a canary that had to keep every artifact in memory to be
auditable would be one whose evidence lived in the wrong place."""

MAX_DISPATCHED_KEYS = 2000
"""How many spent idempotency keys the replay fence remembers.

Bounded because this object lives for the whole run. A boundary key already
carries the driver epoch and the phase attempt, so a key recurring after two
thousand dispatches is not the replay this fence exists to catch — while an
unbounded set on a long-lived component is a slow leak with no upper bound at
all."""

#: Which refusal each unsatisfiable tier resolution reports on the receipt.
#: A table rather than branches so the mapping is one thing an operator can
#: read, and so a new :class:`plan_broker.PlanRouteReason` fails loudly here
#: (``_REFUSAL_CODES[...]`` raises) rather than defaulting to a plausible code.
_REFUSAL_CODES: dict[PlanRouteReason, RejectionReason] = {
    PlanRouteReason.PHASE_NOT_PLAN: RejectionReason.ROLE_PHASE_FORBIDDEN,
    PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_PLAN: RejectionReason.ROLE_PHASE_FORBIDDEN,
    PlanRouteReason.LITERAL_FAMILY_UNSATISFIABLE: (
        RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
    ),
    # A hold, not a rejection: the tier table is the fixable thing and the
    # request was not inadmissible. Mapping it to the terminal code — which an
    # earlier draft did — put two holds for the same reason under opposite
    # receipt codes inside one module.
    PlanRouteReason.CAPABILITY_UNMAPPED: RejectionReason.ROUTE_UNAVAILABLE,
    PlanRouteReason.CONCRETE_MODEL_REQUESTED: (
        RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
    ),
}

#: Routing-policy refusal reasons that mean *the request was inadmissible*
#: rather than *something operational is missing*. These map to
#: MODEL_REQUIREMENT_UNSATISFIABLE — retrying changes nothing, whatever an
#: operator edits; every other reason is ROUTE_UNAVAILABLE, where a caretaker
#: retry is right once whatever is missing is supplied. The remedy for a hold
#: may be a policy edit rather than a gateway one, so this does not say "look
#: at the gateway" — an earlier version did, and it was wrong for every hold
#: except an outage.
#:
#: Built from the resolver's own enum rather than from string literals, because
#: the first draft of this set contained a member that does not exist
#: (``concrete-model-not-allowed``) and omitted one that does
#: (``policy-conflict``) — a hand-written copy of another module's vocabulary
#: drifts silently and reads as a working classification while classifying
#: nothing. ``tests/test_plan_worker_runner.py`` requires every
#: :class:`DecisionReason` member to be classified, so a new one fails there
#: rather than defaulting to "retry it".
_INADMISSIBLE_ROUTE_REASONS = frozenset(
    {
        DecisionReason.LITERAL_FAMILY_UNSATISFIABLE.value,
        DecisionReason.MODEL_NOT_ALLOWED.value,
        # Two policies claim the same rung: an operator must resolve it, and a
        # retry against an unresolved conflict is an infinite one.
        DecisionReason.POLICY_CONFLICT.value,
    }
)

#: Reasons deliberately left retryable, and why — so the judgement is visible
#: rather than implied by absence from the set above.
_OPERATIONAL_ROUTE_REASONS = frozenset(
    {
        # The snapshot will be back; nothing about the request is wrong.
        DecisionReason.SNAPSHOT_UNAVAILABLE.value,
        # Unreachable on THIS seam, and the reason is worth stating because
        # an earlier comment here got it wrong: it is not that the resolver
        # never rejects on a hold — ``enforce_canary_route`` raises on every
        # non-SELECTED outcome, HELD included, which is the whole premise of
        # classifying on the reason. It is that a brokered child's model is
        # always a ``PLAN_TIER_CATALOG`` id, and ``requirement_for_model``
        # returns CAPABILITY only for an *empty* model string — so the resolver
        # cannot emit ``capability-unmapped`` for one of these spawns at all.
        # Classified anyway, because the table is required to be total.
        DecisionReason.CAPABILITY_UNMAPPED.value,
        # Collapses "no credential for this account" with "a provider lock
        # excluded every account". The first is operational and the second is
        # policy, and the resolver does not distinguish them here — so the
        # conservative reading is the retryable one, which sends the operator
        # to the gateway where both are visible.
        DecisionReason.NO_ELIGIBLE_ACCOUNT.value,
        # Reasons a *selected* decision carries. They reach a refusal only
        # through ``enforce_canary_route``'s empty-effective-model guard, which
        # a brokered child cannot trip (its legacy model is always the catalog
        # id) — so "not a refusal" is nearly but not exactly right, and
        # operational is the correct reading of the case that can occur.
        DecisionReason.MATCHED_POLICY.value,
        DecisionReason.NO_POLICY_APPLIES.value,
        # NOT one of those two, and an earlier comment here swept it in with
        # them: ``_legacy_decision`` emits it HELD, so it raises at the outcome
        # check rather than at the empty-model guard. It is unreachable for a
        # different reason — ``route_shadow.build_route_context`` always
        # constructs a ``LegacyRoute``, so ``context.legacy_route`` is never
        # ``None`` on this path. Operational either way: nothing about the
        # request is wrong.
        DecisionReason.NO_LEGACY_ROUTE.value,
    }
)


class PlanWorkerSpawn(Protocol):
    """The one-shot spawn seam, injectable so a unit test needs no gateway.

    Spelled out rather than ``**kwargs`` so the seam has a real contract: a
    double that quietly drops ``issue_labels`` or ``spawn_out`` would otherwise
    typecheck, and both are load-bearing — the first feeds the CH-6 gate and the
    second is where the served model comes back from.
    """

    async def __call__(
        self,
        *,
        runner: SubprocessRunner,
        config: HydraFlowConfig,
        tool: str,
        model: str,
        prompt: str,
        source: str,
        timeout: float,
        issue_number: int,
        issue_labels: Sequence[str],
        provider: str,
        gateway_client: GatewayControlClient | None,
        spawn_out: dict[str, object],
    ) -> SimpleResult: ...


async def _spawn_plan_worker(
    *,
    runner: SubprocessRunner,
    config: HydraFlowConfig,
    tool: str,
    model: str,
    prompt: str,
    source: str,
    timeout: float,
    issue_number: int,
    issue_labels: Sequence[str],
    provider: str,
    gateway_client: GatewayControlClient | None,
    spawn_out: dict[str, object],
) -> SimpleResult:
    """The real seam. Named so the scan sees it and the seam row is honest.

    Delegating to ``run_lightweight_agent`` rather than spawning here is what
    gives a brokered child the CH-6 data-governance gate, the per-spawn gateway
    mint and revoke, the credit-exhaustion detection and the telemetry row —
    all of which a hand-rolled spawn would have to re-derive, and one of which
    it would get wrong.

    The signature is spelled out rather than forwarded as ``**kwargs`` on
    purpose: ``issue_labels`` has to be *visible at the call site* for
    ``tests/test_prompt_gate_completeness.py`` to see it, and a forwarding
    wrapper is exactly how a spawn ends up silently under-enforcing the CH-6
    data-class elevation while every test still passes.
    """
    return await run_lightweight_agent(
        runner=runner,
        config=config,
        tool=cast("AgentTool", tool),
        model=model,
        prompt=prompt,
        source=source,
        timeout=timeout,
        issue_number=issue_number,
        issue_labels=issue_labels,
        provider=provider,
        gateway_client=gateway_client,
        spawn_out=spawn_out,
    )


@dataclass(frozen=True, slots=True)
class PlanWorkerArtifact:
    """One child's output, kept beside its receipt rather than inside it."""

    request_id: str
    role: str
    served_model: str
    model_observed: bool
    """True when the CLI named the model; False when the requested id stands in.

    Recorded rather than assumed, because "the served model" is the claim this
    canary is judged on and an unobserved one is weaker evidence than an
    observed one. Collapsing the two would make the weaker claim invisible.
    """

    decision_id: str
    """The tier decision that authorised this child. The join back to *why*."""

    text: str


class PlanWorkerRunner:
    """Dispatches admitted Plan requests as real children and mints receipts.

    Constructed at the ``build_services`` composition root and only under
    ``execution_runtime=fable_director`` — so Classic and the deterministic
    controller have no such object in their process at all.

    Under a director it is built **unconditionally**, armed or not, and gated
    only by ``plan_broker.plan_canary_covers``. Making construction conditional
    on the dial read as a stronger default-off proof and was a bug: the dial is
    live and empty by default, so a factory booted disarmed had nothing to arm
    and naming a canary repository silently did nothing until a restart. Both
    directions of a live dial have to work, or it is not live.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        route_policy_revision: str,
        runner: SubprocessRunner,
        spawn: PlanWorkerSpawn | None = None,
        gateway_client: GatewayControlClient | None = None,
    ) -> None:
        self._config = config
        self._route_policy_revision = route_policy_revision
        # Injected so a scenario can drive the REAL seam — the real mint, the
        # real revoke, the real env scrub — against a recording control plane
        # instead of a live gateway. ``None`` in production builds the ordinary
        # HTTP client inside ``resolve_harness_env``.
        self._gateway_client = gateway_client
        # Injected from the composition root and REQUIRED, never built inside a
        # method: that is what lets the sandbox substitute a
        # ``FakeSubprocessRunner``, and what #11602/#11615 cost this repo twice
        # in one night by getting backwards. Required rather than defaulted
        # because a runner this class built itself would be the seam being
        # aspirational, and because ``run_lightweight_agent`` cannot spawn
        # without one anyway.
        self._runner = runner
        self._spawn: PlanWorkerSpawn = spawn or _spawn_plan_worker
        # Bounded, because this object lives for the whole run: an unbounded set
        # on a long-lived component is a slow leak, and a boundary key already
        # carries the epoch and the phase attempt, so a "duplicate" arriving
        # MAX_DISPATCHED_KEYS dispatches later is not the replay this fence
        # exists to catch.
        self._dispatched_keys: set[str] = set()
        self._dispatched_order: deque[str] = deque()
        # Bounded for the same reason the replay fence is: this object lives
        # for the whole run, and an unbounded list on one is a leak with no
        # ceiling. Both are diagnostics — the durable record is the receipt.
        self.decisions: deque[PlanRouteDecision] = deque(maxlen=MAX_RETAINED_RECORDS)
        # request_id -> decision_id for the batch just dispatched. Batch-local
        # and therefore bounded by MAX_DISPATCH_BATCH: it exists so the
        # receipt row can carry the join back to the tier decision, and a
        # run-lifetime version of it would be a third accumulator.
        self.last_decision_ids: dict[str, str] = {}
        self.artifacts: deque[PlanWorkerArtifact] = deque(maxlen=MAX_RETAINED_RECORDS)

    @property
    def spawn(self) -> PlanWorkerSpawn:
        """What actually starts a child. Read-only, and exposed so a test can
        assert the default IS the real seam — an injection point nobody checks
        is a seam in name only, which is how the s51/s56/s57 wedges happened."""
        return self._spawn

    async def dispatch(
        self,
        requests: Sequence[WorkerDispatchRequest],
        *,
        task: Task,
        lease: DriverLease,
        phase: DriverPhase,
        fence: Callable[[], RejectionReason | None],
    ) -> tuple[WorkerReceipt, ...]:
        """Run every admitted request as its own child. Returns one receipt each.

        Requests are dispatched in order, and each is fenced immediately before
        its own spawn rather than once for the batch: the second child of a
        batch starts after the first has finished, so a stop arriving during
        the first must stop the second. Serial rather than concurrent for
        exactly that reason — ``asyncio.gather`` would start every child before
        any of them could observe a stop.

        Which is why the budget bounds the **batch**. This is awaited inside the
        allocator tick, so a per-child budget would let one boundary block every
        other driver for ``MAX_DISPATCH_BATCH`` times the dial. Each child is
        given whatever the batch has left; once that is spent the rest are
        refused with ``WORKER_TIMEOUT`` rather than started.
        """
        deadline = time.monotonic() + float(
            self._config.fable_plan_worker_timeout_seconds
        )
        self.last_decision_ids = {}
        receipts: list[WorkerReceipt] = []
        for request in requests:
            receipts.append(
                await self._dispatch_one(request, task, lease, phase, fence, deadline)
            )
        return tuple(receipts)

    def refuse(
        self, requests: Sequence[WorkerDispatchRequest], reason: RejectionReason
    ) -> tuple[WorkerReceipt, ...]:
        """Mint a refusal receipt per request without resolving or spawning.

        For refusals decided *outside* this module — the canary's one-issue
        slot, held by the director because it alone sees when an issue leaves
        PLAN. Minting them here rather than at the caller keeps every receipt
        in the codebase produced by one function, so "a refusal names no served
        model" is a property of :func:`_refusal` rather than of each caller
        remembering it.
        """
        blank = _unresolved_decision(self._route_policy_revision)
        # Reset the join too. Without this the refused receipts inherited the
        # PREVIOUS batch's ids whenever a request id repeated across issues —
        # which it does, because a director names its requests per turn rather
        # than per issue. A blank decision must produce a blank join, or the
        # field this canary added to make the join real records a false one.
        self.last_decision_ids = dict.fromkeys(
            (request.request_id for request in requests), ""
        )
        return tuple(_refusal(request, reason, blank) for request in requests)

    # -- one child ----------------------------------------------------------

    async def _dispatch_one(
        self,
        request: WorkerDispatchRequest,
        task: Task,
        lease: DriverLease,
        phase: DriverPhase,
        fence: Callable[[], RejectionReason | None] | None = None,
        deadline: float | None = None,
    ) -> WorkerReceipt:
        decision = resolve_plan_model(
            request,
            phase=phase,
            route_policy_revision=self._route_policy_revision,
        )
        self.decisions.append(decision)
        self.last_decision_ids[request.request_id] = decision.decision_id
        if decision.outcome is not PlanRouteOutcome.SELECTED:
            logger.info(
                "plan_worker_runner: #%d %s refused before spawn (%s)",
                task.id,
                request.worker_role.value,
                decision.reason.value,
            )
            return _refusal(request, _REFUSAL_CODES[decision.reason], decision)

        # The fence and the idempotency claim are one step, with no ``await``
        # between them. Anything else leaves a window in which two admissions
        # of the same key both observe it unclaimed.
        blocked = None if fence is None else fence()
        if blocked is None and request.idempotency_key in self._dispatched_keys:
            blocked = RejectionReason.DUPLICATE_IDEMPOTENCY_KEY
        if blocked is not None:
            return _refusal(request, blocked, decision)

        budget = self._remaining_budget(deadline)
        if budget <= 0.0:
            # The batch spent its whole budget on earlier children. Refused
            # rather than started with a nonsensical deadline, and *before* the
            # key is claimed — a request that never ran must stay replayable.
            return _refusal(
                request,
                RejectionReason.WORKER_TIMEOUT,
                decision,
                status=ReceiptStatus.EXPIRED,
            )
        self._claim(request.idempotency_key)

        return await self._run_child(request, task, lease, decision, budget)

    async def _run_child(
        self,
        request: WorkerDispatchRequest,
        task: Task,
        lease: DriverLease,
        decision: PlanRouteDecision,
        budget: float,
    ) -> WorkerReceipt:
        child_spawn_id = uuid.uuid4().hex
        # Minted before the spawn so every path AFTER it can name the child that
        # ran — including the refusals. A refusal that dropped it made a reaped
        # child look like one that never started.
        lineage = WorkerLineage(
            driver_id=lease.driver_id,
            epoch=lease.epoch,
            child_spawn_id=child_spawn_id,
            depth=1,
        )
        spawn_out: dict[str, object] = {}
        started = datetime.now(UTC)
        try:
            result = await self._spawn(
                runner=self._runner,
                config=self._config,
                tool="claude",
                model=decision.served_model,
                prompt=build_plan_worker_prompt(
                    role=request.worker_role.value,
                    task_contract=request.task_contract,
                    issue_goal=_issue_goal(task),
                    issue_number=task.id,
                ),
                source=request.worker_role.value,
                timeout=budget,
                issue_number=task.id,
                issue_labels=tuple(task.tags or ()),
                # Pinned, not dialled: see the module docstring.
                provider="gateway",
                gateway_client=self._gateway_client,
                spawn_out=spawn_out,
            )
        except TimeoutError:
            # A deadline that escaped the seam rather than one it handled: the
            # seam converts its OWN timeout into ``spawn_out["timed_out"]`` and
            # a soft rc=-1, which lands below. So this fires for work outside
            # that inner try — ``gate_prompt``, the route-shadow and enforcement
            # threads, the Docker client (``socket.timeout`` IS ``TimeoutError``)
            # before a child exists, or the seam's outer ``finally`` after one
            # did. An earlier comment here asserted the second case only, and
            # attached a spawn id on the strength of it.
            return _refusal(
                request,
                RejectionReason.WORKER_TIMEOUT,
                decision,
                status=ReceiptStatus.EXPIRED,
                lineage=_child_lineage(spawn_out, lineage),
            )
        except Exception as exc:
            # A burnt credit balance is factory-wide and must not be converted
            # into a worker refusal (dark-factory 2.2); everything else is this
            # child's failure and becomes a receipt rather than an exception a
            # shadow-shaped observer would have to carry into the allocator.
            #
            # **No lineage on this path**, and the honest reason is not the
            # one an earlier version of this comment gave. It named
            # ``GatewayMintError`` and the seam's ``provider 'gateway' requires
            # the Claude harness`` guard, and **neither reaches here**: the mint
            # error is caught inside the seam and becomes a soft ``rc=-1`` (that
            # is the case the ``spawned`` guard below exists for), and the
            # harness guard is a ``ValueError``, which is a likely bug and is
            # re-raised by ``reraise_on_credit_or_bug`` below — besides being
            # unreachable from a call site that passes ``tool="claude"``
            # literally.
            #
            # What actually lands here is the work *around* the spawn:
            # ``_terminal_gateway_runner`` failing to open a Docker client, a
            # non-``EnforcementRefused`` failure from the route-shadow or
            # enforcement threads, a non-``PromptGateBlockedError`` from the
            # CH-6 gate — all before a child exists — and ``cleanup()`` in the
            # seam's outer ``finally``, which is the one case where a child
            # *did* run. That last one is a known under-attribution: a receipt
            # with no spawn id for a child that had one. Under-claiming is the
            # safe direction for the discriminator, and the alternative is
            # claiming a spawn on every case above it.
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "plan_worker_runner: #%d %s could not be dispatched: %s",
                task.id,
                request.worker_role.value,
                exc,
            )
            return _refusal(request, RejectionReason.ROUTE_UNAVAILABLE, decision)

        requested = str(spawn_out.get("model", "") or "")
        if not spawn_out.get("spawned"):
            # The seam returned without starting a process. FOUR ways in,
            # and the last two are why this guard reads ``spawned`` rather than
            # ``model``:
            #
            # * the CH-6 gate and an ``EnforcementRefused`` return *before* the
            #   seam's try block, so they fill no ``model`` (the refusal does
            #   leave ``refused``/``refused_outcome``, which ``_refusal_for_spawn``
            #   reads below);
            # * a ``GatewayMintError`` is neither fatal nor a likely bug, so the
            #   seam CATCHES it and its ``finally`` fills ``model`` anyway;
            # * ``run_simple`` itself can fail to start anything — a
            #   ``DockerRunner`` whose daemon is down, a ``HostRunner`` with no
            #   CLI binary — which the seam also swallows.
            #
            # Keying on ``model`` let the second fall through to the ACCEPTED
            # receipt below, and setting ``spawned`` before ``run_simple`` let
            # the third: a worker recorded as accepted, with a spawn id, a
            # served model and zero cost, for a child that never existed. In
            # the canary's own evidence record, twice.
            refusal = _refusal_for_spawn(spawn_out)
            logger.info(
                "plan_worker_runner: #%d %s never spawned: %s/%s -> %s",
                task.id,
                request.worker_role.value,
                spawn_out.get("refused_outcome") or "no-decision",
                spawn_out.get("refused") or "no-reason",
                refusal.value,
            )
            return _refusal(request, refusal, decision)
        if spawn_out.get("timed_out"):
            # A deadline, not a bad reply. The seam converts its own timeout
            # into a soft rc=-1, so without this signal a timed-out child would
            # be recorded ACCEPTED with an unusable artifact — which is exactly
            # what the acceptance criteria call an EXPIRED worker.
            return _refusal(
                request,
                RejectionReason.WORKER_TIMEOUT,
                decision,
                status=ReceiptStatus.EXPIRED,
                lineage=_child_lineage(spawn_out, lineage),
            )
        # The model the CLI *reported*, when it reported one. When it did not,
        # the requested id is recorded and ``model_observed`` says so rather
        # than the receipt implying an observation it never made.
        observed = str(spawn_out.get("served_model", "") or "")
        served = observed or requested
        if not request.model_requirement.satisfied_by(served):
            logger.warning(
                "plan_worker_runner: #%d %s asked for %s and was served %r; "
                "refusing the receipt rather than recording the substitution",
                task.id,
                request.worker_role.value,
                request.model_requirement.value,
                served,
            )
            return _refusal(
                request,
                RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE,
                decision,
                lineage=_child_lineage(spawn_out, lineage),
            )

        text = (result.stdout or "")[:MAX_ARTIFACT_CHARS]
        self.artifacts.append(
            PlanWorkerArtifact(
                request_id=request.request_id,
                role=request.worker_role.value,
                served_model=served,
                model_observed=bool(observed),
                decision_id=decision.decision_id,
                text=text,
            )
        )
        return WorkerReceipt(
            request_id=request.request_id,
            idempotency_key=request.idempotency_key,
            status=ReceiptStatus.ACCEPTED,
            lineage=lineage,
            worker_role=request.worker_role,
            transport=WorkerTransport.BROKERED,
            requested_model=request.model_requirement,
            served_model=served,
            route_policy_revision=decision.route_policy_revision,
            artifact_digest=_digest(text),
            output_contract_ok=result.returncode == 0 and bool(text.strip()),
            started_at=started,
            finished_at=datetime.now(UTC),
            usd_cost=_estimate_cost(served, spawn_out.get("usage")),
        )

    def _remaining_budget(self, deadline: float | None) -> float:
        """What this batch has left, in seconds. The dial when unbounded."""
        configured = float(self._config.fable_plan_worker_timeout_seconds)
        if deadline is None:
            return configured
        return min(configured, deadline - time.monotonic())

    def _claim(self, key: str) -> None:
        """Record an idempotency key as spent, keeping the set bounded."""
        self._dispatched_keys.add(key)
        self._dispatched_order.append(key)
        while len(self._dispatched_order) > MAX_DISPATCHED_KEYS:
            self._dispatched_keys.discard(self._dispatched_order.popleft())


def build_plan_worker_prompt(
    *, role: str, task_contract: str, issue_goal: str, issue_number: int
) -> str:
    """The whole of one brokered Plan worker's input.

    Everything the child is allowed to know arrives here, and it is the same
    shape as the director's capsule for the same reason: a worker whose context
    is a bounded, declared payload is one whose output can be judged against
    what it was actually given. There is no repository access, no credential,
    no conversation history and no earlier turn.

    The instruction leads and the variable payload is delimited and last, per
    ADR-0087's long-context placement rule.
    """
    return f"""Answer one bounded question about a HydraFlow issue and return prose.

You are a HydraFlow `{role}` working on issue #{issue_number}. Your entire
assignment is the task contract at the end of this message. Everything you are
allowed to know about the issue is in the goal block; there is nothing else to
consult and no earlier turn to remember.

Do the work the task contract asks for. Respond with the finding itself and
nothing else: prose under Markdown headings, under 800 words. Do not wrap the
reply in a code fence, do not add a preamble about what you are about to do,
and do not explain your process.

Rules:

- Answer the task contract and nothing wider. A broader answer is not a better
  one — the plan that consumes this has a fixed shape and an off-topic section
  is discarded.
- You have no shell, no file access and no ability to move a label, merge a
  pull request, or start a process. Do not describe using one.

Edge cases, and what to do about each:

- If the goal is missing a fact the contract needs, say exactly which fact is
  absent in one short section and stop. A stated gap is a useful answer; a
  guess presented as a finding is not.
- If the task contract is ambiguous, answer the narrowest reading of it and say
  in one line which reading you took.
- Otherwise, if you are unsure whether something belongs in the reply, leave it
  out. A short correct finding is worth more than a long hedged one.

<example>
For the contract "list the modules that implement chunked upload and how they
signal failure", a good reply opens:

## Modules

`upload/chunker.py` splits the stream and owns retry state; `upload/session.py`
holds the multipart session and is the only writer of the manifest.

## Failure signalling

Both raise `UploadAborted`, which the caller converts to a 409 …
</example>

<task_contract>
{task_contract}
</task_contract>

<issue_goal>
{issue_goal}
</issue_goal>
"""


def _refusal(
    request: WorkerDispatchRequest,
    reason: RejectionReason,
    decision: PlanRouteDecision,
    *,
    status: ReceiptStatus = ReceiptStatus.REJECTED,
    lineage: WorkerLineage | None = None,
) -> WorkerReceipt:
    """A real receipt for a real refusal, naming no served model.

    ``served_model`` is left unset on every refusal path — including the one
    where a model *was* served but did not satisfy the requirement. Recording
    it would put a mis-resolved id on a receipt in the one field whose validator
    exists to make that a validation error, which is the smuggling path rather
    than the evidence.

    ``lineage`` is the opposite case and is passed on the refusals that follow a
    **real spawn**: a child that ran to its deadline and was reaped did exist,
    was billed, and had a spawn id, and a receipt that hid that would make a
    dispatched child indistinguishable from one that was never started. It is
    what tells the two emitters of ``WORKER_TIMEOUT`` apart, and what keeps the
    worker tree from reporting ``dispatched: false`` for a child that ran.
    """
    return WorkerReceipt(
        request_id=request.request_id,
        idempotency_key=request.idempotency_key,
        status=status,
        reason_code=reason,
        lineage=lineage,
        worker_role=request.worker_role,
        transport=WorkerTransport.BROKERED,
        requested_model=request.model_requirement,
        route_policy_revision=decision.route_policy_revision,
        output_contract_ok=False,
    )


def _child_lineage(
    spawn_out: dict[str, object], lineage: WorkerLineage
) -> WorkerLineage | None:
    """*lineage* when a child actually started, ``None`` when none did.

    One rule for every refusal that can follow a spawn, rather than one per
    ``except`` clause. Which clause fired says nothing useful: the seam handles
    its own deadline and converts it to a soft ``rc=-1``, so a ``TimeoutError``
    that *escapes* it comes from the work around the spawn — the CH-6 gate, the
    route-shadow and enforcement threads, a Docker socket (``socket.timeout``
    IS ``TimeoutError``) — which happen before a child exists, or from the seam's
    outer ``finally``, which happens after one did.

    ``spawn_out["spawned"]`` is set from ``run_simple``'s **outcome**: it
    returned, or it timed out. Both imply a process — neither runner
    implementation returns for one that failed to start, and only a started
    process can outlive a deadline.

    The residual runs the other way now, and is named rather than hidden: a
    child that started but whose call ended some third way — a Docker
    ``attach_socket`` failing after ``container.start()`` succeeded, or the
    seam's ``cleanup()`` raising in its outer ``finally`` — reads *unspawned*
    and loses its lineage. **Under**-claiming, which is the safe direction for
    a discriminator whose whole job is to stop a receipt saying a child ran
    when none did.

    An earlier version keyed on ``model`` instead, reasoning that the seam fills
    it once it has "got as far as spawning" — and that was wrong in production:
    a ``GatewayMintError`` is neither fatal nor a likely bug, so the seam
    catches it, converts it to a soft ``rc=-1``, and its ``finally`` fills
    ``model`` anyway. No child had started, and the receipt said ``ACCEPTED``.
    The unit test did not catch it because its double raised the mint error
    *out* of the seam, which is not what the seam does — a double more
    convenient than the thing it stands for.
    """
    return lineage if spawn_out.get("spawned") else None


def _refusal_for_spawn(spawn_out: dict[str, object]) -> RejectionReason:
    """Why a spawn that never ran did not run, in the receipt's vocabulary.

    The seam collapses a routing-policy refusal and a transport failure onto
    the same soft ``rc=-1``, so without the reason it left behind, both would
    be filed as ``ROUTE_UNAVAILABLE`` — which tells an operator the request was
    fine and to retry once whatever is missing is supplied. For an inadmissible
    route that is wrong: the retry will never succeed, and the thing to edit is
    the policy.
    """
    # Classified on the REASON alone, deliberately. A previous draft short-
    # circuited on ``refused_outcome == held`` first, reasoning that a hold is
    # retryable whatever its reason — and that silently reversed the one code
    # this canary is named after: ``RoutingAction.on_unavailable`` defaults to
    # HOLD, so the ordinary ``provider_lock=zai-harness`` refusal arrives as
    # HELD with ``literal-family-unsatisfiable``, and the guard turned it back
    # into a retryable ``ROUTE_UNAVAILABLE``. The reason is the durable fact
    # about the request; the outcome is a per-policy *dial* over what to do
    # when a lane is unavailable, and it is the wrong axis to classify on.
    reason = str(spawn_out.get("refused", "") or "")
    if reason in _INADMISSIBLE_ROUTE_REASONS:
        return RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
    return RejectionReason.ROUTE_UNAVAILABLE


def _unresolved_decision(route_policy_revision: str) -> PlanRouteDecision:
    """A decision record for a refusal taken before any tier was resolved.

    It carries the route-policy revision because a receipt joins on that, and
    nothing else: inventing a rule, a source or a served model for a resolution
    that never ran would put fiction into the one record the canary's evidence
    is read from.
    """
    from plan_broker import (
        PLAN_TIER_CATALOG_REVISION,
        PlanRouteDecision,
        PlanRouteRule,
        PlanRouteSource,
    )

    return PlanRouteDecision(
        decision_id="",
        outcome=PlanRouteOutcome.REJECTED,
        rule=PlanRouteRule.NONE_MATCHED,
        source=PlanRouteSource.NONE,
        reason=PlanRouteReason.NONE,
        catalog_revision=PLAN_TIER_CATALOG_REVISION,
        route_policy_revision=route_policy_revision,
        worker_role="",
        phase="",
        requirement_kind="",
        requirement_value="",
    )


def _digest(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:64]}"


def _estimate_cost(model: str, usage: object) -> float:
    """This child's spend, from the token counts the seam actually reported.

    Zero when the backend reported none, and zero for an unpriced model —
    never a guess dressed as a measurement. ADR-0137 B5's bar reads *"100% of
    accepted workers carry lineage, cost and effective-route receipts"*, and a
    fabricated cost would satisfy the letter of that while destroying it.
    """
    if not isinstance(usage, dict):
        return 0.0
    from model_pricing import load_pricing

    cost = load_pricing().estimate_cost(
        model,
        int(usage.get("input_tokens", 0) or 0),
        int(usage.get("output_tokens", 0) or 0),
        int(usage.get("cache_creation_input_tokens", 0) or 0),
        int(usage.get("cache_read_input_tokens", 0) or 0),
    )
    return round(cost, 6) if cost else 0.0


def _issue_goal(task: Task) -> str:
    body = (getattr(task, "body", "") or "").strip()
    goal = f"{task.title}\n\n{body}".strip() or task.title or f"issue {task.id}"
    return goal[:8000]
