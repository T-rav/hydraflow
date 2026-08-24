"""The Review canary's actuator: one admitted request, one fresh reviewer (#11543).

:mod:`plan_worker_runner` and :mod:`implement_worker_runner` are this module's
siblings and their shape is deliberately copied: one admitted request becomes
exactly one child process, each child gets its own spawn id, its own short-lived
gateway key, its own route decision, its own share of one batch's wall-clock
budget and its own :class:`driver_contracts.WorkerReceipt` carrying parent-driver
lineage. Three things are new here, and each is one of P5's acceptance criteria
made structural rather than promised.

**The prompt is built from a :class:`review_evidence.ReviewEvidence` and nothing
else.** :func:`build_review_worker_prompt` takes a role and an evidence value —
that is its whole signature, so there is no parameter through which an
implementer's prompt, transcript or reasoning could arrive. This runner never
sees a :class:`models.Task` either: the only description of the issue it can
reach is the canonical one, which is also the only issue identity it holds, so
there is no second source to disagree with the first. ADR-0137's review boundary
says a reviewer *"receives canonical issue/plan/diff/test evidence, never
implementer-private context"*, and the way to make private context unreachable
is to give it no path, not to filter it on the way past.

**It returns a proposal, never a verdict.** A child's reply is parsed into a
:class:`review_authority.ReviewProposal` — which has no verdict field, no merge
instruction, no label and no CI waiver — and :func:`review_authority.adjudicate`
stays the only function in the codebase that produces a
:class:`models.ReviewVerdict`. This module does not import it. A reviewer that
recommends approval while filing a blocking finding is resolved against by the
adjudicator, and nothing here can pre-empt that.

**An unarmed repository dispatches nothing.** Every request is checked against
``review_broker.review_canary_covers`` immediately before its own spawn rather
than once for the batch, so clearing ``fable_review_canary_repo`` between two
children stops the second — the liveness that makes clearing the dial the whole
rollback. The self-review fence is
``review_broker.reviewer_independence_refusal``, called rather than restated:
which roles must be independent is the catalogue's decision (#11673's failure
class), and a second copy of that rule here would go stale the day a role is
added.

Air-gap: the spawn goes through ``runner_utils.run_lightweight_agent``, which
this module names lexically, so it carries a ``SANDBOX_SEAMS`` row. The seam
kind is ``config_disable`` because the sandbox pins
``execution_runtime=stage_subprocess``, under which nothing constructs a
director; the sandbox additionally clears ``fable_review_canary_repo``, so even
a director that did exist would find every boundary outside the canary's bound.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

from adversarial_agents import extract_json
from driver_contracts import (
    ReceiptStatus,
    RejectionReason,
    WorkerLineage,
    WorkerReceipt,
    WorkerTransport,
)
from exception_classify import reraise_on_credit_or_bug
from plan_broker import (
    REFUSAL_CODES,
    PlanRouteOutcome,
    refusal_for_spawn,
)
from review_authority import ReviewFinding, ReviewProposal
from review_broker import (
    resolve_review_model,
    review_canary_covers,
    reviewer_independence_refusal,
)
from runner_utils import run_lightweight_agent
from worker_receipts import (
    artifact_digest,
    estimate_worker_cost,
    unresolved_decision,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from agent_cli import AgentTool
    from config import HydraFlowConfig
    from driver_contracts import DriverLease, DriverPhase, WorkerDispatchRequest
    from execution import SimpleResult, SubprocessRunner
    from gateway_mint_client import GatewayControlClient
    from plan_broker import PlanRouteDecision
    from review_evidence import ReviewEvidence

logger = logging.getLogger("review_worker_runner")

MAX_ARTIFACT_CHARS = 20000
"""How much of a child's reply is retained. A receipt is evidence, not a store."""

MAX_DIFF_CHARS = 24000
"""How much of the change a reviewer is shown.

Bounded for the same reason the Implement canary's excerpt is, and the cut is
*announced* rather than silent: a reviewer shown the first 24 000 characters of
a long diff will judge as though that is the whole change unless told otherwise,
and a partial review presented as a complete one is worse than no review.
"""

