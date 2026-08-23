"""The Implement canary's actuator: one admitted request, one fenced child (#11542).

:mod:`plan_worker_runner` is this module's sibling and its shape is deliberately
copied: one admitted request becomes exactly one child process, each child gets
its own spawn id, its own short-lived gateway key, its own route decision, its
own wall-clock budget and its own :class:`driver_contracts.WorkerReceipt`
carrying parent-driver lineage. What is new here is the word the phase is named
after.

**Fenced means prevented, not expected.** A write-capable worker at IMPLEMENT
is briefed against one worktree state — one branch, one base SHA, one HEAD, one
diff digest — measured *before* it starts and re-measured *after* it returns. If
any of the four moved, or if the driver's own epoch or phase attempt moved, or
if the live label moved, the result is refused with a deterministic code and its
artifact is **discarded**. It is not logged as a warning and kept; it does not
reach ``prior_receipts``; the next director turn never sees it. A late or
superseded worker is provably rejected rather than merely ignored, which is the
difference between a fence and a convention.

**Exactly one writer.** ``implement_broker.WriterLeaseRegistry`` holds the
issue's worktree, taken before the spawn and released in a ``finally`` — so a
timeout, a cancellation, a stale digest, a branch mismatch and a stop all
revoke authority on the way out rather than leaving it held by a process that
is already dead. Read-only evidence roles never take it and so may fan out;
write-capable ones serialize behind it, which is the whole of #11542's third
acceptance criterion.

**The worker adds work, not authority.** ADR-0137's P3 line carried forward
unchanged: the deterministic ``ImplementPhase`` still runs, still gates, still
commits, and still does not push. A brokered implementer or debugger produces a
bounded correction proposal beside it, as an artifact and a receipt. Nothing
here writes a file into the worktree, moves a label, or touches convergence
state — pinned by ``tests/architecture/test_director_no_authority.py`` — so
"existing implementation output markers, quality gates, commit rules, and the
no-push rule remain unchanged" is a property of what this module cannot reach.
Letting a brokered diff *become* the commit needs the independent review
#11543 owns.

**Two subprocess paths, one seam each.** The child goes through
``runner_utils.run_lightweight_agent``, which this module names lexically, so it
carries a ``SANDBOX_SEAMS`` row. The worktree measurement goes through the
**injected** ``SubprocessRunner.run_simple`` — the same posture
``director_turn_runner`` holds, and the same pure-engine/one-subprocess-seam
split ``workspace_gc_loop`` uses for its landed proof: the parsing and the
digesting are pure in :mod:`implement_broker`, and exactly one method here runs
a command.

Air-gap: the seam kind is ``config_disable`` because the sandbox pins
``execution_runtime=stage_subprocess``, under which nothing constructs a
director and therefore nothing constructs this runner; the sandbox additionally
clears ``fable_implement_canary_repo``, so even a director that did exist would
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
from implement_broker import (
    FENCE_REJECTIONS,
    FenceBreach,
    WorktreeState,
    check_worker_fence,
    needs_writer_lease,
    resolve_implement_model,
    worktree_probes,
    worktree_state_from_reads,
)
from plan_broker import (
    PLAN_TIER_CATALOG_REVISION,
    PlanRouteDecision,
    PlanRouteOutcome,
    PlanRouteReason,
    PlanRouteRule,
    PlanRouteSource,
)
from runner_utils import run_lightweight_agent

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from agent_cli import AgentTool
    from config import HydraFlowConfig
    from driver_contracts import DriverLease, DriverPhase, WorkerDispatchRequest
    from execution import SimpleResult, SubprocessRunner
    from gateway_mint_client import GatewayControlClient
    from implement_broker import WriterLeaseRegistry
    from models import Task

logger = logging.getLogger("implement_worker_runner")

MAX_ARTIFACT_CHARS = 20000
"""How much of a child's reply is retained. A receipt is evidence, not a store."""

MAX_DIFF_CHARS = 24000
"""How much of the worktree diff a worker is shown.

Bounded for the reason the capsule is: a worker whose context is a declared,
bounded payload is one whose output can be judged against what it was given.
The **digest** is taken over the whole diff, never over this truncated view, so
a change beyond the cut still moves the fence — which is why the excerpt and the
state are two fields of one measurement rather than one field doing both jobs.
"""

