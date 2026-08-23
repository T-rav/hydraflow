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
    PlanRouteReason.CAPABILITY_UNMAPPED: (
        RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
    ),
    PlanRouteReason.CONCRETE_MODEL_REQUESTED: (
        RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
    ),
}

#: Routing-policy refusal reasons that mean *the request was inadmissible on
#: this lane* rather than *something operational is missing*. The first maps to
#: MODEL_REQUIREMENT_UNSATISFIABLE — retrying changes nothing and the operator
#: must edit the policy; everything else is ROUTE_UNAVAILABLE, where a caretaker
#: retry is right and the operator should look at the gateway.
_INADMISSIBLE_ROUTE_REASONS = frozenset(
    {
        "literal-family-unsatisfiable",
        "capability-unmapped",
        "model-not-allowed",
        "concrete-model-not-allowed",
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

    Constructed only at the ``build_services`` composition root and only when
    the canary is armed for this repository, so an operator who has not named a
    canary repository has no such object in their process — the same
    object-graph standard #11535 and #11537 held themselves to.
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
            # The seam normally converts its own deadline into a soft rc=-1; a
            # bare TimeoutError means the child outlived even that, and its
            # process group has already been reaped by ``run_simple``.
            return _refusal(
                request,
                RejectionReason.WORKER_TIMEOUT,
                decision,
                status=ReceiptStatus.EXPIRED,
            )
        except Exception as exc:
            # A burnt credit balance is factory-wide and must not be converted
            # into a worker refusal (dark-factory 2.2); everything else is this
            # child's failure and becomes a receipt rather than an exception a
            # shadow-shaped observer would have to carry into the allocator.
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "plan_worker_runner: #%d %s could not be dispatched: %s",
                task.id,
                request.worker_role.value,
                exc,
            )
            return _refusal(request, RejectionReason.ROUTE_UNAVAILABLE, decision)

        requested = str(spawn_out.get("model", "") or "")
        if not requested:
            # The seam returned before it spawned anything — a CH-6 block or an
            # enforcement refusal. No inference happened, so there is no served
            # model to record and nothing to bill.
            return _refusal(request, _refusal_for_spawn(spawn_out), decision)
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
                request, RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE, decision
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
            lineage=WorkerLineage(
                driver_id=lease.driver_id,
                epoch=lease.epoch,
                child_spawn_id=child_spawn_id,
                depth=1,
            ),
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
) -> WorkerReceipt:
    """A real receipt for a real refusal, naming no served model.

    ``served_model`` is left unset on every refusal path — including the one
    where a model *was* served but did not satisfy the requirement. Recording
    it would put a mis-resolved id on a receipt in the one field whose validator
    exists to make that a validation error, which is the smuggling path rather
    than the evidence.
    """
    return WorkerReceipt(
        request_id=request.request_id,
        idempotency_key=request.idempotency_key,
        status=status,
        reason_code=reason,
        worker_role=request.worker_role,
        transport=WorkerTransport.BROKERED,
        requested_model=request.model_requirement,
        route_policy_revision=decision.route_policy_revision,
        output_contract_ok=False,
    )


def _refusal_for_spawn(spawn_out: dict[str, object]) -> RejectionReason:
    """Why a spawn that never ran did not run, in the receipt's vocabulary.

    The seam collapses a routing-policy refusal and a transport failure onto
    the same soft ``rc=-1``, so without the reason it left behind, both would
    be filed as ``ROUTE_UNAVAILABLE`` — which tells an operator to retry and
    look at the gateway. For an inadmissible route that is wrong twice: the
    retry will never succeed, and the thing to edit is the policy.
    """
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