MAX_RETAINED_RECORDS = 50
"""How many decisions and artifacts this object keeps. Bounded because it lives
for the whole run; the durable evidence is the receipt (#11657)."""

MAX_DISPATCHED_KEYS = 2000
"""How many spent idempotency keys the replay fence remembers. Bounded because
this object lives for the whole run and a boundary key already carries the
driver epoch and the phase attempt."""

MAX_FINDINGS = 50
"""How many findings one proposal may carry before it is refused outright.

Refused, never **truncated**, and that asymmetry is the point: dropping the
fifty-first finding would be this module hiding a finding to fit a bound, which
is the first thing P5 says a Fable reviewer must not be able to do. A reply
past this bound is treated as an unparseable one — no proposal, and a receipt
that says the output contract failed.
"""

MAX_FINDING_SUMMARY_CHARS = 500
MAX_PROPOSAL_SUMMARY_CHARS = 4000
"""The prose bounds :class:`review_authority.ReviewFinding` and
:class:`review_authority.ReviewProposal` already declare, mirrored here so an
over-long reply is trimmed to fit rather than discarded.

Trimming touches **only prose**. It cannot drop a finding and it cannot flip
``blocking``, so it cannot move a verdict — which is what separates it from the
truncation :data:`MAX_FINDINGS` refuses to do.
"""

#: Re-exported from the module that owns the vocabulary, so three actuators
#: cannot drift on what a refusal means. See ``plan_broker.REFUSAL_CODES``.
_REFUSAL_CODES = REFUSAL_CODES

#: The keys a reviewer's JSON reply may contribute. An ALLOW-LIST, mirroring
#: ``review_evidence.CANONICAL_FIELDS`` and for the same reason: a deny-list of
#: forbidden keys is fail-open the moment somebody invents a new one, and the
#: key an untrusted reviewer would invent is precisely the one nobody listed.
#: Nothing outside this set is read, so nothing outside it can arrive.
_PROPOSAL_KEYS: frozenset[str] = frozenset({"recommended", "summary", "findings"})
_FINDING_KEYS: frozenset[str] = frozenset({"summary", "file", "line", "blocking"})


class ReviewWorkerSpawn(Protocol):
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


