"""The shadow-mode Fable director: it decides, and nothing acts on the decision.

This is #11537's whole subject. Under ``issue_controller + fable_director`` the
deterministic :class:`issue_driver.IssueDriver` still executes every phase and
remains authoritative; at each boundary it completes, this object reconstructs
the issue's canonical context, asks an isolated Fable turn what it would do,
runs the answer past the narrow broker, and writes the comparison down. The live
pipeline never reads any of it.

Three properties are what make that claim true rather than intended:

* the seam is :class:`driver_manager.DriverBoundaryObserver` — it is handed a
  boundary that already happened and returns nothing, so there is no value the
  allocator could act on. ``tests/regressions/test_issue_11537_shadow_safety.py``
  proves the live effects are byte-identical with and without it, including when
  it raises;
* the broker has no method that dispatches anything, so "no production worker is
  dispatched by Fable" is the absence of the code rather than a flag;
* nothing here writes convergence state. ADR-0137's narrowing of ADR-0094 is
  explicit — *a driver may sequence the outer lap but may not own its state* —
  so this object touches no ledger, no lap count and no verdict. Its only
  durable output is telemetry in :mod:`director_shadow_log`.

**Fail-closed at the boundary, in six ways**, because #11537 lists six:

======================  ===============================================
stop                    no turn is started once the stop event is set
timeout                 the turn is killed with its process group (S6)
malformed command       unframed output or a schema failure discards it
stale epoch             the fence refuses the dispatch (``STALE_EPOCH``)
process-tree teardown   ``kill_process_group``, proven by the probe
sandbox unverified      S4's assertion refuses before any admission
======================  ===============================================

Every one of those produces a recorded failure and **zero** hypothetical
dispatches. A failure must never be recorded as "the director chose to yield" —
that would launder a broken runtime into an agreement statistic, which is the
number ADR-0137 B5's rollout bar depends on.

**Capsules are reconstructed, never resumed.** The probe proved a dead
``--resume`` exits 1 with no assistant turn, so this runtime does not have a
session to lose: every turn is built from live label truth and the driver's own
fencing tokens, and the vendor session id is captured only as a rotation hint.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from director_sandbox import (
    DirectorSandboxError,
    ProbeEvidence,
    assert_observed_surface,
)
from director_shadow_log import (
    ShadowAgreement,
    ShadowObservation,
    TurnFailure,
    classify_agreement,
    has_agreement_rule,
)
from director_turn_runner import extract_command_json, render_capsule_prompt
from driver_contracts import (
    WORKER_CATALOG,
    DirectorCapsule,
    DirectorCommand,
    DriverLease,
    WorkerRole,
    WriterLease,
)
from exception_classify import reraise_on_credit_or_bug
from issue_driver import AdvanceOutcome
from issue_driver_policy import phase_for_state

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable
    from pathlib import Path

    from director_broker import BrokerVerdict, ShadowDispatchBroker
    from director_shadow_log import ShadowObservationLog
    from director_turn_runner import DirectorTurnResult, DirectorTurnRunner
    from driver_contracts import DirectorCommandKind, DriverPhase
    from issue_driver import DriverAdvance, IssueDriver
    from models import Task

logger = logging.getLogger("fable_director")

CAPSULE_LEASE_TTL_SECONDS = 900
"""How long a capsule's lease is valid. Short: a shadow turn is a minute's work.

Deliberately far below the driver's own six-hour lease. The driver's TTL is a
backstop against a wedged owner; this one bounds how stale a *director's* view
of the issue may be when the broker judges what it asked for.
"""

#: Outcomes that represent a boundary the driver actually attempted, and so a
#: decision a director could have made differently.
#:
#: ``IDLE`` and ``ALREADY_COMMITTED`` are deliberately absent, and leaving them
#: in was a real defect: a driver parked on a barrier reaches ``IDLE`` on *every*
#: poll, so a turn would be spawned every ``poll_interval`` indefinitely — and
#: because ``IDLE`` maps to "yield", where yielding is trivially right, those
#: no-op ticks would then dominate the agreement rate. That rate is the headline
#: number ADR-0137 B5's rollout bar reads, so contaminating it with ticks that
#: contain no decision would corrupt the evidence the next phase's go/no-go
#: rests on. They are recorded as ``NOT_A_BOUNDARY`` rather than dropped, so the
#: ratio of real boundaries to idle ticks stays visible.
OBSERVABLE_OUTCOMES: frozenset[AdvanceOutcome] = frozenset(
    {
        AdvanceOutcome.COMMITTED,
        AdvanceOutcome.FAILED,
        AdvanceOutcome.PREEMPTED,
        AdvanceOutcome.REJECTED,
        AdvanceOutcome.RETIRED,
    }
)

UNOBSERVED_DIGEST = "unobserved"
"""The worktree digests a shadow turn does not measure, said out loud.