MAX_DISPATCHED_KEYS = 2000
"""How many spent idempotency keys the replay fence remembers. Bounded because
this object lives for the whole run and a boundary key already carries the
driver epoch and the phase attempt."""

MEASURE_TIMEOUT_SECONDS = 30.0
"""Per-probe budget for a git read. Local, no network; the tier
``pattern_async_communicate_timeout_tiers`` gives a plain git query."""

#: Which refusal each unsatisfiable tier resolution reports on the receipt.
#: A table rather than branches, so a new :class:`plan_broker.PlanRouteReason`
#: fails loudly here rather than defaulting to a plausible code.
_REFUSAL_CODES: dict[PlanRouteReason, RejectionReason] = {
    PlanRouteReason.PHASE_NOT_IMPLEMENT: RejectionReason.ROLE_PHASE_FORBIDDEN,
    PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_IMPLEMENT: (
        RejectionReason.ROLE_PHASE_FORBIDDEN
    ),
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


class ImplementWorkerSpawn(Protocol):
    """The one-shot spawn seam, injectable so a unit test needs no gateway.

    Spelled out rather than ``**kwargs`` so the seam has a real contract: a
    double that quietly dropped ``issue_labels`` or ``spawn_out`` would
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


async def _spawn_implement_worker(
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

    ``source`` is the worker's catalogued role, and that is load-bearing rather
    than cosmetic: ``run_lightweight_agent`` runs the governed route resolver
    with ``principal_id=source``, and ``routing_policy.canonical_worker_role``
    matches a :class:`driver_contracts.WorkerRole` value exactly. A brokered
    writer therefore mints a route-**bound** v2 key attributable to its own
    worker account wherever the gateway enforcement canary is armed, through
    the same path as every other governed spawn. Passing a loop-shaped source
    here would silently mint unbound.
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
class WorktreeMeasurement:
    """One reading of an issue worktree: the fence tokens and what to show.

    Two fields because they answer two questions and must not be confused. The
    *state* is what :func:`implement_broker.check_worker_fence` compares, and it
    is a digest so the comparison is total and cheap. The *excerpt* is what a
    worker is shown, and it is truncated so the prompt is bounded. Deriving the
    fence from the excerpt would mean a change past the truncation point moved
    nothing — a fence with a blind spot exactly where a long diff is.
    """

    state: WorktreeState
    diff_excerpt: str = ""

    @classmethod
    def unmeasured(cls) -> WorktreeMeasurement:
        """A measurement that says out loud that nothing could be read."""
        return cls(state=WorktreeState.unmeasured(), diff_excerpt="")


@dataclass(frozen=True, slots=True)
class ImplementWorkerArtifact:
    """One child's output, kept beside its receipt rather than inside it.

    Only ever appended for a child whose fence held on the way out — a
    superseded worker's text is discarded rather than stored with a caveat,
    because a caveat is something a later reader has to remember to check.
    """

    request_id: str
    role: str
    served_model: str
    head_sha: str
    text: str


class ImplementWorkerRunner:
    """Dispatches admitted IMPLEMENT requests as fenced children and mints receipts.

    Constructed only at the ``build_services`` composition root and only when
    the Implement canary is armed for this repository, so an operator who has
    not named one has no such object in their process — the object-graph
    standard #11535, #11537 and #11541 each held themselves to.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        route_policy_revision: str,
        runner: SubprocessRunner,
        leases: WriterLeaseRegistry,
        base_ref: str,
        spawn: ImplementWorkerSpawn | None = None,
        gateway_client: GatewayControlClient | None = None,
    ) -> None:
        self._config = config
        self._route_policy_revision = route_policy_revision
        self._gateway_client = gateway_client
        # Injected from the composition root and REQUIRED, never built inside a
        # method: that is what lets the sandbox substitute a
        # ``FakeSubprocessRunner``, and what #11602/#11615 cost this repo twice
        # in one night by getting backwards. It carries BOTH subprocess paths
        # here — the git measurement and (through the seam) the child.
        self._runner = runner
        self._leases = leases
        self._base_ref = base_ref
        self._spawn: ImplementWorkerSpawn = spawn or _spawn_implement_worker
        self._dispatched_keys: set[str] = set()
        self._dispatched_order: deque[str] = deque()
        self.decisions: list[PlanRouteDecision] = []
        self.artifacts: list[ImplementWorkerArtifact] = []
        self.revocations: list[tuple[int, str]] = []
        """Every writer lease taken away from a live holder, as (issue, holder).

        Recorded rather than merely performed because ADR-0137 B5's bar counts
        ownership events, and a revocation nobody wrote down is indistinguishable
        from a lease that was never held.
        """

    @property
    def spawn(self) -> ImplementWorkerSpawn:
        """What actually starts a child. Read-only, and exposed so a test can
        assert the default IS the real seam — an injection point nobody checks
        is a seam in name only."""
        return self._spawn

    # -- the fence's two measurements --------------------------------------

    async def measure(self, issue_number: int) -> WorktreeMeasurement:
        """Read this issue's worktree, or say out loud that it could not be read.

        Every probe runs against the issue's own worktree directory, which is
        derived rather than passed: ``config.workspace_path_for_issue`` is the
        single definition of where an issue's tree lives, and a second one here
        would be a fence measuring a different tree from the one a worker
        writes to.

        All four tokens come from one pass, because a base read taken a second
        after a HEAD read describes a tree that never existed and a fence built
        from two moments cannot say which of them a worker saw.
        """
        path = self._config.workspace_path_for_issue(issue_number)
        if not path.is_dir():
            # No worktree, no fence. Refusing here costs nothing; discovering it
            # after a spawn costs a worker whose result could never be admitted.
            return WorktreeMeasurement.unmeasured()
        reads: dict[str, str] = {}
        for token, argv in worktree_probes(self._base_ref):
            answer = await self._git(path, argv)
            if answer is None:
                return WorktreeMeasurement.unmeasured()
            reads[token] = answer
        return WorktreeMeasurement(
            state=worktree_state_from_reads(reads),
            diff_excerpt=reads["diff"][:MAX_DIFF_CHARS],
        )

    async def _git(self, cwd: Path, argv: Sequence[str]) -> str | None:
        """One git read through the injected runner. ``None`` when it did not answer.

        Failure is a value rather than an exception because the caller's job is
        to decide that the fence is unarmed, and an exception here would travel
        up into an observer that must not be able to fail the boundary it
        watches.
        """
        try:
            result = await self._runner.run_simple(
                ["git", "-C", str(cwd), *argv], timeout=MEASURE_TIMEOUT_SECONDS
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "implement_worker_runner: worktree probe %s failed: %s", argv[0], exc
            )
            return None
        if result.returncode != 0:
            logger.info(
                "implement_worker_runner: worktree probe %s returned %d",
                argv[0],
                result.returncode,
            )
            return None
        return result.stdout or ""

    # -- one batch ----------------------------------------------------------

    async def dispatch(
        self,
        requests: Sequence[WorkerDispatchRequest],
        *,
        task: Task,
        lease: DriverLease,
        phase: DriverPhase,
        measured: WorktreeMeasurement,
        fence: Callable[[], RejectionReason | None],
        driver_facts: Callable[[], tuple[str, int, int, str]],
    ) -> tuple[WorkerReceipt, ...]:
        """Run every admitted request as its own fenced child, one at a time.

        Serial rather than concurrent, and for two reasons rather than one.
        ``plan_worker_runner``'s reason still applies — ``asyncio.gather`` would
        start every child before any of them could observe a stop — and this
        phase adds the stronger one: the writer lease admits one holder, so two
        write-capable children started together would deadlock the second
        against the first for the length of the batch. Running them in order is
        what "run sequentially in one issue worktree" means.

        The batch budget bounds the **batch**, exactly as the Plan canary's
        does, because this is awaited inside the allocator tick.
        """
        deadline = time.monotonic() + float(
            self._config.fable_implement_worker_timeout_seconds
        )
        receipts: list[WorkerReceipt] = []
        for request in requests:
            receipts.append(
                await self._dispatch_one(
                    request, task, lease, phase, measured, fence, driver_facts, deadline
                )
            )
        return tuple(receipts)

    def refuse(
        self, requests: Sequence[WorkerDispatchRequest], reason: RejectionReason
    ) -> tuple[WorkerReceipt, ...]:
        """Mint a refusal receipt per request without resolving or spawning.

        For refusals decided *outside* this module — an unmeasurable worktree
        and a hibernating driver, both of which the director sees first. Minting
        them here keeps "a refusal names no served model" a property of one
        function rather than of every caller remembering it.
        """
        blank = _unresolved_decision(self._route_policy_revision)
        return tuple(_refusal(request, reason, blank) for request in requests)

    def revoke(self, issue_number: int, reason: RejectionReason) -> None:
        """Take this issue's writer lease away from whoever holds it.

        Called by the director when a boundary hibernates or the factory stops:
        the ADR-0137 C6 rule that a non-working driver releases capacity,
        applied to authority. A worker whose lease is revoked mid-run still
        returns, and its result still meets :func:`check_worker_fence` — which
        is why revoking is safe to do without waiting for it.
        """
        displaced = self._leases.revoke(issue_number)
        if displaced is None:
            return
        self.revocations.append((issue_number, displaced))
        logger.info(
            "implement_worker_runner: revoked #%d's writer lease from %s (%s)",
            issue_number,
            displaced,
            reason.value,
        )

    # -- one child ----------------------------------------------------------

    async def _dispatch_one(
        self,
        request: WorkerDispatchRequest,
        task: Task,
        lease: DriverLease,
        phase: DriverPhase,
        measured: WorktreeMeasurement,
        fence: Callable[[], RejectionReason | None],
        driver_facts: Callable[[], tuple[str, int, int, str]],
        deadline: float,
    ) -> WorkerReceipt:
        decision = resolve_implement_model(
            request,
            phase=phase,
            route_policy_revision=self._route_policy_revision,
        )
        self.decisions.append(decision)
        if decision.outcome is not PlanRouteOutcome.SELECTED:
            logger.info(
                "implement_worker_runner: #%d %s refused before spawn (%s)",
                task.id,
                request.worker_role.value,
                decision.reason.value,
            )
            return _refusal(request, _REFUSAL_CODES[decision.reason], decision)

        if not measured.state.measured:
            # The fence could not be armed. Refused before the key is claimed,
            # so the request stays replayable once the worktree is readable.
            return _refusal(request, RejectionReason.WORKTREE_UNMEASURED, decision)

        # The fence and the idempotency claim are one step, with no ``await``
        # between them. Anything else leaves a window in which two admissions of
        # the same key both observe it unclaimed.
        blocked = fence()
        if blocked is None and request.idempotency_key in self._dispatched_keys:
            blocked = RejectionReason.DUPLICATE_IDEMPOTENCY_KEY
        if blocked is not None:
            return _refusal(request, blocked, decision)

        budget = self._remaining_budget(deadline)
        if budget <= 0.0:
            return _refusal(
                request,
                RejectionReason.WORKER_TIMEOUT,
                decision,
                status=ReceiptStatus.EXPIRED,
            )

        writer = needs_writer_lease(request.worker_role)
        if writer and not self._leases.acquire(task.id, request.request_id):
            # Another request already owns this worktree. Refused rather than
            # queued: the batch is serial, so a lease still held here means a
            # worker from an earlier boundary has not finished, and waiting
            # would block the allocator tick behind it.
            return _refusal(request, RejectionReason.WRITER_LEASE_HELD, decision)

        self._claim(request.idempotency_key)
        try:
            return await self._run_child(
                request, task, lease, decision, budget, measured, driver_facts
            )
        finally:
            # Timeout, cancellation, a raised bug, a stale digest and a clean
            # run all leave through here. Authority ends when the worker does.
            if writer:
                self._leases.release(task.id, request.request_id)

    async def _run_child(
        self,
        request: WorkerDispatchRequest,
        task: Task,
        lease: DriverLease,
        decision: PlanRouteDecision,
        budget: float,
        measured: WorktreeMeasurement,
        driver_facts: Callable[[], tuple[str, int, int, str]],
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
                prompt=build_implement_worker_prompt(
                    role=request.worker_role.value,
                    task_contract=request.task_contract,
                    issue_goal=_issue_goal(task),
                    issue_number=task.id,
                    worktree=measured,
                ),
                source=request.worker_role.value,
                timeout=budget,
                issue_number=task.id,
                issue_labels=tuple(task.tags or ()),
                # Pinned, not dialled: the key, the route decision and the
                # ledger row are all gateway properties.
                provider="gateway",
                gateway_client=self._gateway_client,
                spawn_out=spawn_out,
            )
        except TimeoutError:
            # The child outlived even the seam's own deadline; its process group
            # has already been reaped by ``run_simple``. The ``finally`` above
            # takes its authority back on the way out.
            return _refusal(
                request,
                RejectionReason.WORKER_TIMEOUT,
                decision,
                status=ReceiptStatus.EXPIRED,
            )
        except Exception as exc:
            # A burnt credit balance is factory-wide and must not become a
            # worker refusal (dark-factory 2.2); everything else is this child's
            # failure and becomes a receipt.
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "implement_worker_runner: #%d %s could not be dispatched: %s",
                task.id,
                request.worker_role.value,
                exc,
            )
            return _refusal(request, RejectionReason.ROUTE_UNAVAILABLE, decision)

        served = str(spawn_out.get("model", "") or "")
        if not served:
            # The seam returned before it spawned anything — a CH-6 block or an
            # enforcement refusal. No inference happened, so there is nothing to
            # bill and no served model to record.
            return _refusal(request, RejectionReason.ROUTE_UNAVAILABLE, decision)
        if not request.model_requirement.satisfied_by(served):
            logger.warning(
                "implement_worker_runner: #%d %s asked for %s and was served %r; "
                "refusing the receipt rather than recording the substitution",
                task.id,
                request.worker_role.value,
                request.model_requirement.value,
                served,
            )
            return _refusal(
                request, RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE, decision
            )

        breach = await self._fence_on_the_way_out(
            task, lease, measured.state, driver_facts
        )
        if breach is not FenceBreach.NONE:
            logger.info(
                "implement_worker_runner: #%d %s came back to a moved slice (%s); "
                "its result is rejected, not merged",
                task.id,
                request.worker_role.value,
                breach.value,
            )
            # SUPERSEDED, not REJECTED: the worker ran, and its receipt is still
            # evidence that it did. The artifact is discarded — a superseded
            # answer describes a tree that no longer exists, and keeping it
            # would feed the next director turn a fact about the past.
            return _refusal(
                request,
                FENCE_REJECTIONS[breach],
                decision,
                status=ReceiptStatus.SUPERSEDED,
            )

        text = (result.stdout or "")[:MAX_ARTIFACT_CHARS]
        self.artifacts.append(
            ImplementWorkerArtifact(
                request_id=request.request_id,
                role=request.worker_role.value,
                served_model=served,
                head_sha=measured.state.head_sha,
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

    async def _fence_on_the_way_out(
        self,
        task: Task,
        lease: DriverLease,
        minted: WorktreeState,
        driver_facts: Callable[[], tuple[str, int, int, str]],
    ) -> FenceBreach:
        """Re-measure and re-read, then judge. The result half of the fence.

        The driver facts are read through a callable rather than captured at
        dispatch time for the same reason the canary's dial is: they are
        precisely the values that can move while a child runs, and a fence that
        compared a lease against a copy of itself would verify unconditionally.
        """
        driver_id, epoch, phase_attempt, live_label = driver_facts()
        return check_worker_fence(
            minted=minted,
            observed=(await self.measure(task.id)).state,
            lease=lease,
            driver_id=driver_id,
            driver_epoch=epoch,
            driver_phase_attempt=phase_attempt,
            live_stage_label=live_label,
        )

    def _remaining_budget(self, deadline: float) -> float:
        """What this batch has left, in seconds, capped by the dial."""
        configured = float(self._config.fable_implement_worker_timeout_seconds)
        return min(configured, deadline - time.monotonic())

    def _claim(self, key: str) -> None:
        """Record an idempotency key as spent, keeping the set bounded."""
        self._dispatched_keys.add(key)
        self._dispatched_order.append(key)
        while len(self._dispatched_order) > MAX_DISPATCHED_KEYS:
            self._dispatched_keys.discard(self._dispatched_order.popleft())


def build_implement_worker_prompt(
    *,
    role: str,
    task_contract: str,
    issue_goal: str,
    issue_number: int,
    worktree: WorktreeMeasurement,
) -> str:
    """The whole of one fenced worker's input, and the whole of its authority.

    The bounded slice is stated to the worker rather than merely enforced
    around it: it is told which branch, which base and which HEAD its answer is
    about, and told that an answer about anything else will be discarded. That
    is not the fence — :func:`check_worker_fence` is — but a worker that knows
    the bound produces fewer answers the fence has to throw away.

    There is no repository access, no credential, no shell and no earlier turn.
    The instruction leads and the variable payload is delimited and last, per
    ADR-0087's long-context placement rule.
    """
    return f"""Propose one bounded correction to a HydraFlow issue branch and return prose.

You are a HydraFlow `{role}` working on issue #{issue_number}. Your entire
assignment is the task contract at the end of this message, and it is about one
exact snapshot of one branch: `{worktree.state.branch}`, based on
`{worktree.state.base_sha}`, at commit `{worktree.state.head_sha}`. Everything you are allowed to know is in the
blocks below; there is nothing else to consult and no earlier turn to remember.

Do the work the task contract asks for. Respond with the proposal itself and
nothing else: prose under Markdown headings, under 900 words, quoting only the
lines you are talking about. Do not wrap the reply in a code fence, do not add a
preamble, and do not explain your process.

Rules:

- Answer the task contract and nothing wider. Your proposal is one input to a
  deterministic implementation phase that owns the commit; a broader answer is
  not a better one, and an off-topic section is discarded.
- You have no shell, no file access, and no ability to commit, push, move a
  label, or merge a pull request. Do not describe using one.
- Your answer is about the snapshot named above and is rejected outright if that
  snapshot has moved by the time you finish. Say what you would change and
  where; do not assume anything you propose has been applied.

Edge cases, and what to do about each:

- If the diff is empty, say so in one line and describe what the contract's
  change would have to touch. An empty snapshot is a real state, not an error.
- If the goal or the diff is missing a fact the contract needs, say exactly
  which fact is absent in one short section and stop. A stated gap is a useful
  answer; a guess presented as a finding is not.
- If the task contract is ambiguous, answer the narrowest reading and say in one
  line which reading you took.
- Otherwise, if you are unsure whether something belongs in the reply, leave it
  out. A short correct proposal is worth more than a long hedged one.

<example>
For the contract "the retry loop double-counts an attempt after a timeout; say
where and what to change", a good reply opens:

## Where

`upload/session.py`, the `except TimeoutError` arm: it increments `attempts`
before re-entering the loop, which increments it again at the top.

## Change

Move the increment to a single site at the top of the loop …
</example>

<task_contract>
{task_contract}
</task_contract>

<issue_goal>
{issue_goal}
</issue_goal>

<worktree_diff branch="{worktree.state.branch}" head="{worktree.state.head_sha}">
{_bounded_diff(worktree)}
</worktree_diff>
"""


def _bounded_diff(worktree: WorktreeMeasurement) -> str:
    """What the worker is shown of the tree, and what it is told about the rest.

    A truncated excerpt is a real hazard rather than a cosmetic one: a worker
    shown the first 24 000 characters of a long diff will reason as though that
    is the whole change unless told otherwise. So the cut is *announced*, and
    the digest of the whole diff is printed beside it — which is also the token
    the fence compares, so a reader of the prompt and a reader of the receipt
    are looking at the same number.
    """
    excerpt = worktree.diff_excerpt
    if not excerpt.strip():
        return f"(no uncommitted or committed change against the base; digest {worktree.state.diff_digest})"
    truncated = len(excerpt) >= MAX_DIFF_CHARS
    note = (
        f"(TRUNCATED at {MAX_DIFF_CHARS} characters; "
        f"whole-diff digest {worktree.state.diff_digest})\n"
        if truncated
        else f"(whole-diff digest {worktree.state.diff_digest})\n"
    )
    return note + excerpt


def _refusal(
    request: WorkerDispatchRequest,
    reason: RejectionReason,
    decision: PlanRouteDecision,
    *,
    status: ReceiptStatus = ReceiptStatus.REJECTED,
) -> WorkerReceipt:
    """A real receipt for a real refusal, naming no served model.

    ``served_model`` is left unset on every refusal path — including the two
    where a model *was* served: a mis-resolved id and a superseded run. Putting
    either in the one field whose validator exists to make a mis-reported model
    a validation error would be the smuggling path rather than the evidence.
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


def _unresolved_decision(route_policy_revision: str) -> PlanRouteDecision:
    """A decision record for a refusal taken before any tier was resolved.

    It carries the route-policy revision because a receipt joins on that, and
    nothing else: inventing a rule, a source or a served model for a resolution
    that never ran would put fiction into the record the canary is read from.
    """
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

    Zero when the backend reported none, and zero for an unpriced model — never
    a guess dressed as a measurement. ADR-0137 B5's bar reads *"100% of accepted
    workers carry lineage, cost and effective-route receipts"*, and a fabricated
    cost would satisfy its letter while destroying it.
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