async def _spawn_review_worker(
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

    ``source`` is the worker's catalogued role, which is load-bearing rather
    than cosmetic: ``run_lightweight_agent`` runs the governed route resolver
    with ``principal_id=source``, and ``routing_policy.canonical_worker_role``
    matches a :class:`driver_contracts.WorkerRole` value exactly. A brokered
    reviewer therefore mints a route-**bound** key attributable to its own
    worker account wherever the gateway enforcement canary is armed. Passing a
    loop-shaped source here would silently mint unbound.
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
class ReviewWorkerArtifact:
    """One reviewer's output, kept beside its receipt rather than inside it."""

    request_id: str
    role: str
    served_model: str
    model_observed: bool
    """Whether the CLI reported the served id, or it was inferred from the request.

    A weak claim that says so is better evidence than a weak claim that looks
    strong — ADR-0137 B5 reads "effective-route receipts", and one implying an
    observation it never made is worse than one that admits the gap.
    """

    decision_id: str
    head_sha: str
    """The snapshot this review is *about*.

    Carried so a caller can hand it to ``review_authority.adjudicate`` as
    ``evidence_head_sha``: a review of a branch that has since moved is not a
    review of what would merge, and the adjudicator cannot check that against a
    snapshot nobody wrote down.
    """

    proposal: ReviewProposal | None
    """``None`` when the reply could not be parsed into one.

    Absent rather than defaulted. A default proposal would be this module
    inventing a reviewer's opinion, and the safe-looking default — an empty
    ``REQUEST_CHANGES`` — is still a fabricated finding-free judgement that the
    adjudicator would treat as real.
    """

    text: str


class ReviewWorkerRunner:
    """Dispatches admitted REVIEW requests as fresh children and mints receipts.

    Constructed at the ``build_services`` composition root under
    ``execution_runtime=fable_director``, armed or not, and gated only by
    ``review_broker.review_canary_covers``. Unconditional construction is
    #11657's correction inherited rather than relearned: making it conditional
    on the dial reads as a stronger default-off proof and is in fact the bug
    that makes *arming* require a restart while only disarming stays live.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        route_policy_revision: str,
        runner: SubprocessRunner,
        spawn: ReviewWorkerSpawn | None = None,
        gateway_client: GatewayControlClient | None = None,
    ) -> None:
        self._config = config
        self._route_policy_revision = route_policy_revision
        self._gateway_client = gateway_client
        # Injected from the composition root and REQUIRED, never built inside a
        # method: that is what lets the sandbox substitute a
        # ``FakeSubprocessRunner``, and what #11602/#11615 cost this repo twice
        # in one night by getting backwards.
        self._runner = runner
        self._spawn: ReviewWorkerSpawn = spawn or _spawn_review_worker
        self._dispatched_keys: set[str] = set()
        self._dispatched_order: deque[str] = deque()
        self.decisions: deque[PlanRouteDecision] = deque(maxlen=MAX_RETAINED_RECORDS)
        self.artifacts: deque[ReviewWorkerArtifact] = deque(maxlen=MAX_RETAINED_RECORDS)
        self.last_decision_ids: dict[str, str] = {}
        """This batch's ``request_id -> decision_id``, for the receipt join."""
        self.last_proposals: dict[str, ReviewProposal] = {}
        """This batch's ``request_id -> proposal``, for the adjudicator's input.

        Batch-local, so it is bounded by the batch rather than by the run, and
        it holds **only** what a reviewer actually proposed: a request that was
        refused, timed out or replied unparseably has no entry here at all,
        rather than an entry a caller could mistake for an opinion.
        """

    @property
    def spawn(self) -> ReviewWorkerSpawn:
        """What actually starts a child. Read-only, and exposed so a test can
        assert the default IS the real seam — an injection point nobody checks
        is a seam in name only."""
        return self._spawn

    async def dispatch(
        self,
        requests: Sequence[WorkerDispatchRequest],
        *,
        evidence: ReviewEvidence,
        issue_labels: Sequence[str],
        lease: DriverLease,
        phase: DriverPhase,
        fence: Callable[[], RejectionReason | None],
        implementer_spawn_ids: Iterable[str] = (),
    ) -> tuple[WorkerReceipt, ...]:
        """Run every admitted request as its own fresh child. One receipt each.

        Serial rather than concurrent, for ``plan_worker_runner``'s reason:
        ``asyncio.gather`` would start every child before any of them could
        observe a stop, and the fence is re-evaluated immediately before each
        spawn precisely so a stop arriving during the first stops the second.

        The batch budget bounds the **batch**, because this is awaited inside
        the allocator tick: the dial is exactly how long one armed REVIEW
        boundary may delay every other driver.

        *implementer_spawn_ids* is materialised **once**, here. Left as the
        iterable it is declared to be, a generator would be drained by the first
        request and every request after it would compare against an empty set —
        a self-review fence that stops the first reviewer and waves the rest
        through, green in a one-request test.
        """
        implementers = frozenset(implementer_spawn_ids)
        deadline = time.monotonic() + float(
            self._config.fable_review_worker_timeout_seconds
        )
        self.last_decision_ids = {}
        self.last_proposals = {}
        receipts: list[WorkerReceipt] = []
        for request in requests:
            receipts.append(
                await self._dispatch_one(
                    request,
                    evidence=evidence,
                    issue_labels=issue_labels,
                    lease=lease,
                    phase=phase,
                    fence=fence,
                    implementers=implementers,
                    deadline=deadline,
                )
            )
        return tuple(receipts)

    def refuse(
        self, requests: Sequence[WorkerDispatchRequest], reason: RejectionReason
    ) -> tuple[WorkerReceipt, ...]:
        """Mint a refusal receipt per request without resolving or spawning.

        For refusals decided *outside* this module. Minting them here keeps "a
        refusal names no served model" a property of one function rather than of
        every caller remembering it, and resets both joins so a blank decision
        produces a blank join rather than inheriting the previous batch's ids
        (#11657).
        """
        blank = unresolved_decision(self._route_policy_revision)
        self.last_decision_ids = dict.fromkeys(
            (request.request_id for request in requests), ""
        )
        self.last_proposals = {}
        return tuple(_refusal(request, reason, blank) for request in requests)

    # -- one child ----------------------------------------------------------

    async def _dispatch_one(
        self,
        request: WorkerDispatchRequest,
        *,
        evidence: ReviewEvidence,
        issue_labels: Sequence[str],
        lease: DriverLease,
        phase: DriverPhase,
        fence: Callable[[], RejectionReason | None],
        implementers: frozenset[str],
        deadline: float,
    ) -> WorkerReceipt:
        blank = unresolved_decision(self._route_policy_revision)

        # 1. The canary's bound, read live and per request. An unarmed
        #    repository dispatches nothing, and a dial cleared between two
        #    children of one batch stops the second.
        if not review_canary_covers(self._config, phase=phase):
            self.last_decision_ids[request.request_id] = ""
            logger.info(
                "review_worker_runner: #%d %s is outside the review canary's bound",
                evidence.issue_number,
                request.worker_role.value,
            )
            return _refusal(request, RejectionReason.ROLE_PHASE_FORBIDDEN, blank)

        # 2. Independence, asked of the module that owns the rule. Before the
        #    tier is resolved, because no route can make a self-review
        #    admissible and a decision record for a request that could never be
        #    dispatched would be a fiction in the canary's evidence.
        self_review = reviewer_independence_refusal(
            role=request.worker_role,
            requesting_spawn_id=request.requesting_spawn_id,
            implementer_spawn_ids=implementers,
        )
        if self_review is not None:
            self.last_decision_ids[request.request_id] = ""
            logger.info(
                "review_worker_runner: #%d %s would review its own work (spawn %s)",
                evidence.issue_number,
                request.worker_role.value,
                request.requesting_spawn_id,
            )
            return _refusal(request, self_review, blank)

        decision = resolve_review_model(
            request,
            phase=phase,
            route_policy_revision=self._route_policy_revision,
        )
        self.decisions.append(decision)
        self.last_decision_ids[request.request_id] = decision.decision_id
        if decision.outcome is not PlanRouteOutcome.SELECTED:
            logger.info(
                "review_worker_runner: #%d %s refused before spawn (%s)",
                evidence.issue_number,
                request.worker_role.value,
                decision.reason.value,
            )
            return _refusal(request, _REFUSAL_CODES[decision.reason], decision)

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
            # The batch spent its whole budget on earlier children. Refused
            # rather than started with no time to run, and *before* the key is
            # claimed — a request that never ran must stay replayable.
            return _refusal(
                request,
                RejectionReason.WORKER_TIMEOUT,
                decision,
                status=ReceiptStatus.EXPIRED,
            )
        self._claim(request.idempotency_key)

        return await self._run_child(
            request,
            evidence=evidence,
            issue_labels=issue_labels,
            lease=lease,
            decision=decision,
            budget=budget,
        )

    async def _run_child(
        self,
        request: WorkerDispatchRequest,
        *,
        evidence: ReviewEvidence,
        issue_labels: Sequence[str],
        lease: DriverLease,
        decision: PlanRouteDecision,
        budget: float,
    ) -> WorkerReceipt:
        lineage = WorkerLineage(
            driver_id=lease.driver_id,
            epoch=lease.epoch,
            child_spawn_id=uuid.uuid4().hex,
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
                # The evidence and the role are the WHOLE of a reviewer's
                # input. Nothing about the request, the lease or the driver is
                # rendered: a task contract is written by a director that has
                # read the implementer's receipts, so it is a path for exactly
                # the context this boundary exists to withhold.
                prompt=build_review_worker_prompt(
                    role=request.worker_role.value,
                    evidence=evidence,
                ),
                source=request.worker_role.value,
                timeout=budget,
                issue_number=evidence.issue_number,
                issue_labels=issue_labels,
                # Pinned, not dialled: the key, the route decision and the
                # ledger row are all gateway properties.
                provider="gateway",
                gateway_client=self._gateway_client,
                spawn_out=spawn_out,
            )
        except TimeoutError:
            # A deadline that escaped the seam rather than one it handled: the
            # seam converts its OWN timeout into ``spawn_out["timed_out"]`` and
            # a soft rc=-1, which lands below. So this fires for the work
            # *around* the spawn — the CH-6 gate, the route-shadow and
            # enforcement threads, a Docker socket (``socket.timeout`` IS
            # ``TimeoutError``) before a child exists, or the seam's outer
            # ``finally`` after one did.
            return _refusal(
                request,
                RejectionReason.WORKER_TIMEOUT,
                decision,
                status=ReceiptStatus.EXPIRED,
                lineage=_child_lineage(spawn_out, lineage),
            )
        except Exception as exc:
            # A burnt credit balance is factory-wide and must not become a
            # worker refusal (dark-factory 2.2); everything else is this child's
            # failure and becomes a receipt rather than an exception the
            # allocator would have to carry.
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "review_worker_runner: #%d %s could not be dispatched: %s",
                evidence.issue_number,
                request.worker_role.value,
                exc,
            )
            return _refusal(request, RejectionReason.ROUTE_UNAVAILABLE, decision)

        refusal = self._refusal_after_spawn(request, decision, lineage, spawn_out)
        if refusal is not None:
            return refusal

        observed = str(spawn_out.get("served_model", "") or "")
        served = observed or str(spawn_out.get("model", "") or "")
        text = (result.stdout or "")[:MAX_ARTIFACT_CHARS]
        proposal = parse_review_proposal(text)
        if proposal is None:
            logger.info(
                "review_worker_runner: #%d %s returned no parseable proposal; "
                "its receipt records a failed output contract rather than a verdict",
                evidence.issue_number,
                request.worker_role.value,
            )
        else:
            self.last_proposals[request.request_id] = proposal
        self.artifacts.append(
            ReviewWorkerArtifact(
                request_id=request.request_id,
                role=request.worker_role.value,
                served_model=served,
                model_observed=bool(observed),
                decision_id=decision.decision_id,
                head_sha=evidence.head_sha,
                proposal=proposal,
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
            artifact_digest=artifact_digest(text),
            # A reviewer's output contract is a PROPOSAL, not merely non-empty
            # prose. A reply nobody could parse produced no opinion, and a
            # receipt claiming a satisfied contract for one would be the
            # canary's own evidence overstating what it got.
            output_contract_ok=result.returncode == 0 and proposal is not None,
            started_at=started,
            finished_at=datetime.now(UTC),
            usd_cost=estimate_worker_cost(served, spawn_out.get("usage")),
        )

    def _refusal_after_spawn(
        self,
        request: WorkerDispatchRequest,
        decision: PlanRouteDecision,
        lineage: WorkerLineage,
        spawn_out: dict[str, object],
    ) -> WorkerReceipt | None:
        """Every way a spawn that returned still produced nothing usable.

        The three #11657 found the Plan actuator getting wrong, read as one
        table rather than as three arms buried in a longer method.
        """
        if not spawn_out.get("spawned"):
            # The seam returned without starting a process: a CH-6 block, an
            # enforcement refusal, a caught mint error, or a runner that could
            # not start anything. Which of those it was decides whether a retry
            # can ever work, so it is classified by the module that owns the
            # routing vocabulary rather than collapsed onto ROUTE_UNAVAILABLE.
            refusal = refusal_for_spawn(spawn_out)
            logger.info(
                "review_worker_runner: %s never spawned: %s/%s -> %s",
                request.worker_role.value,
                spawn_out.get("refused_outcome") or "no-decision",
                spawn_out.get("refused") or "no-reason",
                refusal.value,
            )
            return _refusal(request, refusal, decision)
        if spawn_out.get("timed_out"):
            # A deadline, not a bad reply. ``run_lightweight_agent`` converts
            # its own timeout into a soft rc=-1 and returns, so without this
            # signal a timed-out reviewer would be recorded ACCEPTED with an
            # unusable artifact (#11657).
            #
            # The lineage is passed **directly**, not through
            # :func:`_child_lineage`: the clause above already returned for
            # everything unspawned, so asking again here could only ever answer
            # yes. The siblings ask anyway, and a guard whose answer is fixed by
            # its caller is a guard no test can kill — the shape #11541's
            # mutation testing had to delete from this codebase once already.
            return _refusal(
                request,
                RejectionReason.WORKER_TIMEOUT,
                decision,
                status=ReceiptStatus.EXPIRED,
                lineage=lineage,
            )
        observed = str(spawn_out.get("served_model", "") or "")
        served = observed or str(spawn_out.get("model", "") or "")
        if not request.model_requirement.satisfied_by(served):
            logger.warning(
                "review_worker_runner: %s asked for %s and was served %r; refusing "
                "the receipt rather than recording the substitution",
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
        return None

    def _remaining_budget(self, deadline: float) -> float:
        """What this batch has left, in seconds, capped by the dial."""
        configured = float(self._config.fable_review_worker_timeout_seconds)
        return min(configured, deadline - time.monotonic())

    def _claim(self, key: str) -> None:
        """Record an idempotency key as spent, keeping the set bounded."""
        self._dispatched_keys.add(key)
        self._dispatched_order.append(key)
        while len(self._dispatched_order) > MAX_DISPATCHED_KEYS:
            self._dispatched_keys.discard(self._dispatched_order.popleft())


_OUTPUT_SCHEMA = """{
  "recommended": "approve" | "comment" | "request-changes",
  "summary": "one paragraph, under 200 words, on what this change does and how it reads",
  "findings": [
    {
      "summary": "one sentence naming the defect",
      "file": "path/from/the/diff.py",
      "line": 42,
      "blocking": true
    }
  ]
}"""


def build_review_worker_prompt(*, role: str, evidence: ReviewEvidence) -> str:
    """The whole of one fresh reviewer's input, and the whole of its authority.

    **Two parameters, and that is the guarantee.** There is no argument here for
    a task contract, a director rationale, a prior receipt or an implementer's
    transcript, so none of them can reach a reviewer through this function — the
    same construction ``review_evidence.CANONICAL_FIELDS`` uses one layer down.
    Filtering a wider payload would be the fail-open shape that module's
    docstring rejects: the field nobody thought to strip is the one that leaks.

    The bounded slice is stated to the worker rather than only enforced around
    it: it is told which branch, which base and which HEAD its review is about,
    and told that a proposal about a snapshot that has since moved is discarded
    rather than applied to whatever replaced it. That is not the fence —
    ``review_authority.adjudicate``'s ``evidence_head_sha`` check is — but a
    reviewer that knows the bound writes fewer proposals the fence must throw
    away.

    The instruction leads and the variable payload is delimited and last, per
    ADR-0087's long-context placement rule.
    """
    payload = evidence.as_payload()
    return f"""Review one bounded change to a HydraFlow issue and return one JSON object.

You are a HydraFlow `{role}` reviewing issue #{payload["issue_number"]} with fresh
eyes. You did not write this change and you have not seen it before. Everything
you are allowed to know is in the blocks at the end of this message: what was
asked for, what was agreed, what changed, and what the tests did. The
implementer's prompt, reasoning and transcript are deliberately absent — your
job is to judge the change, not the argument that produced it.

Your review is about one exact snapshot and nothing else: branch
`{payload["branch"]}`, based on `{payload["base_sha"]}`, at commit
`{payload["head_sha"]}`. A proposal about a snapshot that has moved by the time you
finish is discarded, not applied to whatever replaced it.

What you produce, and what you do not decide:

- You produce a *proposal*. Deterministic code adjudicates it into a verdict and
  your recommendation is one input among several. Recommending `approve` while
  filing a blocking finding resolves to `request-changes`, and filing any
  finding at all means the result is no stronger than `comment`.
- You cannot withhold a finding in order to reach a recommendation. Every
  concern goes in `findings`; they are counted, not read for tone.
- You have no shell, no file access, no repository access and no network. You
  cannot merge a pull request, approve one, move a label, push a commit, run a
  test or start a process. Do not describe doing any of those and do not make
  your recommendation conditional on one being done for you.

Respond with one JSON object and nothing else — no prose before it, no
explanation after it, no code fence around it:

{_OUTPUT_SCHEMA}

Rules for the object:

- `recommended` is exactly one of `approve`, `comment`, `request-changes`. Any
  other value, or a missing one, makes the whole reply unusable — there is no
  default and none will be invented for you.
- `findings` is a list, empty when you have none. `blocking` is `true` unless
  you write literal `false`; an advisory observation is a finding with
  `"blocking": false`, not a sentence buried in `summary`.
- Quote only the lines you are talking about. `file` and `line` name a place in
  the diff below, not a place you assume exists elsewhere.

Edge cases, and what to do about each:

- If the diff is marked TRUNCATED, review what you can see, say so in `summary`,
  and file it as a finding with `"blocking": false`. A partial review offered as
  a complete one is worse than no review.
- If the diff is empty, say so in `summary` with an empty `findings` list and
  recommend `comment`. An empty change is a real state, not an error.
- If the evidence is missing a fact you need — no plan, no test result, no
  acceptance criteria — name the missing fact in a finding rather than guessing.
  A stated gap is a useful review; an assumption presented as a finding is not.
- Otherwise, if you are unsure whether something belongs in `findings`, ask
  whether you would block a merge on it. If not, it is `"blocking": false`.

<issue number="{payload["issue_number"]}" title="{_attr(payload["issue_title"])}">
{payload["issue_goal"]}
</issue>

<acceptance_criteria>
{_bullets(payload["acceptance_criteria"])}
</acceptance_criteria>

<agreed_plan>
{payload["plan_summary"]}
</agreed_plan>

<changed_files>
{_bullets(payload["changed_files"])}
</changed_files>

<diff branch="{payload["branch"]}" base="{payload["base_sha"]}" head="{payload["head_sha"]}">
{_bounded_diff(str(payload["diff"]))}
</diff>

<tests command="{_attr(payload["test_command"])}">
{payload["test_summary"]}
{_bullets(payload["test_failures"])}
</tests>
"""


def _attr(value: object) -> str:
    """*value* as a delimiter-safe attribute.

    An issue title carrying a double quote or a newline would otherwise close
    the pseudo-tag early and leave the rest of the title reading as markup — a
    reviewer parsing a broken block is being shown something other than the
    evidence it was handed.
    """
    return str(value).replace('"', "'").replace("\n", " ").strip()


def _bullets(values: object) -> str:
    """A sequence rendered as a list, or a line that says it was empty.

    An empty block would read to a reviewer as "not applicable"; a line that
    says nothing was supplied reads as what it is, which is the difference
    between a reviewer noting a missing acceptance criterion and one silently
    assuming there were none.
    """
    if not isinstance(values, list | tuple) or not values:
        return "(none supplied)"
    return "\n".join(f"- {value}" for value in values)


def _bounded_diff(diff: str) -> str:
    """What the reviewer is shown of the change, and what it is told about the rest.

    The cut is *announced*. A reviewer shown the first :data:`MAX_DIFF_CHARS`
    characters of a long diff and told nothing will judge as though that is the
    whole change, and the resulting proposal would carry the confidence of a
    complete review over a partial one.
    """
    if not diff.strip():
        return "(the diff supplied with this evidence is empty)"
    if len(diff) <= MAX_DIFF_CHARS:
        return diff
    return (
        f"(TRUNCATED at {MAX_DIFF_CHARS} characters; the change continues past "
        "the end of this block and you are not being shown the rest)\n"
        + diff[:MAX_DIFF_CHARS]
    )


def parse_review_proposal(text: str) -> ReviewProposal | None:
    """One reviewer's reply as a proposal, or ``None`` when it is not one.

    ``None`` rather than a stand-in, on every failure path. The tempting
    defaults are all fabrications: an empty ``APPROVE`` invents a clean review
    nobody performed, and an empty ``REQUEST_CHANGES`` invents a blocking
    judgement with no finding behind it. A caller that gets ``None`` has a
    receipt saying the output contract failed, which is the truth.

    Only :data:`_PROPOSAL_KEYS` and :data:`_FINDING_KEYS` are read. A reply
    carrying, say, a ``verdict`` key is not rejected for it and not warned
    about — the key is simply never looked at, so it has no path to authority.
    That is ``review_evidence``'s allow-list argument applied to the other
    direction of the boundary.

    Coercion is deliberately asymmetric, and the asymmetry is the safety
    property. Prose is trimmed to fit, and an unusable ``line`` becomes
    ``None``, because neither can change whether something blocks. But
    ``blocking`` is true unless the reply says literal ``false``, a finding with
    no prose is kept with a placeholder rather than dropped, and a reply with
    more than :data:`MAX_FINDINGS` findings is refused whole rather than
    trimmed: every one of those would otherwise let this parser do the one thing
    P5 forbids a reviewer to do, which is make a finding go away.
    """
    try:
        raw = extract_json(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    findings = raw.get("findings", ())
    if not isinstance(findings, list | tuple):
        return None
    if len(findings) > MAX_FINDINGS:
        logger.warning(
            "review_worker_runner: a reply carried %d findings (max %d); it is "
            "refused whole rather than trimmed",
            len(findings),
            MAX_FINDINGS,
        )
        return None
    try:
        return ReviewProposal(
            recommended=raw.get("recommended"),  # type: ignore[arg-type]
            findings=tuple(_finding(entry) for entry in findings),
            summary=_text(raw.get("summary"), MAX_PROPOSAL_SUMMARY_CHARS),
        )
    except (ValueError, TypeError):
        # An unknown ``recommended``, or a finding that survived coercion and
        # still would not validate. Pydantic raises ``ValidationError``, which
        # IS a ``ValueError``; ``TypeError`` covers an unhashable or otherwise
        # unusable value reaching a field. Either way there is no opinion here.
        return None


def _finding(entry: object) -> ReviewFinding:
    """One finding, coerced only where coercion cannot weaken it."""
    if not isinstance(entry, dict):
        # A bare string in the findings list is still somebody saying something
        # is wrong. Kept, and kept blocking: silently dropping it would be this
        # parser hiding a finding on a formatting technicality.
        return ReviewFinding(summary=_summary_or_placeholder(entry))
    picked: dict[str, Any] = {k: v for k, v in entry.items() if k in _FINDING_KEYS}
    line = picked.get("line")
    return ReviewFinding(
        summary=_summary_or_placeholder(picked.get("summary")),
        file=_text(picked.get("file"), MAX_FINDING_SUMMARY_CHARS),
        line=line if isinstance(line, int) and not isinstance(line, bool) else None,
        # Blocking unless the reply says literal ``false``. ``"no"``, ``0`` and
        # a missing key all block, because the only reading that costs nothing
        # when wrong is the one that holds the change.
        blocking=picked.get("blocking") is not False,
    )


NO_SUMMARY_PLACEHOLDER = "(a finding was reported with no summary)"
"""What stands in when a finding carries no prose.

:class:`review_authority.ReviewFinding` requires a non-empty summary, so a
finding with none would fail validation and take the **whole proposal** down
with it — nine good findings lost to one malformed tenth. Substituting prose
keeps the finding, and the finding is what carries ``blocking``: the placeholder
changes what an operator reads, never what the adjudicator counts.
"""


def _summary_or_placeholder(value: object) -> str:
    """A finding's prose, bounded, and never empty."""
    return _text(value, MAX_FINDING_SUMMARY_CHARS) or NO_SUMMARY_PLACEHOLDER


def _text(value: object, limit: int) -> str:
    """*value* as bounded prose. Non-strings are rendered rather than dropped."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


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
    where a model *was* served but did not satisfy the requirement. Recording it
    would put a mis-resolved id in the one field whose validator exists to make
    that a validation error, which is the smuggling path rather than the
    evidence.

    ``lineage`` is passed on the refusals that follow a **real spawn**: a child
    that ran to its deadline and was reaped did exist, was billed, and had a
    spawn id, and a receipt that hid that would make a dispatched child
    indistinguishable from one that was never started.
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

    ``spawn_out["spawned"]`` is set from ``run_simple``'s **outcome**: it
    returned, or it timed out. Both imply a process. The residual under-claims —
    a child whose call ended some third way loses its lineage — which is the
    safe direction for a discriminator whose whole job is to stop a receipt
    saying a child ran when none did.
    """
    return lineage if spawn_out.get("spawned") else None