``WriterLease`` requires them, and #11535 deliberately left writer-lease
enforcement to #11542. Rather than fabricate a plausible-looking sha, the lease
carries a value that reads as what it is. The lease is never held on entry, and
the broker folds it forward within a batch so the single-writer property still
holds over what would have been dispatched.
"""


class FableDirector:
    """Runs one shadow director turn per completed driver boundary.

    Constructed only under ``execution_runtime=fable_director`` and only at the
    ``build_services`` composition root, so an operator who has not opted in has
    no such object in their process at all — the same default-off standard
    #11535 held itself to for ``DriverManager``.
    """

    def __init__(
        self,
        *,
        runner: DirectorTurnRunner,
        broker: ShadowDispatchBroker,
        shadow_log: ShadowObservationLog,
        evidence: ProbeEvidence,
        repo_slug: str,
        route_policy_revision: str,
        stage_labels: dict[str, str],
        stop_event: asyncio.Event | None = None,
        usd_budget_per_boundary: float = 1.0,
        usd_ceiling: float = 25.0,
        is_enabled: Callable[[], bool] | None = None,
    ) -> None:
        self._runner = runner
        self._broker = broker
        self._shadow_log = shadow_log
        self._evidence = evidence
        self._repo_slug = repo_slug
        self._route_policy_revision = route_policy_revision
        self._stage_labels = stage_labels
        self._stop_event = stop_event
        self._usd_budget_per_boundary = usd_budget_per_boundary
        self._usd_ceiling = usd_ceiling
        # Read per boundary, not captured once: it is a LIVE kill switch, and a
        # kill switch that needs a restart is not a kill switch. The dials that
        # select the director are restart-required; this one must not be,
        # because a director turn costs money.
        self._is_enabled = is_enabled

    @property
    def shadow_log(self) -> ShadowObservationLog:
        """The durable comparison record. Read by operator status and by humans.

        Exposed rather than kept private because it is the phase's entire
        product — and it is safe to expose precisely because nothing in the
        pipeline reads it: ADR-0137 keeps convergence state on
        ``ConvergenceLedger``, and this is telemetry beside it, not a second
        copy of it.
        """
        return self._shadow_log

    # -- startup ------------------------------------------------------------

    @classmethod
    def load_evidence(cls, path: Path) -> ProbeEvidence:
        """Read the committed probe evidence S4 asserts against, or refuse."""
        return ProbeEvidence.load(path)

    async def preflight(self) -> None:
        """Prove the runtime boundary before the factory believes it is watched.

        ADR-0137's go is *conditional on S4*, and S4 cannot be armed against
        evidence that will not load or a CLI whose version cannot be read. So
        this raises rather than degrading: a director that cannot prove its
        sandbox, its teardown, its credential boundary or its tool-surface
        assertion must refuse to run. Raising here surfaces it at boot, which is
        the only moment an operator is looking.
        """
        version = await self._runner.preflight()
        logger.info(
            "fable_director: preflight ok — CLI %s, evidence recorded against %s",
            version,
            self._evidence.agent_cli_version,
        )

    # -- the observation seam ----------------------------------------------

    async def observe_boundary(
        self, *, task: Task, advance: DriverAdvance, driver: IssueDriver
    ) -> None:
        """Record what a director would have done at this boundary.

        Returns ``None`` always, and the allocator discards even that. The only
        exception permitted to escape is a credit-exhaustion signal, which is
        factory-wide rather than a shadow failure — and the allocator's own
        containment re-raises it for the same reason.
        """
        refusal = self._refuse_before_spending()
        if refusal is not None:
            self._record_failure(task, advance, driver, refusal)
            return
        if advance.outcome not in OBSERVABLE_OUTCOMES:
            self._record_failure(task, advance, driver, TurnFailure.NOT_A_BOUNDARY)
            return
        phase = advance.phase or phase_for_state(driver.driver_state)
        if phase is None:
            # PARKED and the terminal states have no phase, so there is no
            # dispatch a director could have asked for at all.
            return

        live_label = self._stage_labels.get(driver.driver_state, "")
        lease = self._lease_for(driver, phase, live_label)
        capsule = self._build_capsule(task, driver, lease, live_label)

        try:
            result = await self._runner.run_turn(
                render_capsule_prompt(capsule.model_dump_json())
            )
        except DirectorSandboxError as exc:
            # The boundary could not be constructed for this turn. Fail closed,
            # loudly in the log, and carry on observing — a shadow component
            # must not take the pipeline down with it.
            logger.warning("fable_director: sandbox unavailable this turn: %s", exc)
            self._record_failure(
                task, advance, driver, TurnFailure.SANDBOX_UNVERIFIED, detail=str(exc)
            )
            return
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("fable_director: turn failed for #%d: %s", task.id, exc)
            self._record_failure(
                task, advance, driver, TurnFailure.TURN_ERROR, detail=str(exc)
            )
            return

        self._judge(task, advance, driver, lease, capsule, result, live_label)

    # -- one turn, judged ---------------------------------------------------

    def _judge(
        self,
        task: Task,
        advance: DriverAdvance,
        driver: IssueDriver,
        lease: DriverLease,
        capsule: DirectorCapsule,
        result: DirectorTurnResult,
        live_label: str,
    ) -> None:
        """Apply S4, then the schema, then the broker — in that order.

        The order is the safety property, and it has one step before S4 rather
        than starting with it. A turn that was **killed at its budget** or that
        printed **unframed junk** produced nothing for S4 to read, so running
        the assertion on it would report ``no_init_frame`` — true, and useless:
        it would file a dead CLI and a moved tool surface under the same code,
        and the operator watching the sandbox counter would see noise. Those two
        are classified first, on their own terms.

        Everything that *did* produce frames goes through S4 **before** the
        command is parsed, because a turn whose tool surface cannot be proven
        empty must have its output **discarded**, not parsed: parsing it and
        then refusing the dispatches would still let a turn that held ``Bash``
        for its lifetime influence what is recorded as the director's judgement.
        """
        if result.timed_out or result.unframed_output:
            self._record(
                task,
                advance,
                driver,
                agreement=ShadowAgreement.NO_COMMAND,
                failure=TurnFailure.TIMED_OUT
                if result.timed_out
                else TurnFailure.MALFORMED_OUTPUT,
                detail=result.stderr_excerpt,
                result=result,
            )
            return

        surface = assert_observed_surface(
            result.init_frame,
            evidence=self._evidence,
            observed_cli_version=self._runner.cli_version,
        )
        if not surface.verified:
            self._record(
                task,
                advance,
                driver,
                agreement=ShadowAgreement.NO_COMMAND,
                failure=TurnFailure.SANDBOX_UNVERIFIED,
                detail=surface.detail,
                result=result,
                sandbox_verdict=surface.verdict.value,
            )
            return

        failure = _turn_failure(result)
        if failure is not TurnFailure.NONE:
            self._record(
                task,
                advance,
                driver,
                agreement=ShadowAgreement.NO_COMMAND,
                failure=failure,
                detail=result.stderr_excerpt,
                result=result,
                sandbox_verdict=surface.verdict.value,
            )
            return

        command = _parse_command(result)
        if command is None:
            self._record(
                task,
                advance,
                driver,
                agreement=ShadowAgreement.NO_COMMAND,
                failure=TurnFailure.MALFORMED_OUTPUT,
                detail="no DirectorCommand could be read from the turn's output",
                result=result,
                sandbox_verdict=surface.verdict.value,
            )
            return

        verdict = self._broker.admit(
            command,
            capsule=capsule,
            lease=lease,
            writer_lease=_unheld_writer_lease(lease),
            sandbox_verified=True,
            now=datetime.now(UTC),
            live_stage_label=live_label or lease.expected_stage_label,
        )
        self._record(
            task,
            advance,
            driver,
            agreement=_agreement_or_no_command(advance.outcome, command.kind),
            failure=TurnFailure.NONE,
            detail=command.rationale[:500],
            result=result,
            sandbox_verdict=surface.verdict.value,
            command=command,
            verdict=verdict,
        )

    # -- capsule construction ----------------------------------------------

    def _lease_for(
        self, driver: IssueDriver, phase: DriverPhase, live_label: str
    ) -> DriverLease:
        return DriverLease(
            driver_id=driver.driver_id,
            epoch=driver.epoch,
            repo_slug=self._repo_slug,
            issue_number=driver.issue_number,
            phase=phase,
            expected_stage_label=live_label or "hydraflow-unlabelled",
            phase_attempt=driver.phase_attempt(phase),
            expires_at=datetime.now(UTC) + timedelta(seconds=CAPSULE_LEASE_TTL_SECONDS),
        )

    def _build_capsule(
        self,
        task: Task,
        driver: IssueDriver,
        lease: DriverLease,
        live_label: str,
    ) -> DirectorCapsule:
        """Rebuild the whole of one turn's context from live state.

        Nothing carries over from a previous turn — not a transcript, not a
        session, not a receipt. That is the acceptance criterion "fresh
        reconstruction succeeds without vendor session history", and it is met
        by never having anything to reconstruct *from*.

        ``prior_receipts`` is deliberately empty. In shadow mode no worker ever
        ran, so there are no receipts of work; the only receipts that exist are
        the broker's own refusals, and feeding a director its refusals would
        teach it to route around the rule table rather than to it. When #11541
        lets a worker run, its receipt is real context and belongs here.
        """
        return DirectorCapsule(
            lease=lease,
            issue_goal=_issue_goal(task),
            live_stage_label=lease.expected_stage_label,
            allowed_roles=_roles_for_phase(lease.phase),
            route_policy_revision=self._route_policy_revision,
            remaining_usd_budget=self._usd_budget_per_boundary,
            remaining_wall_clock_seconds=CAPSULE_LEASE_TTL_SECONDS,
            prior_receipts=(),
            stop_requested=self._stopping(),
            draining=False,
        )

    # -- recording ----------------------------------------------------------

    def _stopping(self) -> bool:
        return self._stop_event is not None and self._stop_event.is_set()

    def _refuse_before_spending(self) -> TurnFailure | None:
        """The three reasons not to start a turn at all, checked before cost.

        Ordered cheapest-and-most-absolute first. Each returns a recorded
        failure rather than a silent skip, so an operator reading the rollup can
        tell "the director declined" from "the director was never asked".
        """
        if self._stopping():
            return TurnFailure.STOPPED
        if self._is_enabled is not None and not self._is_enabled():
            return TurnFailure.DISABLED
        spent = float(self._shadow_log.summary()["usd_cost_total"])
        if spent >= self._usd_ceiling:
            logger.warning(
                "fable_director: aggregate spend ceiling reached ($%.2f of "
                "$%.2f); no further shadow turns will be started this run",
                spent,
                self._usd_ceiling,
            )
            return TurnFailure.SPEND_CEILING
        return None

    def _record_failure(
        self,
        task: Task,
        advance: DriverAdvance,
        driver: IssueDriver,
        failure: TurnFailure,
        *,
        detail: str = "",
    ) -> None:
        self._record(
            task,
            advance,
            driver,
            agreement=ShadowAgreement.NO_COMMAND,
            failure=failure,
            detail=detail,
            result=None,
        )

    def _record(
        self,
        task: Task,
        advance: DriverAdvance,
        driver: IssueDriver,
        *,
        agreement: ShadowAgreement,
        failure: TurnFailure,
        detail: str,
        result: DirectorTurnResult | None,
        sandbox_verdict: str = "",
        command: DirectorCommand | None = None,
        verdict: BrokerVerdict | None = None,
    ) -> None:
        """Write one observation. A failed turn records **no** hypothetical work.

        Guaranteed by construction: every ``would_dispatch`` field is read off a
        broker verdict, and a broker verdict is produced on exactly one path —
        the one where the surface was verified, the turn succeeded and the
        command parsed. There is no branch on which a failure carries
        hypothetical work.
        """
        self._shadow_log.record(
            ShadowObservation(
                recorded_at=datetime.now(UTC).isoformat(),
                issue_number=task.id,
                driver_id=driver.driver_id,
                epoch=driver.epoch,
                phase=advance.phase.value if advance.phase else "",
                live_outcome=advance.outcome.value,
                live_state=driver.driver_state,
                agreement=agreement,
                command_kind=command.kind.value if command is not None else None,
                turn_failure=failure,
                turn_failure_detail=detail[:500],
                would_dispatch=() if verdict is None else tuple(verdict.worker_tree()),
                invalid_requests=0 if verdict is None else verdict.invalid_requests,
                rejection_reasons=()
                if verdict is None
                else tuple(reason.value for reason in verdict.rejection_reasons),
                route_revisions=0 if verdict is None else verdict.route_revisions,
                usd_cost=result.usd_cost if result else 0.0,
                latency_ms=result.latency_ms if result else 0,
                sandbox_verdict=sandbox_verdict,
            )
        )


def _agreement_or_no_command(
    outcome: AdvanceOutcome, kind: DirectorCommandKind
) -> ShadowAgreement:
    """``classify_agreement``, with its loud failure kept loud but not fatal.

    The comparison raises for an unmapped outcome on purpose — scoring one
    nobody wired up as agreement would inflate the number ADR-0137 B5's bar
    reads. But raising *here* would travel up into the allocator's containment
    and the observation would be dropped entirely, turning "fails loudly" into
    "silently records nothing", which is strictly worse than what it replaced.
    So this asks first rather than provoking the raise, logs the gap by name,
    and records the boundary with no agreement rather than with a wrong one.
    """
    if not has_agreement_rule(outcome):
        logger.error(
            "fable_director: no agreement rule for %s; recording the boundary "
            "without an agreement verdict. Add a row to "
            "director_shadow_log._AGREEING_COMMAND.",
            outcome.value,
        )
        return ShadowAgreement.NO_COMMAND
    return classify_agreement(outcome, kind)


def _turn_failure(result: DirectorTurnResult) -> TurnFailure:
    """Classify a framed turn's own failure, first match wins.

    Timeout and unframed output never reach here — they are classified before
    S4, because they produce no frames for S4 to read.

    Resume loss is checked before the generic error because it is the *specific*
    failure ADR-0137 requires to be countable; folding it into ``TURN_ERROR``
    would erase the one signal the rollout bar's "successful fresh
    reconstruction on every resume failure" line reads.
    """
    if result.looks_like_resume_loss:
        return TurnFailure.RESUME_LOSS
    if result.failed:
        return TurnFailure.TURN_ERROR
    return TurnFailure.NONE


def _parse_command(result: DirectorTurnResult) -> DirectorCommand | None:
    """Validate the turn's reply against the fixed contract, or refuse it.

    ``DirectorCommand`` is frozen and ``extra="forbid"``, so anything that is
    not exactly one of dispatch / yield / finish — including a plausible-looking
    object with an invented field — fails validation and is discarded. That is
    the malformed-command fail-closed requirement, enforced by the schema rather
    than by a parser someone has to keep correct.
    """
    raw = extract_command_json(result.frames)
    if raw is None:
        return None
    try:
        return DirectorCommand.model_validate_json(raw)
    except ValueError as exc:
        logger.info("fable_director: refusing a malformed director command: %s", exc)
        return None


def _roles_for_phase(phase: DriverPhase) -> frozenset[WorkerRole]:
    """Exactly the catalogued roles legal at *phase*, and nothing else.

    The capsule's ``allowed_roles`` is the director's whole menu, and
    ``admit_dispatch`` refuses anything outside it with ``ROLE_NOT_IN_CAPSULE``.
    Deriving it from ``WORKER_CATALOG`` rather than listing it here means one
    catalog governs both what may be asked for and what is offered.
    """
    return frozenset(
        role for role, entry in WORKER_CATALOG.items() if phase in entry.allowed_phases
    )


def _unheld_writer_lease(lease: DriverLease) -> WriterLease:
    """A single-writer lease at the driver's identity and epoch, held by no one."""
    return WriterLease(
        driver_id=lease.driver_id,
        epoch=lease.epoch,
        holder_request_id=None,
        worktree_base_digest=UNOBSERVED_DIGEST,
        worktree_head_digest=UNOBSERVED_DIGEST,
    )


def _issue_goal(task: Task) -> str:
    """The bounded goal text a capsule carries. Never an unbounded repo dump."""
    body = (getattr(task, "body", "") or "").strip()
    goal = f"{task.title}\n\n{body}".strip() or task.title or f"issue {task.id}"
    return goal[:8000]
