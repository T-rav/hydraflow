"""Implementation batch processing for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from adequacy_demand import pin_findings
from adr_utils import is_adr_issue_title, next_adr_number
from agent import AgentRunner
from beads_manager import BeadsManager
from config import HydraFlowConfig
from dispatch_overlap import DispatchOverlapTracker
from flows import Edge, Flow, FlowState, KillSwitch, Node, NodeHook
from harness_insights import (
    FailureCategory,
    HarnessInsightStore,
    format_known_traps_for_prompt,
    top_failure_categories,
)
from implement_failure_class import classify_implement_failure
from implement_spec_reviewer import (
    SpecComplianceReviewer,
    SpecReviewInput,
    compute_branch_changed_files,
    compute_branch_diff,
    format_gaps_for_prior_failure,
)
from implement_timeout import tiered_implement_timeout
from issue_cache import classification_complexity
from models import (
    EscalationContext,
    GitHubIssue,
    PipelineStage,
    PRInfo,
    Task,
    WorkerResult,
    WorkerResultMeta,
)
from phase_utils import (
    MemorySuggester,
    PipelineEscalator,
    _sentry_transaction,
    issue_state_is_resolved,
    log_exception_with_bug_classification,
    record_harness_failure,
    release_batch_in_flight,
    run_refilling_pool,
    run_with_fatal_guard,
    store_lifecycle,
)
from run_recorder import RunRecorder
from state import StateTracker
from task_source import TaskTransitioner
from transcript_summarizer import TranscriptSummarizer

if TYPE_CHECKING:
    from issue_cache import IssueCache
    from ports import IssueStorePort, PRPort, WorkspacePort
    from precondition_gate import PreconditionGate

logger = logging.getLogger("hydraflow.implement_phase")


# ---------------------------------------------------------------------------
# Implement flow (P2 of #10682, ADR-0111) — edge guards
# ---------------------------------------------------------------------------
#
# The per-issue implement pipeline runs as an explicit ``src.flows.Flow``:
#
#     decompose -> no-progress-abort -> issue-state -> build -> screen
#         screen  --(zero-commit)-------------------> zero-commit-abort
#             zero-commit-abort --(routed to diagnose, #11568)--> done
#             zero-commit-abort --(abort disabled / below threshold)--> spec-verify
#         screen  --(null-delivery)-----------------> spec-verify -> gate -> done
#         screen  --(otherwise)---------------------> open-pr
#         open-pr --(success / early-return)--------> done
#         open-pr --(failed retry / no-PR failure)--> spec-verify -> gate -> done
#
# Every fail-closed early-exit (existing-PR shortcut, attempt-cap, no-progress
# abort, zero-commit abort, ``_handle_successful_push`` early return) sets
# ``state['_stop']`` and
# routes straight to the terminal ``done`` sink. The LLM/agent call lives inside
# ``build`` alone (the actuator boundary); routing between nodes is
# deterministic. The graph is reused two ways: ``_worker_inner`` runs it from
# ``decompose``; ``_handle_implementation_result`` re-enters it at ``screen``
# (``Flow.resume``) with the built ``result`` pre-seeded, so the post-build
# handling has a single source of truth.


def _flow_stopped(state: FlowState) -> bool:
    """Edge guard: a node signalled a fail-closed early exit → route to ``done``."""
    return bool(state.get("_stop"))


def _route_is_zero_commit(state: FlowState) -> bool:
    """Edge guard: ``screen`` classified a zero-commit failure (#11568).

    Zero-commit results visit ``zero-commit-abort`` first: at/over the
    ``implement_no_progress_abort_attempts`` threshold (default 1 — the
    FIRST such result) the issue routes to diagnose and the walk ends;
    otherwise it falls through to ``spec-verify`` like any other failure.
    """
    return state.get("route") == "fail_zero_commit"


def _route_is_failure_screen(state: FlowState) -> bool:
    """Edge guard: ``screen`` classified a zero-commit / null-delivery failure.

    These are the two failures that never push and go straight to the shared
    ``spec-verify`` node (screen-specific comment + spec-compliance review).
    Every other classification (success, retry-push, committed-but-failed,
    no-workspace) flows through ``open-pr`` first. Zero-commit results reach
    here only via ``zero-commit-abort`` (its first-match edge wins).
    """
    return state.get("route") in {"fail_zero_commit", "fail_null_delivery"}


def _pinned_adequacy_demand(result: WorkerResult) -> list[str]:
    """The test-adequacy demand to carry onto the next attempt (#11644).

    Empty unless this attempt actually died at the adequacy gate. Only the
    findings that BLOCKED ride forward: advisory findings (new *and* naming
    nothing locatable) did not reject this run, so promoting them to the next
    run's bar would reintroduce exactly the moving target the pin removes.
    """
    outcome = result.test_adequacy
    if outcome is None or outcome.passed:
        return []
    advisory = set(outcome.advisory_findings)
    return list(pin_findings([f for f in outcome.findings if f not in advisory]))


def _open_pr_terminal(state: FlowState) -> bool:
    """Edge guard: ``open-pr`` fully resolved the outcome → route to ``done``.

    True on an early return (no-PR fallback / zero-diff escalation set
    ``_stop``) or on a genuine success. A failed push path (a failed
    review-feedback retry, or a committed-but-failed fresh attempt) instead
    falls through to ``spec-verify`` so the two-stage reviewer still captures
    gaps for the next attempt (ADR-0063 W5).
    """
    return bool(state.get("_stop")) or bool(state["result"].success)


class ImplementPhase:
    """Fetches ready issues and runs implementation agents concurrently."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        workspaces: WorkspacePort,
        agents: AgentRunner,
        prs: PRPort,
        store: IssueStorePort,
        stop_event: asyncio.Event,
        run_recorder: RunRecorder | None = None,
        harness_insights: HarnessInsightStore | None = None,
        beads_manager: BeadsManager | None = None,
        active_issues_cb: Callable[[], None] | None = None,
        transcript_summarizer: TranscriptSummarizer | None = None,
        precondition_gate: PreconditionGate | None = None,
        spec_reviewer: SpecComplianceReviewer | None = None,
        issue_cache: IssueCache | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._workspaces = workspaces
        self._agents = agents
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._store = store
        self._stop_event = stop_event
        self._run_recorder = run_recorder
        self._harness_insights = harness_insights
        self._beads_manager = beads_manager
        self._active_issues_cb = active_issues_cb
        self._summarizer = transcript_summarizer
        self._active_issues: set[int] = set()
        self._active_issues_lock = asyncio.Lock()
        # Dispatch-overlap guard (#10778): pre-flight admission check that
        # serializes concurrently-dispatched units whose predicted scopes
        # overlap. Scopes are reserved at dispatch time (in ``_supply_live``)
        # and released when a worker exits (in ``_worker``'s ``finally``).
        self._dispatch_overlap = DispatchOverlapTracker()
        self._suggest_memory = MemorySuggester(config)
        self._zero_diff_memory_filed: set[int] = set()
        self._precondition_gate = precondition_gate
        # ADR-0063 W5: spec-compliance reviewer dispatched after failed
        # attempts. None disables the two-stage flow entirely (used by tests
        # that don't care, and by production when ``spec_reviewer`` isn't
        # wired into the service registry).
        self._spec_reviewer = spec_reviewer
        # #11568: triage's complexity score (the same IssueCache record the
        # plan-side size tiers read) sizes each build's wall-clock budget.
        # None → every spawn gets the full ``agent_timeout`` ceiling.
        self._issue_cache = issue_cache
        self._escalator = PipelineEscalator(
            state,
            prs,
            store,
            harness_insights,
            origin_label=config.ready_label[0],
            hitl_label=config.hitl_label[0],
            diagnose_label=config.diagnose_label[0],
            stage=PipelineStage.IMPLEMENT,
        )

    @property
    def active_issues(self) -> set[int]:
        return self._active_issues

    async def _claim_issue(self, issue_number: int) -> None:
        """Stamp the durable build-claim marker on *issue_number* (#10168).

        Adds ``in_progress_label`` the moment a build STARTS on a ready issue.
        The label coexists with ``hydraflow-ready`` (it is not a stage) and
        advertises "being built" to any external observer of GitHub labels —
        a second factory instance, a parallel operator session, or an
        out-of-band Agent dispatch — so they skip the issue instead of
        double-picking it (the #10141 cross-actor collision class).

        Best-effort: a GitHub hiccup must never block the build (dark-factory
        contract). The in-process ``IssueStore`` guards still protect the
        current process even if the durable stamp fails.
        """
        try:
            await self._prs.add_labels(issue_number, self._config.in_progress_label)
        except Exception:
            logger.warning(
                "Issue #%d: failed to stamp in-progress build claim (continuing)",
                issue_number,
                exc_info=True,
            )

    async def _release_claim(self, issue_number: int) -> None:
        """Clear the build-claim marker on any build exit (#10168).

        On the success path the ``ready → review`` swap already removed the
        claim (it is in ``all_pipeline_labels``); this remove is then a no-op.
        On abandon/failure the issue stays at ``hydraflow-ready``, so removing
        the claim here is what makes it re-pickable — an issue can never get
        stuck claimed. Best-effort, like :meth:`_claim_issue`.
        """
        for label in self._config.in_progress_label:
            try:
                await self._prs.remove_label(issue_number, label)
            except Exception:
                logger.warning(
                    "Issue #%d: failed to clear in-progress build claim '%s'",
                    issue_number,
                    label,
                    exc_info=True,
                )

    def _known_traps_section(self) -> str:
        """Render the harness-insights Known CI Traps section (#9858).

        Cached per phase instance for one hour — the failure distribution
        moves slowly and run_batch may spawn many agents per tick. Fails
        open to "" so a store hiccup never blocks implementation.
        """
        now = time.monotonic()
        cached = getattr(self, "_known_traps_cache", None)
        if cached is not None and now - cached[0] < 3600:
            return cached[1]
        section = ""
        if self._harness_insights is not None:
            try:
                entries = top_failure_categories(self._harness_insights._failures_path)
                section = format_known_traps_for_prompt(entries)
            except (OSError, ValueError) as exc:
                logger.debug("known-traps render failed: %s", exc)
        self._known_traps_cache = (now, section)
        return section

    def _log_adversarial_carryover(self, issue: Task) -> None:
        """Log CRITICAL/HIGH carryover concerns surfaced during plan phase.

        Dark-factory contract (Task 7 of earlier-adversarial pipeline):
        implement_phase READS the per-issue ``AdversarialState`` so the
        operator (and downstream tooling) can see pending concerns, but
        it MUST NOT block on them. Concerns are logged at INFO level
        and the implementation proceeds.

        Safe to call when no state has been persisted — the read
        returns ``None`` and the method is a no-op.
        """
        adv = self._state.get_adversarial_state(issue.id)
        if adv is None:
            return
        loud_concerns = [
            c for c in adv.pending_concerns if c.severity in {"CRITICAL", "HIGH"}
        ]
        if not loud_concerns:
            return
        lines = [
            f"  - [{c.id}|{c.severity}|{c.raised_in_stage}] {c.concern}"
            for c in loud_concerns
        ]
        logger.info(
            "Adversarial carryover for issue #%d (%d %s concern(s)) — "
            "forwarding to implementation per dark-factory contract:\n%s",
            issue.id,
            len(loud_concerns),
            "CRITICAL/HIGH",
            "\n".join(lines),
        )

    async def _post_impl_transcript(self, result: WorkerResult, *, status: str) -> None:
        """File memory suggestion and post transcript summary for a single result."""
        if result.transcript:
            await self._suggest_memory(
                result.transcript, "implementer", f"issue #{result.issue_number}"
            )
        if self._summarizer and result.transcript and result.issue_number > 0:
            try:
                await self._summarizer.summarize_and_comment(
                    transcript=result.transcript,
                    issue_number=result.issue_number,
                    phase="implement",
                    status=status,
                    duration_seconds=result.duration_seconds,
                    log_file=self._impl_log_reference(result.issue_number),
                )
            except Exception as exc:
                log_exception_with_bug_classification(
                    logger,
                    exc,
                    f"Failed to post transcript summary for issue #{result.issue_number}",
                )

    async def post_impl_transcript_hooks(self, results: list[WorkerResult]) -> None:
        """File memory suggestions and post transcript summaries for completed runs.

        Called by the orchestrator after :meth:`run_batch` returns.  Skips
        memory filing for issues where the zero-diff escalation handler has
        already filed a suggestion with a more specific source tag.
        """
        for result in results:
            already_filed = result.issue_number in self._zero_diff_memory_filed
            self._zero_diff_memory_filed.discard(result.issue_number)
            if already_filed:
                # Zero-diff handler filed memory with a specific source; skip
                # memory filing here but still post the transcript summary.
                if self._summarizer and result.transcript and result.issue_number > 0:
                    try:
                        await self._summarizer.summarize_and_comment(
                            transcript=result.transcript,
                            issue_number=result.issue_number,
                            phase="implement",
                            status="success" if result.success else "failed",
                            duration_seconds=result.duration_seconds,
                            log_file=self._impl_log_reference(result.issue_number),
                        )
                    except Exception as exc:
                        log_exception_with_bug_classification(
                            logger,
                            exc,
                            f"Failed to post transcript summary for issue #{result.issue_number}",
                        )
            else:
                await self._post_impl_transcript(
                    result, status="success" if result.success else "failed"
                )

    def _impl_log_reference(self, issue_number: int) -> str:
        """Return a display-friendly log path for implementer transcripts."""
        log_path = self._config.log_dir / f"issue-{issue_number}.txt"
        return self._config.format_path_for_display(log_path)

    def _hitl_cause(self, issue: Task, reason: str) -> str:
        """Build a HITL cause string, prefixing with epic context if applicable."""
        epic_child_labels = {lbl.lower() for lbl in self._config.epic_child_label}
        issue_labels = {t.lower() for t in issue.tags}
        if not (epic_child_labels & issue_labels):
            return reason
        # Try to find parent epic number from issue body
        match = re.search(r"[Pp]arent\s+[Ee]pic[:\s#]*(\d+)", issue.body)
        if match:
            return f"Epic child (#{match.group(1)}): {reason}"
        return f"Epic child: {reason}"

    async def run_batch(
        self,
        issues: list[Task] | None = None,
    ) -> tuple[list[WorkerResult], list[Task]]:
        """Run implementation agents concurrently using a slot-filling pool.

        If *issues* is ``None``, drains the ``IssueStore`` ready queue
        once, runs the precondition gate (#6423) if configured, then
        feeds the gated batch into the slot-fill pool. If a fixed list
        is provided, processes those items directly without gating —
        callers that pass an explicit list are assumed to have done
        their own gating.
        """
        # Declared before the branches so both assignments conform to one
        # type (the pool accepts a sync or async supply — #10511).
        supply: Callable[[], list[Task] | Awaitable[list[Task]]]
        if issues is not None:
            # Fixed-list mode — the caller provided an explicit, already-gated
            # list (it has done its own gating). Feed the pool one at a time.
            items_iter = iter(issues)
            exhausted = False

            async def _supply_fixed() -> list[Task]:
                nonlocal exhausted
                if exhausted:
                    return []
                item = next(items_iter, None)
                if item is None:
                    exhausted = True
                    return []
                return [item]

            supply = _supply_fixed
        else:
            # Live-refill from the store on every slot open (#10511). Pull one
            # ready issue at a time and, when a precondition gate is configured,
            # gate it inline: gate failures are routed back (relabeled out of
            # the ready stage) and their in-flight claim released, so a long
            # build no longer starves newly-ready work of the free slot. This
            # restores the #10312 mid-run refill intent for the gated path,
            # which the old drain-once-then-fixed-list approach defeated.
            # implement now shares the same live get_X(1) refill as triage and
            # plan (which already did). review keeps its bespoke loop because
            # its no-work items self-re-enqueue and it needs a work-based idle
            # break — see _do_review_work.
            issues = []

            async def _supply_live() -> list[Task]:
                from stage_preconditions import Stage  # noqa: PLC0415

                guard_on = self._config.dispatch_overlap_guard_enabled
                # Units held this round for scope overlap (#10778). They are
                # kept out of the ready queue while we pull the next candidate,
                # then re-enqueued in the ``finally`` so a later refill round
                # re-dispatches them — so a held unit never blocks a
                # non-overlapping one from taking the free slot now.
                held: list[Task] = []
                try:
                    while True:
                        batch = self._store.get_implementable(1)
                        if not batch:
                            return []
                        if self._precondition_gate is not None:
                            try:
                                gated = await self._precondition_gate.filter_and_route(
                                    batch, Stage.READY
                                )
                            except BaseException:
                                # The gate re-raises credit exhaustion and real
                                # bugs rather than swallowing them (#11609), so
                                # this call is no longer total. ``batch`` is
                                # already spliced out of the ready queue and
                                # stamped in ``_in_flight`` — an in-memory map
                                # only a full orchestrator reset clears — so
                                # without this release the issue being gated
                                # when credit runs out is invisible to
                                # ``get_implementable`` forever. The ``finally``
                                # below only re-enqueues ``held``.
                                release_batch_in_flight(
                                    self._store, {t.id for t in batch}
                                )
                                raise
                            if not gated:
                                # Gate failure: filter_and_route already routed
                                # it back. Release the in-flight claim
                                # get_implementable took so it doesn't leak, then
                                # keep pulling — the next may pass.
                                release_batch_in_flight(
                                    self._store, {t.id for t in batch}
                                )
                                continue
                            batch = gated
                        if guard_on:
                            candidate = batch[0]
                            hold = self._dispatch_overlap.reserve_or_hold(candidate)
                            if hold is not None:
                                # Predicted-scope overlap with an in-flight build
                                # (#10778): serialize by holding this unit; the
                                # ``finally`` re-enqueues it so it re-dispatches
                                # once the blocking unit frees its slot.
                                logger.info(
                                    "Issue #%d held from concurrent dispatch — "
                                    "%s overlap with in-flight issue #%d (%s); "
                                    "serializing to a later round (#10778)",
                                    hold.held_id,
                                    hold.reason.kind,
                                    hold.blocking_id,
                                    hold.reason.detail,
                                )
                                held.append(candidate)
                                continue
                        issues.extend(batch)
                        return batch
                finally:
                    for task in held:
                        # Put held units back on the ready queue (this also
                        # clears the in-flight claim get_implementable took) so
                        # the next refill round can re-dispatch them.
                        self._store.enqueue_transition(task, "ready")

            supply = _supply_live

        async def _worker(idx: int, issue: Task) -> WorkerResult:
            if self._stop_event.is_set():
                # Reserved at supply time (#10778); release before the early
                # exit so a stop mid-fill can't leak the reservation.
                self._dispatch_overlap.release(issue.id)
                return WorkerResult(
                    issue_number=issue.id,
                    branch=f"agent/issue-{issue.id}",
                    error="stopped",
                )

            branch = f"agent/issue-{issue.id}"
            async with self._active_issues_lock:
                self._active_issues.add(issue.id)
                if self._active_issues_cb:
                    self._active_issues_cb()
            with _sentry_transaction("pipeline.implement", f"implement:#{issue.id}"):
                async with store_lifecycle(self._store, issue.id, "implement"):
                    self._state.mark_issue(issue.id, "in_progress")
                    self._state.set_branch(issue.id, branch)
                    # Durable cross-actor build claim (#10168): stamp the
                    # in-progress marker on GitHub the moment the build starts
                    # so out-of-band actors skip this ready issue. Cleared on
                    # the ready→review swap at PR-open, and in the ``finally``
                    # below on any abandon/failure exit.
                    await self._claim_issue(issue.id)

                    def _on_worker_failure(exc_name: str) -> WorkerResult:
                        self._state.mark_issue(issue.id, "failed")
                        record_harness_failure(
                            self._harness_insights,
                            issue.id,
                            FailureCategory.IMPLEMENTATION_ERROR,
                            f"Worker {exc_name} for issue #{issue.id}",
                            stage=PipelineStage.IMPLEMENT,
                        )
                        return WorkerResult(
                            issue_number=issue.id,
                            branch=branch,
                            error=f"Worker {exc_name} for issue #{issue.id}",
                        )

                    try:
                        return await run_with_fatal_guard(
                            self._worker_inner(idx, issue, branch),
                            on_failure=_on_worker_failure,
                            context=f"Worker failed for issue #{issue.id}",
                            log=logger,
                        )
                    finally:
                        async with self._active_issues_lock:
                            self._active_issues.discard(issue.id)
                            if self._active_issues_cb:
                                self._active_issues_cb()
                        # Free this unit's dispatch-overlap reservation (#10778)
                        # so any unit held for overlapping it can now dispatch.
                        self._dispatch_overlap.release(issue.id)
                        release_batch_in_flight(self._store, {issue.id})
                        # Clear the durable build claim on every exit (#10168).
                        # Success already swapped it away at PR-open (no-op
                        # here); failure/abandon leaves the issue at ready, so
                        # this is what makes it re-pickable — never stuck.
                        await self._release_claim(issue.id)

        all_results = await run_refilling_pool(
            supply_fn=supply,
            worker_fn=_worker,
            max_concurrent=self._config.max_workers,
            stop_event=self._stop_event,
            # Opt in to mid-run refill (issue #10312, extending #10296): wake
            # at least every poll_interval to dispatch items enqueued while a
            # long implement worker holds a slot, instead of only refilling
            # when a worker completes.
            poll_interval=self._config.poll_interval,
        )
        return all_results, issues

    async def _worker_inner(self, idx: int, issue: Task, branch: str) -> WorkerResult:
        """Core implementation logic — called inside the semaphore.

        Runs the per-issue implement pipeline as an explicit ``src.flows.Flow``
        (P2 of #10682, ADR-0111): ``decompose -> no-progress-abort -> build ->
        screen -> (spec-verify | open-pr) -> gate -> done``. The public entry
        keeps its signature and ``WorkerResult`` return type; internally it
        builds and runs the flow, seeding the shared state and reading the
        final ``result`` off the terminal state. Callers (``run_batch`` via
        ``_worker``) are unaffected.
        """
        flow = self._build_implement_flow()
        outcome = await flow.run(self._initial_flow_state(idx, issue, branch))
        return outcome.state["result"]

    @staticmethod
    def _initial_flow_state(idx: int, issue: Task, branch: str) -> FlowState:
        """Seed the implement flow's shared working state for one attempt."""
        return {"idx": idx, "issue": issue, "branch": branch}

    def _build_implement_flow(
        self,
        *,
        checkpoint: NodeHook | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> Flow:
        """Build the per-issue implement DAG (P2 of #10682, ADR-0111).

        The straight-line ``_worker_inner`` control is re-expressed as an
        explicit flow (see the module-level diagram). Node roles:

        * ``decompose`` — deterministic admission control: read plan-phase
          adversarial carryover, seed an ADR plan, resolve review-feedback /
          retry, take the existing-PR shortcut, enforce the attempt cap. Early
          exits set ``result`` and route to ``done``.
        * ``no-progress-abort`` *(new — the point of P2, #10659/#10616)* —
          before spending another (up to ``agent_timeout``) build, escalate a
          non-converging issue to HITL instead of retry-thrashing to the cap.
        * ``issue-state`` *(new — #11457)* — the last gate before the
          actuator: re-read the issue's state from GitHub and abandon the
          build when the issue was resolved elsewhere between selection and
          branch-cut. Placement after ``no-progress-abort`` is deliberate —
          ``decompose``'s existing-PR shortcut and attempt cap must still run
          first. ``open-pr`` re-checks the same thing before pushing, closing
          the mid-build half of the window.
        * ``build`` — the sole actuator: runs the implementation agent and
          records the run (unchanged from today).
        * ``screen`` — classify the outcome (zero-commit / null-delivery /
          push / no-op) exactly as the pre-refactor ``_handle_implementation_
          result`` head did.
        * ``zero-commit-abort`` *(#11568)* — a zero-commit result at/over
          ``implement_no_progress_abort_attempts`` (default 1: the FIRST one)
          routes to diagnose with the transcript tail and ends the walk,
          instead of spending the W5 reviewer and attempts 2 and 3 on the
          same shape. Below the threshold (or disabled) it falls through to
          ``spec-verify`` — the pre-#11568 retry shape.
        * ``spec-verify`` — reuse ``SpecComplianceReviewer`` via
          ``_run_spec_compliance_review`` (the shared node from the P0.5 map)
          on any failed attempt, plus the screen-specific comment.
        * ``gate`` — the read-only ``retry <= max | route-to-HITL`` disposition
          (enforcement stays in ``decompose``/``no-progress-abort``).
        * ``open-pr`` — push + PR resolution + review handoff for the
          success/retry path.

        ``checkpoint`` / ``kill_switch`` stay injected per ADR-0111 so the
        primitive's persistence + halt seams are wired-through and testable.
        The production entry runs without a checkpoint: a single-attempt build
        needs no resume, and writing one would be a new on-disk side effect
        this parity-gated, no-flag refactor must not introduce. Per-node
        ``on_node`` event wiring is deferred to a later phase per ADR-0111.
        """
        return Flow(
            nodes=[
                Node("decompose", self._flow_decompose, kind="gate"),
                Node(
                    "no-progress-abort",
                    self._flow_no_progress_abort,
                    kind="gate",
                ),
                Node(
                    "issue-state",
                    self._flow_issue_state,
                    kind="gate",
                ),
                Node("build", self._flow_build),
                Node("screen", self._flow_screen, kind="gate"),
                Node(
                    "zero-commit-abort",
                    self._flow_zero_commit_abort,
                    kind="gate",
                ),
                Node("spec-verify", self._flow_spec_verify),
                Node("gate", self._flow_gate, kind="gate"),
                Node("open-pr", self._flow_open_pr),
                Node("done", self._flow_done),
            ],
            edges=[
                # First-match-wins: a stopped node skips straight to the sink.
                Edge("decompose", "done", when=_flow_stopped),
                Edge("decompose", "no-progress-abort"),
                Edge("no-progress-abort", "done", when=_flow_stopped),
                Edge("no-progress-abort", "issue-state"),
                Edge("issue-state", "done", when=_flow_stopped),
                Edge("issue-state", "build"),
                Edge("build", "screen"),
                Edge("screen", "zero-commit-abort", when=_route_is_zero_commit),
                Edge("screen", "spec-verify", when=_route_is_failure_screen),
                Edge("screen", "open-pr"),
                Edge("zero-commit-abort", "done", when=_flow_stopped),
                Edge("zero-commit-abort", "spec-verify"),
                Edge("spec-verify", "gate"),
                Edge("gate", "done"),
                Edge("open-pr", "done", when=_open_pr_terminal),
                Edge("open-pr", "spec-verify"),
            ],
            entry="decompose",
            checkpoint=checkpoint,
            kill_switch=kill_switch,
        )

    # -- flow nodes ---------------------------------------------------------

    async def _flow_decompose(self, state: FlowState) -> FlowState:
        """Admission control: prepare the attempt or short-circuit (#10682).

        Reads plan-phase adversarial carryover, seeds an ADR plan, resolves
        review-feedback / retry into state, takes the existing-PR shortcut, and
        enforces the attempt cap. Any early exit sets ``result`` + ``_stop`` so
        routing skips straight to ``done`` without a build.
        """
        issue = state["issue"]
        branch = state["branch"]

        # Earlier-adversarial pipeline: read carryover concerns surfaced during
        # plan_phase, log them, then proceed. Never blocks — dark-factory.
        self._log_adversarial_carryover(issue)
        self._prepare_adr_plan(issue)

        # If a non-draft PR already exists and this is NOT a review-feedback
        # retry, skip implementation and transition directly to review. This
        # handles issues requeued to hydraflow-ready that already have completed
        # PRs from a prior run.
        review_feedback = self._state.get_review_feedback(issue.id) or ""
        state["review_feedback"] = review_feedback
        state["is_retry"] = bool(review_feedback)
        if not review_feedback:
            existing_pr = await self._prs.find_open_pr_for_branch(
                branch, issue_number=issue.id
            )
            if existing_pr and existing_pr.number > 0 and not existing_pr.draft:
                logger.info(
                    "Issue #%d already has open PR #%d — skipping to review",
                    issue.id,
                    existing_pr.number,
                )
                self._store.enqueue_transition(issue, "review")
                await self._transitioner.transition(
                    issue.id,
                    "review",
                    pr_number=existing_pr.number,
                )
                self._state.increment_session_counter("implemented")
                self._state.mark_issue(issue.id, "success")
                state["result"] = WorkerResult(
                    issue_number=issue.id,
                    branch=branch,
                    success=True,
                    pr_info=existing_pr,
                )
                state["_stop"] = True
                return state

        cap_result = await self._check_attempt_cap(issue, branch)
        if cap_result is not None:
            state["result"] = cap_result
            state["_stop"] = True
        return state

    async def _flow_no_progress_abort(self, state: FlowState) -> FlowState:
        """No-progress early-abort node (P2 of #10682; #10659/#10616).

        The crux of P2: a non-converging issue used to burn up to
        ``max_issue_attempts × agent_timeout`` (≈ 3 × 3600s) of build time
        before the attempt cap escalated it. This node runs BEFORE ``build``
        and, once :meth:`_should_abort_no_progress` confirms the issue is
        thrashing (this attempt is at/over ``implement_no_progress_abort_
        attempts`` and the immediately prior attempt produced no output),
        escalates to HITL immediately — skipping the next full build.

        Review-feedback retries are review-driven, not ready-queue thrash, so
        they are never aborted here.
        """
        issue = state["issue"]
        branch = state["branch"]
        if state.get("review_feedback"):
            return state
        if not self._should_abort_no_progress(issue):
            return state
        state["result"] = await self._escalate_no_progress(issue, branch)
        state["_stop"] = True
        return state

    async def _flow_issue_state(self, state: FlowState) -> FlowState:
        """Re-check the issue's GitHub state immediately before the build (#11457).

        The work-picker validates issue state at selection only; between the
        pick and the branch-cut another PR can close the issue and the local
        cache goes stale — building anyway produced the duplicate PRs behind
        #11443/#11451. GitHub is the source of truth (ADR-0041), so this node
        re-reads it as the LAST gate before the actuator and abandons the
        attempt when the issue was resolved elsewhere. The read fails open:
        only a positive resolved state abandons, never a failed one.
        """
        issue = state["issue"]
        if not await self._issue_resolved_elsewhere(issue.id):
            return state
        state["result"] = await self._abandon_resolved_issue(
            issue, state["branch"], at="branch-cut"
        )
        state["_stop"] = True
        return state

    async def _flow_build(self, state: FlowState) -> FlowState:
        """The actuator node: run the implementation agent and record it.

        This is the only node that spends the (up to ``agent_timeout``) LLM
        build — the actuator boundary. Sets ``state['result']``. Behaviour is
        unchanged from the pre-refactor ``_worker_inner`` body.
        """
        issue = state["issue"]
        branch = state["branch"]
        idx = state["idx"]
        review_feedback = state["review_feedback"]

        # Start recording if a run recorder is available.
        ctx = None
        if self._run_recorder is not None:
            try:
                ctx = self._run_recorder.start(issue.id)
                plan_text = self._read_plan_for_recording(issue.id)
                if plan_text:
                    ctx.save_plan(plan_text)
                ctx.save_config(
                    self._config.model_dump(
                        mode="json",
                        exclude={
                            "gh_token",
                            "whatsapp_token",
                            "whatsapp_phone_id",
                            "whatsapp_recipient",
                            "whatsapp_verify_token",
                        },
                    )
                )
            except (RuntimeError, OSError):
                logger.debug("Run recording setup failed", exc_info=True)
                ctx = None

        # Inject prior reflections into the issue context so the agent benefits
        # from learnings accumulated in previous cycles.
        from reflections import append_reflection, read_reflections  # noqa: PLC0415

        prior_reflections = read_reflections(self._config, issue.id)
        if prior_reflections:
            issue.body = (issue.body or "") + (
                f"\n\n## Prior Reflections\n\n{prior_reflections}"
            )

        result = await self._run_implementation(issue, branch, idx, review_feedback)

        # Failure-class split (#11593 seam 3): classify every failed build at
        # the point the result lands so the System tab shows why attempts die
        # (test_adequacy / timeout / zero_commit / diff_sanity / quality /
        # scope / other) instead of a bare attempt count. Counter updates
        # must never take down the build path.
        failure_class: str | None = None
        if not result.success:
            failure_class = classify_implement_failure(result.error)
            try:
                self._state.increment_implement_failure(failure_class)
            except OSError:
                logger.debug(
                    "implement failure-class counter update failed", exc_info=True
                )

        # Record a reflection for future cycles.
        if result.error:
            append_reflection(
                self._config,
                issue.id,
                "implement",
                f"Attempt {idx} failed: {result.error[:200]}",
            )
        elif result.success:
            append_reflection(
                self._config,
                issue.id,
                "implement",
                f"Attempt {idx} succeeded on branch {branch}.",
            )

        # Finalize the recording.
        if ctx is not None:
            try:
                if result.transcript:
                    for line in result.transcript.splitlines():
                        ctx.append_transcript(line)
                outcome = "success" if result.success else "failed"
                ctx.finalize(
                    outcome,
                    error=result.error,
                    failure_class=failure_class,
                    test_adequacy=(
                        result.test_adequacy.model_dump()
                        if result.test_adequacy is not None
                        else None
                    ),
                )
            except (RuntimeError, OSError):
                logger.debug("Run recording finalize failed", exc_info=True)

        state["result"] = result
        return state

    async def _flow_screen(self, state: FlowState) -> FlowState:
        """Classify the build outcome (#10682 screen node).

        Reproduces the classification precedence of the pre-refactor
        ``_handle_implementation_result`` head — zero-commit first, then
        null-delivery (which mutates ``result`` into a failure), then the
        push/no-op fall-through — writing the branch into ``state['route']``.
        Routing to ``spec-verify`` vs ``open-pr`` is done by the outgoing
        edges.
        """
        result = state["result"]
        is_retry = state["is_retry"]
        if self._is_zero_commit_failure(result):
            state["route"] = "fail_zero_commit"
        elif await self._is_null_delivery(result):
            # Null-delivery guard (issue #9480): a non-empty diff whose every
            # file is a planner diagram / auto-generated artifact is not a real
            # implementation — treat it as a failed attempt.
            result.success = False
            if not result.error:
                result.error = (
                    "Null delivery: implementation produced only planner "
                    "diagrams / auto-generated artifacts, no code or tests"
                )
            state["route"] = "fail_null_delivery"
        elif result.workspace_path and (result.success or is_retry):
            state["route"] = "push"
        else:
            state["route"] = "final_only"
        return state

    async def _flow_zero_commit_abort(self, state: FlowState) -> FlowState:
        """Route a zero-commit result to diagnose instead of attempt N+1 (#11568).

        Measured 2026-08-21: attempts per merged issue doubled (1.2 → 2.2);
        13 of 153 implement results ended "No commits found on branch" and
        each then burned a second and third full build on the same shape. A
        zero-commit attempt is not a partial success to retry blindly. When
        this attempt is at/over ``implement_no_progress_abort_attempts``
        (default 1 — the first one), escalate now through the shared
        diagnose/HITL escalator with the transcript tail, skip the W5 spec
        review (there is no diff to review) and end the walk. Below the
        threshold, or with the abort disabled (0), fall through to
        ``spec-verify`` — the pre-#11568 corrective-retry shape.

        Credit exhaustion never reaches here: ``AgentRunner.run`` re-raises
        ``CreditExhaustedError`` before a ``WorkerResult`` exists, so the
        ADR-0119 pause is untouched.
        """
        issue = state["issue"]
        if not self._should_abort_zero_commit(issue):
            return state
        await self._escalate_zero_commit(issue, state["result"])
        state["disposition"] = "escalate"
        state["_stop"] = True
        return state

    async def _flow_spec_verify(self, state: FlowState) -> FlowState:
        """Handle a failed attempt + reuse ``SpecComplianceReviewer`` (#10682).

        The shared spec-verify node from the P0.5 map. Runs the screen-specific
        failure handler (zero-commit / null-delivery comment + mark-failed) when
        applicable, then dispatches ``_run_spec_compliance_review`` (ADR-0063
        W5) so the next attempt sees concrete gaps. Push-path failures (a failed
        review-feedback retry, a committed-but-failed fresh attempt) reach here
        already marked failed by ``open-pr`` — for those it runs the spec review
        only.
        """
        issue = state["issue"]
        result = state["result"]
        route = state["route"]
        if route == "fail_zero_commit":
            await self._handle_zero_commits(issue, result)
        elif route == "fail_null_delivery":
            await self._handle_null_delivery(issue, result)
        await self._run_spec_compliance_review(issue, result)
        return state

    async def _flow_gate(self, state: FlowState) -> FlowState:
        """Convergence gate: record the retry-vs-HITL disposition (#10682).

        The epic's ``gate(retry <= max | route-to-HITL)`` node. It is read-only
        here: it records ``state['disposition']`` (``"retry"`` for a converging
        failure that re-queues as ``hydraflow-ready`` for a corrective attempt,
        ``"escalate"`` for a thrashing / cap-reached one). Enforcement stays in
        ``decompose`` (``_check_attempt_cap``), ``no-progress-abort`` and
        ``zero-commit-abort`` so the HITL escalation fires exactly once (never
        double-firing here).
        """
        issue = state["issue"]
        attempts = self._state.get_issue_attempts(issue.id)
        escalate = (
            self._should_abort_no_progress(issue)
            or attempts >= self._config.max_issue_attempts
        )
        state["disposition"] = "escalate" if escalate else "retry"
        return state

    async def _flow_open_pr(self, state: FlowState) -> FlowState:
        """Push + PR resolution + review handoff (#10682 open-pr node).

        Reproduces the pre-refactor push/finalize tail of
        ``_handle_implementation_result``: push the branch (success or retry),
        resolve/recover the PR and hand off to review, flag requirements gaps,
        and mark the issue. A fully-resolved early return (no-PR fallback /
        zero-diff escalation) or a success ends the walk at ``done``; a failed
        push falls through to ``spec-verify`` for the two-stage review.
        """
        issue = state["issue"]
        result = state["result"]
        is_retry = state["is_retry"]

        # Surface B of the #11457 window: the issue can also close DURING
        # the (minutes-long) build. Re-check before pushing so a resolved
        # issue never opens the duplicate PR — the commit cost is already
        # spent, but the PR, its CI, and the review round are not.
        if await self._issue_resolved_elsewhere(issue.id):
            state["result"] = await self._abandon_resolved_issue(
                issue, state["branch"], at="open-pr"
            )
            state["_stop"] = True
            return state

        # Fresh failed attempts skip the push entirely — partial commits never
        # land on origin. Cycling retries reset the worktree to main. Retries
        # with review feedback push so the existing PR sees the iteration.
        if result.workspace_path and (result.success or is_retry):
            pushed = await self._prs.push_branch(
                Path(result.workspace_path), result.branch
            )
            if pushed:
                early_return = await self._handle_successful_push(
                    issue, result, is_retry
                )
                if early_return is not None:
                    state["result"] = early_return
                    state["_stop"] = True
                    return state

        if result.success and result.transcript:
            await self._flag_requirements_gaps(issue, result.transcript)

        self._state.mark_issue(issue.id, "success" if result.success else "failed")
        return state

    @staticmethod
    async def _flow_done(state: FlowState) -> FlowState:
        """Terminal sink for the implement flow (#10682).

        A no-op join point so every path — the happy walk and each fail-closed
        early exit — ends at one observable terminal carrying the final
        ``result``.
        """
        return state

    # -- no-progress abort helpers ------------------------------------------

    def _should_abort_no_progress(self, issue: Task) -> bool:
        """Return ``True`` when *issue* is thrashing and should abort to HITL.

        The signal (#10659/#10616): this attempt is at/over the configured
        ``implement_no_progress_abort_attempts`` threshold AND the immediately
        prior attempt produced no output (zero commits with an error). The
        default threshold equals ``max_issue_attempts`` (3), so the ADR-0063 W5
        corrective retry still runs and only the final, futile build is skipped.
        A threshold of 0 disables the abort entirely.
        """
        threshold = self._config.implement_no_progress_abort_attempts
        if threshold <= 0:
            return False
        attempts = self._state.get_issue_attempts(issue.id)
        # "Prior attempt" means the prior attempt of THIS cycle: a human
        # re-queue resets the counter but not the last worker meta, so attempt
        # 1 with stale zero-commit meta must build, not bounce (#11568).
        if attempts < 2 or attempts < threshold:
            return False
        prior_meta = self._state.get_worker_result_meta(issue.id) or {}
        return self._is_no_output_signal(prior_meta)

    def _should_abort_zero_commit(self, issue: Task) -> bool:
        """Post-build twin of :meth:`_should_abort_no_progress` (#11568).

        ``True`` when THIS attempt's zero-commit result is at/over the
        ``implement_no_progress_abort_attempts`` threshold — default 1, so
        the first zero-commit result routes to diagnose. ``0`` disables both
        aborts (the pre-#11568 retry-to-cap shape).
        """
        threshold = self._config.implement_no_progress_abort_attempts
        if threshold <= 0:
            return False
        # A zero-commit result proves at least one attempt ran, even when the
        # graph was re-entered at ``screen`` without ``decompose`` counting it.
        return max(self._state.get_issue_attempts(issue.id), 1) >= threshold

    @staticmethod
    def _is_no_output_signal(meta: WorkerResultMeta) -> bool:
        """Return ``True`` when *meta* records a no-output failed attempt.

        A no-output attempt committed nothing (``commits == 0``) and carried an
        error. The explicit ``== 0`` (not merely falsy/absent) matters: a prior
        meta without a ``commits`` key — e.g. attempts pre-seeded by a caller
        that never ran a build — is NOT a no-output signal, so the abort never
        fires on a fabricated attempt count.
        """
        return meta.get("commits") == 0 and bool(meta.get("error"))

    async def _escalate_no_progress(self, issue: Task, branch: str) -> WorkerResult:
        """Escalate a non-converging issue to HITL before another build (#10659).

        Posts an abort comment, routes the issue to the diagnose/HITL stage via
        the shared escalator, marks it failed, and returns a terminal
        ``WorkerResult`` — never spending the next (up to ``agent_timeout``)
        build cycle a thrashing issue would otherwise burn.
        """
        attempts = self._state.get_issue_attempts(issue.id)
        prior_meta = self._state.get_worker_result_meta(issue.id) or {}
        last_error = (
            prior_meta.get("error") or "no output (zero commits) on the prior attempt"
        )
        await self._transitioner.post_comment(
            issue.id,
            "## Implementation Aborted — No Progress\n\n"
            f"The prior {attempts - 1} implementation attempt(s) produced no "
            "output (zero commits). Rather than spend another full build cycle "
            "re-attempting a non-converging issue, HydraFlow is escalating to "
            "human review now instead of retry-thrashing to the attempt cap "
            "(#10659).\n\n"
            f"Last error: {last_error}\n\n"
            "---\n"
            "*Generated by HydraFlow Implementer*",
        )
        context = EscalationContext(
            cause=self._hitl_cause(
                issue, "implementation not converging (no commits across attempts)"
            ),
            origin_phase="implement",
        )
        await self._escalator(
            issue,
            cause=context.cause,
            details=(
                f"No-progress early abort after {attempts - 1} no-output "
                f"attempt(s): {last_error}"
            ),
            category=FailureCategory.HITL_ESCALATION,
            context=context,
        )
        self._state.mark_issue(issue.id, "failed")
        return WorkerResult(
            issue_number=issue.id,
            branch=branch,
            error=(
                f"Implementation aborted — no progress across attempts "
                f"({attempts - 1} no-output attempt(s))"
            ),
        )

    def _implement_timeout(self, issue: Task) -> int:
        """Complexity-tiered spawn budget for *issue* (#11568).

        Reads triage's ``complexity_score`` from the shared IssueCache
        classification record (the field #11304/#11305 tier on) and maps it
        through :func:`implement_timeout.tiered_implement_timeout` with
        ``agent_timeout`` as the ceiling. Unknown → the ceiling, so an
        unscored issue never gets a shorter budget than it did before.
        """
        complexity = classification_complexity(self._issue_cache, issue.id)
        ceiling = int(self._config.agent_timeout)
        timeout = tiered_implement_timeout(complexity, ceiling)
        if timeout != ceiling:
            logger.info(
                "Issue #%d: implement timeout %ds (complexity %s, ceiling %ds)",
                issue.id,
                timeout,
                complexity,
                ceiling,
            )
        return timeout

    def _transcript_tail(self, result: WorkerResult) -> str | None:
        """Last ``error_output_max_chars`` of the run transcript, or ``None``."""
        transcript = result.transcript or ""
        if not transcript:
            return None
        return transcript[-self._config.error_output_max_chars :]

    async def _escalate_zero_commit(self, issue: Task, result: WorkerResult) -> None:
        """Route a zero-commit attempt to diagnose with the transcript tail (#11568).

        Posts the zero-commit comment (with the tail folded in), stores an
        ``EscalationContext`` whose ``agent_transcript`` IS the tail (the
        diagnostic Stage-1 prompt quotes its head, so the tail is what the
        diagnoser sees), escalates through the shared escalator (label swap
        to diagnose + store transition + harness-failure record) and marks
        the issue failed. The ``WorkerResult`` is left as-is: it is the
        zero-commit result; the routing is the disposition.
        """
        # Floored like ``_should_abort_zero_commit``: a resume at ``screen``
        # can arrive before ``decompose`` counted this attempt.
        attempts = max(self._state.get_issue_attempts(issue.id), 1)
        max_attempts = self._config.max_issue_attempts
        last_error = result.error or "No commits found on branch"
        tail = self._transcript_tail(result)
        logger.warning(
            "Issue #%d: zero commits on attempt %d/%d — routing to diagnose (#11568)",
            issue.id,
            attempts,
            max_attempts,
        )
        tail_section = (
            "\n<details><summary>Transcript tail</summary>\n\n"
            f"```\n{tail}\n```\n</details>\n"
            if tail
            else ""
        )
        await self._transitioner.post_comment(
            issue.id,
            "## Implementation Failed — Zero Commits\n\n"
            "The implementation agent ran but produced no commits "
            f"(attempt {attempts}/{max_attempts}). A zero-commit attempt is "
            "not a partial success to retry blindly: rather than spend "
            "another full build on the same shape, HydraFlow is routing this "
            "issue to the diagnostic agent now with the transcript tail "
            "(#11568).\n\n"
            f"Last error: {last_error}\n"
            f"{tail_section}\n"
            "---\n"
            "*Generated by HydraFlow Implementer*",
        )
        context = EscalationContext(
            cause=self._hitl_cause(
                issue, f"implementation produced zero commits (attempt {attempts})"
            ),
            origin_phase="implement",
            agent_transcript=tail,
        )
        await self._escalator(
            issue,
            cause=context.cause,
            details=(
                f"Zero-commit attempt {attempts}/{max_attempts} routed to "
                f"diagnose: {last_error}"
            ),
            category=FailureCategory.HITL_ESCALATION,
            context=context,
        )
        self._state.mark_issue(issue.id, "failed")

    def _read_plan_for_recording(self, issue_number: int) -> str:
        """Read the plan file for *issue_number*, returning empty string on failure."""
        plan_path = self._config.plans_dir / f"issue-{issue_number}.md"
        try:
            return plan_path.read_text()
        except OSError:
            return ""

    # -- resolved-issue gate helpers (#11457) -------------------------------

    async def _issue_resolved_elsewhere(self, issue_number: int) -> bool:
        """Re-read the issue's state from GitHub; True when resolved (#11457).

        Fail-open by contract: a transient Port failure logs and reads as
        "not resolved" — the gate only ever abandons on a positive resolved
        read, so an unreadable issue still builds (trading a rare duplicate
        PR for a guaranteed stuck factory would be the worse failure).
        Credit/auth exhaustion and likely bugs re-raise per the
        ``reraise_on_credit_or_bug`` dark-factory contract.
        """
        try:
            gh_state = await self._prs.get_issue_state(issue_number)
        except Exception as exc:
            from exception_classify import reraise_on_credit_or_bug

            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Issue-state re-check failed for #%d — failing open (build proceeds)",
                issue_number,
                exc_info=True,
            )
            return False
        return issue_state_is_resolved(gh_state)

    async def _abandon_resolved_issue(
        self, issue: Task, branch: str, *, at: str
    ) -> WorkerResult:
        """Abandon an attempt whose issue was resolved elsewhere (#11457).

        Terminal, side-effect-free exit: the build slot returns without an
        agent run, worktree, or PR. Deliberately NO re-enqueue to ready and
        NO label stripping — the issue is closed on GitHub, so
        ``IssueFetcher._is_open`` drops it on the next refresh and
        ``LabelDriftWatcherLoop`` reconciles any stray pipeline labels
        (ADR-0088); re-queueing or swapping here would fight both. The state
        records ``completed`` (the terminal, workspace-clearing status) so no
        retry sweeper can pick a resolved issue back up, and the returned
        ``WorkerResult`` is non-success: this worker delivered nothing.
        """
        logger.info(
            "Issue #%d was resolved elsewhere (closed on GitHub) — abandoning "
            "the attempt at %s before spending further work (#11457)",
            issue.id,
            at,
        )
        self._state.mark_issue(issue.id, "completed")
        return WorkerResult(
            issue_number=issue.id,
            branch=branch,
            error=(
                f"Issue #{issue.id} already resolved elsewhere (closed on "
                f"GitHub) — build abandoned at {at}"
            ),
        )

    async def _create_beads_in_worktree(
        self, issue: Task, wt_path: Path
    ) -> dict[str, str] | None:
        """Create the issue's bead task graph in its own worktree store.

        Beads are created in the same per-worktree JSONL store that owns their
        lifecycle. The host ``bd`` CLI is deliberately excluded because its
        storage engine is database-backed. This replaces the old split where
        the planner created beads in a separate host store the agent's clone
        never saw. Best-effort: a beads failure must never block implementation.
        """
        from agent import AgentRunner  # noqa: PLC0415
        from task_graph import extract_phases, topological_sort  # noqa: PLC0415

        manager = self._beads_manager
        if manager is None:
            return None
        # The plan lives in the issue's "## Implementation Plan" comment (the
        # same source the agent reads); the issue was enriched with comments
        # just above. Fall back to the on-disk plan for safety.
        plan, _ = AgentRunner._extract_plan_comment(issue.comments)
        if not plan:
            plan = self._read_plan_for_recording(issue.id)
        if not plan:
            return None
        mapping: dict[str, str] | None = None
        try:
            phases = topological_sort(extract_phases(plan))
            if not phases:
                return None
            await manager.ensure_installed()
            await manager.init(wt_path)
            # The state mapping is only a cache for downstream prompt/review
            # context. It carries no stable task identity, so same-shaped IDs
            # may refer to an unrelated graph. Always ask the canonical JSONL
            # store to create-or-recover by issue/phase external refs.
            mapping = await manager.create_from_phases(phases, issue.id, wt_path)
            # Persist the identity of a successfully created/validated graph
            # before claiming roots. If one claim fails part-way through, the
            # next attempt can reuse this graph instead of appending another.
            self._state.set_bead_mapping(issue.id, mapping)
            if not self._config.dry_run:
                for phase in phases:
                    if not phase.depends_on:
                        root = await manager.show(mapping[phase.id], wt_path)
                        if root.status == "open":
                            await manager.claim(root.id, wt_path)
                        elif root.status not in {"in_progress", "closed"}:
                            raise RuntimeError(
                                f"root Beads task {root.id} has unexpected status "
                                f"{root.status!r}"
                            )
        except Exception as exc:  # noqa: BLE001
            from exception_classify import reraise_on_credit_or_bug  # noqa: PLC0415

            reraise_on_credit_or_bug(exc)
            logger.warning(
                "bead creation in worktree failed for #%d: %s", issue.id, exc
            )
            return mapping
        return mapping

    async def _complete_beads_after_success(
        self,
        mapping: dict[str, str],
        wt_path: Path,
    ) -> bool | None:
        """Close a successful phase graph in dependency order.

        AgentRunner is one opaque multi-phase session, so the factory can
        observe only the overall verified result. Root tasks are claimed
        before that session starts. Once it succeeds, this method repeatedly
        claims and closes the ready frontier, preserving dependency order and
        ensuring every task passes through ``in_progress``. Failed or
        interrupted runs never call this method, leaving roots in progress and
        untouched dependents open.
        """

        manager = self._beads_manager
        if manager is None:
            return None
        remaining = set(mapping.values())
        changed = False
        try:
            for bead_id in tuple(remaining):
                task = await manager.show(bead_id, wt_path)
                if task.status == "closed":
                    remaining.remove(bead_id)
                elif task.status not in {"open", "in_progress"}:
                    raise RuntimeError(
                        f"Beads task {task.id} has unexpected status {task.status!r}"
                    )
            while remaining:
                ready = await manager.list_ready(wt_path)
                frontier = [task for task in ready if task.id in remaining]
                if not frontier:
                    raise RuntimeError(
                        "successful implementation has no ready Beads tasks "
                        f"for remaining IDs: {sorted(remaining)}"
                    )
                for task in frontier:
                    if task.status == "open":
                        await manager.claim(task.id, wt_path)
                        changed = True
                    elif task.status != "in_progress":
                        raise RuntimeError(
                            f"ready Beads task {task.id} has unexpected status "
                            f"{task.status!r}"
                        )
                    await manager.close(
                        task.id,
                        "Phase complete",
                        wt_path,
                    )
                    changed = True
                    remaining.remove(task.id)
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            logger.warning(
                "bead lifecycle completion failed in %s: %s",
                wt_path,
                exc,
            )
            return None
        return changed

    def _build_cap_exceeded_comment(self, attempts: int, last_error: str) -> str:
        """Build the human-readable comment explaining why the cap was exceeded."""
        return (
            f"**Implementation attempt cap exceeded** — "
            f"{attempts - 1} attempt(s) exhausted "
            f"(max {self._config.max_issue_attempts}).\n\n"
            f"Last error: {last_error}\n\n"
            f"Escalating to human review."
        )

    async def _escalate_capped_issue(
        self, issue: Task, attempts: int, last_error: str
    ) -> None:
        """Post the cap comment, escalate to HITL, record harness failure."""
        comment = self._build_cap_exceeded_comment(attempts, last_error)
        await self._transitioner.post_comment(issue.id, comment)
        await self._escalator(
            issue,
            cause=f"Implementation attempt cap exceeded after {attempts - 1} attempt(s)",
            details=f"Implementation attempt cap exceeded after {attempts - 1} attempt(s): {last_error}",
            category=FailureCategory.HITL_ESCALATION,
        )

    async def _check_attempt_cap(self, issue: Task, branch: str) -> WorkerResult | None:
        """Check per-issue attempt cap.  Returns a WorkerResult on cap exceeded, else None."""
        attempts = self._state.increment_issue_attempts(issue.id)
        if attempts <= self._config.max_issue_attempts:
            return None

        last_meta = self._state.get_worker_result_meta(issue.id)
        last_error = (
            last_meta.get("error", "No error details available")
            or "No error details available"
        )
        await self._escalate_capped_issue(issue, attempts, last_error)
        self._state.mark_issue(issue.id, "failed")
        return WorkerResult(
            issue_number=issue.id,
            branch=branch,
            error=f"Implementation attempt cap exceeded ({attempts - 1} attempts)",
        )

    async def _setup_worktree_and_branch(
        self, issue: Task, branch: str, *, reset_for_retry: bool = False
    ) -> Path:
        """Ensure worktree exists/resumed and branch is pushed.

        When *reset_for_retry* is True, resets an existing worktree to
        ``origin/main`` to discard stale state from a prior failed attempt.
        """
        wt_path = self._config.workspace_path_for_issue(issue.id)
        if wt_path.is_dir():
            if reset_for_retry:
                logger.info(
                    "Resetting worktree to clean state for issue #%d retry",
                    issue.id,
                )
                try:
                    await self._workspaces.reset_to_main(wt_path)
                except (RuntimeError, OSError):
                    logger.warning(
                        "Worktree reset failed for issue #%d — continuing with existing state",
                        issue.id,
                        exc_info=True,
                    )
            else:
                logger.info("Resuming existing worktree for issue #%d", issue.id)
        else:
            wt_path = await self._workspaces.create(issue.id, branch)
        self._state.set_workspace(issue.id, str(wt_path))
        await self._prs.push_branch(wt_path, branch, force=reset_for_retry)
        await self._transitioner.post_comment(
            issue.id,
            f"**Branch:** [`{branch}`](https://github.com/"
            f"{self._config.repo}/tree/{branch})\n\n"
            f"Implementation in progress.",
        )
        return wt_path

    async def _record_impl_metrics(
        self, issue: Task, result: WorkerResult, review_feedback: str
    ) -> None:
        """Record quality-fix-attempt, duration, harness metrics to state/store."""
        if review_feedback:
            self._state.clear_review_feedback(issue.id)
        if result.duration_seconds > 0:
            self._state.record_implementation_duration(result.duration_seconds)
        if result.quality_fix_attempts > 0:
            self._state.record_quality_fix_rounds(result.quality_fix_attempts)
            for _ in range(result.quality_fix_attempts):
                self._state.record_stage_retry(issue.id, "quality_fix")
            record_harness_failure(
                self._harness_insights,
                issue.id,
                FailureCategory.QUALITY_GATE,
                f"Quality fix needed: {result.quality_fix_attempts} round(s). "
                f"Error: {result.error or 'none'}",
                stage=PipelineStage.IMPLEMENT,
            )
        # Only write a quality_fix stage record when a fix round actually
        # happened. Writing unconditionally (including count == 0) created an
        # empty stage_state["quality_fix"] entry for every issue; retrospective
        # reads via ConvergenceLedger.get_attempts() already default to 0 for
        # a missing stage, so skipping the zero-count write is a no-op for
        # readers.
        if result.quality_fix_attempts > 0:
            self._state.set_quality_fix_attempts(issue.id, result.quality_fix_attempts)
        meta: WorkerResultMeta = {
            "pre_quality_review_attempts": result.pre_quality_review_attempts,
            "duration_seconds": result.duration_seconds,
            "error": result.error,
            "commits": result.commits,
        }
        # #11644: pin the demand the adequacy gate actually made, so the next
        # attempt is judged against THIS bar rather than a freshly-sampled one.
        # Only the blocking findings ride forward — advisory ones did not
        # reject this run and must not become the next run's bar.
        pinned = _pinned_adequacy_demand(result)
        if pinned:
            meta["test_adequacy_findings"] = pinned
        self._state.set_worker_result_meta(issue.id, meta)

    async def _run_implementation(
        self,
        issue: Task,
        branch: str,
        worker_id: int,
        review_feedback: str,
    ) -> WorkerResult:
        """Set up worktree, push branch, run agent, record metrics."""
        # Retrieve prior failure context for retry feedback
        last_meta = self._state.get_worker_result_meta(issue.id)
        prior_failure = ""
        # #11644: the demand the previous attempt's adequacy gate stated. Rides
        # the same seam as prior_failure and under the same condition — during a
        # review-feedback retry the prior gate verdict is stale, so no pin.
        pinned_adequacy: list[str] = []
        reset_for_retry = bool(review_feedback)  # review-feedback retries always reset
        # Only inject prior failure context for cycling retries (no active review feedback).
        # During review-feedback retries the prior error is stale — the agent should
        # focus on reviewer comments, not a potentially-resolved quality gate error.
        if last_meta and not review_feedback:
            pinned_adequacy = [
                f
                for f in last_meta.get("test_adequacy_findings") or []
                if isinstance(f, str) and f.strip()
            ]
            prior_error = last_meta.get("error") or ""
            # ADR-0063 W5: spec-compliance gaps from the prior attempt's
            # post-failure review take priority — they describe *what* was
            # missing (or wrong), which is more actionable than the runner's
            # error string. Both are included when both exist.
            spec_gaps = last_meta.get("spec_review_gaps") or ""
            if spec_gaps and prior_error:
                prior_failure = f"{spec_gaps}\n\nRunner error: {prior_error}"
                reset_for_retry = True
            elif spec_gaps:
                prior_failure = spec_gaps
                reset_for_retry = True
            elif prior_error:
                prior_failure = prior_error
                reset_for_retry = True

        wt_path = await self._setup_worktree_and_branch(
            issue, branch, reset_for_retry=reset_for_retry
        )

        # Human-on-the-loop continuous steering (ADR-0099 #4): fold live
        # operator guidance into the prompt. Reference signal only — never
        # blocking; empty when the feature is off or no guidance was posted.
        human_guidance = self._state.get_human_steering(str(issue.id)).guidance or ""

        # Capture items.jsonl hash before agent runs (for outcome tracking)
        import hashlib  # noqa: PLC0415

        items_path = self._config.memory_dir / "items.jsonl"
        digest_hash = ""
        if items_path.exists():
            with contextlib.suppress(OSError):
                digest_hash = hashlib.sha256(items_path.read_bytes()).hexdigest()[:16]
        self._state.set_digest_hash(issue.id, digest_hash)

        # Copy architecture diagrams from /tmp into the worktree so the
        # implementer agent has full architectural context on disk.
        from planner import PlannerRunner  # noqa: PLC0415

        n_diagrams = PlannerRunner.copy_diagrams_to_workspace(issue.id, wt_path)
        if n_diagrams:
            logger.info(
                "Copied %d diagram file(s) into workspace for #%d",
                n_diagrams,
                issue.id,
            )
            PlannerRunner.cleanup_diagrams(issue.id)

        # Enrich the task with comments so the agent can find the plan
        # comment posted by the planner.  The IssueStore bulk fetch
        # does not include comment bodies.
        issue = await self._store.enrich_with_comments(issue)

        # Create the bead task graph in THIS worktree's canonical JSONL store.
        # Agent prompts reference these IDs but never invoke the database-backed
        # bd CLI; the planner no longer creates beads in a separate host store.
        bead_mapping: dict[str, str] | None = None
        if self._beads_manager is not None:
            bead_mapping = await self._create_beads_in_worktree(issue, wt_path)

        run_kwargs: dict[str, object] = {
            "worker_id": worker_id,
            "review_feedback": review_feedback,
            "prior_failure": prior_failure,
            "human_guidance": human_guidance,
            # #9858: recurring repo failure classes from harness-insights,
            # rendered once and injected so agents stop re-hitting
            # documented CI traps (ratchet, arch-regen, ...).
            "known_traps": self._known_traps_section(),
            # Diverse-retry: the agent frames its strategy-delta directive
            # as "attempt N of M" (rendered only when prior_failure is set).
            "attempt_number": self._state.get_issue_attempts(issue.id),
            # #11568: complexity-tiered wall-clock budget for the build spawn;
            # ``agent_timeout`` remains the ceiling inside the runner.
            "timeout_s": self._implement_timeout(issue),
            # #11644: judge this retry's adequacy verdict against the demand
            # the previous attempt stated, not a freshly-sampled one.
            "pinned_adequacy_findings": pinned_adequacy,
        }
        if bead_mapping:
            run_kwargs["bead_mapping"] = bead_mapping

        # Allocate a trace run id and set the tracing context on the agent
        # runner so its _execute calls build a TraceCollector.
        from trace_rollup import write_phase_rollup  # noqa: PLC0415
        from tracing_context import TracingContext, source_to_phase  # noqa: PLC0415

        phase = source_to_phase("implementer")
        run_id = self._state.begin_trace_run(issue.id, phase)
        self._agents.set_tracing_context(
            TracingContext(
                issue_number=issue.id,
                phase=phase,
                source="implementer",
                run_id=run_id,
            )
        )

        try:
            result = await self._agents.run(
                issue,
                wt_path,
                branch,
                **run_kwargs,  # type: ignore[arg-type]
            )
        finally:
            self._agents.clear_tracing_context()
            # Roll up the subprocess traces whether the run succeeded or failed.
            try:
                write_phase_rollup(
                    config=self._config,
                    issue_number=issue.id,
                    phase=phase,
                    run_id=run_id,
                )
            except Exception:
                logger.warning(
                    "Phase rollup failed for issue #%d", issue.id, exc_info=True
                )
            self._state.end_trace_run(issue.id, phase)

        if (
            result.success
            and bead_mapping
            and self._beads_manager is not None
            and not self._config.dry_run
        ):
            lifecycle_changed = await self._complete_beads_after_success(
                bead_mapping, wt_path
            )
            if lifecycle_changed is None:
                result.success = False
                result.error = "Failed to finalize worktree Beads lifecycle"
            elif not await self._agents.commit_pending(issue, wt_path):
                result.success = False
                result.error = "Failed to commit finalized worktree Beads lifecycle"

        await self._record_impl_metrics(issue, result, review_feedback)

        return result

    async def _handle_implementation_result(
        self, issue: Task, result: WorkerResult, is_retry: bool
    ) -> WorkerResult:
        """Handle the result of an agent run: close, create PR, swap labels.

        The post-build handling of the implement flow (P2 of #10682): the same
        ``screen -> (spec-verify | open-pr) -> gate`` graph ``_worker_inner``
        runs, re-entered at the ``screen`` node with the built ``result``
        pre-seeded (``Flow.resume``). Keeping this as the single source of truth
        — rather than a second inline copy — means the zero-commit /
        null-delivery / push / spec-compliance branches can never drift between
        the two entry points. Signature and return contract are unchanged.
        """
        flow = self._build_implement_flow()
        state: FlowState = {
            "issue": issue,
            "result": result,
            "is_retry": is_retry,
        }
        outcome = await flow.resume(state, "screen")
        return outcome.state["result"]

    @staticmethod
    def _is_zero_commit_failure(result: WorkerResult) -> bool:
        """Check whether *result* represents a zero-commit implementation failure.

        Any failed run with no commits is a zero-commit failure — not just
        the canonical "No commits found on branch" error. ProcessLookupError
        (subprocess killed mid-run), AuthenticationRetryError (credentials
        expired), and any other early-exit Exception path that leaves
        commits=0 must route to _handle_zero_commits, not push/PR.
        """
        return not result.success and result.commits == 0

    async def _is_null_delivery(self, result: WorkerResult) -> bool:
        """Return ``True`` if the branch diff is diagrams/auto-generated only.

        Computes the changed-file list for the branch and classifies it with
        ``null_delivery.is_null_delivery``. Fails open (returns ``False``) when
        the diff cannot be computed, so a transient git error never blocks a
        real implementation.
        """
        from null_delivery import is_null_delivery  # noqa: PLC0415

        changed = await self._branch_changed_files(result)
        return is_null_delivery(changed)

    async def _branch_changed_files(self, result: WorkerResult) -> list[str]:
        """Return the changed file paths of the result's branch vs base, or []."""
        if not result.workspace_path or not Path(result.workspace_path).is_dir():
            return []
        runner = getattr(self._agents, "_runner", None)
        run_simple = getattr(runner, "run_simple", None) if runner else None
        if run_simple is None:
            return []
        return await compute_branch_changed_files(
            Path(result.workspace_path),
            result.branch,
            self._config.base_branch(),
            runner_run_simple=run_simple,
            timeout=self._config.git_command_timeout,
        )

    async def _handle_null_delivery(
        self, issue: Task, result: WorkerResult
    ) -> WorkerResult:
        """Handle a null-delivery failure: no PR, mark failed, allow retry.

        Mirrors ``_handle_zero_commits`` — the attempt-cap mechanism retries
        with corrective ``prior_failure`` context rather than escalating
        immediately.
        """
        attempts = self._state.get_issue_attempts(issue.id)
        logger.warning(
            "Issue #%d: null delivery (diagrams/auto-generated only) "
            "after implementation (attempt %d/%d)",
            issue.id,
            attempts,
            self._config.max_issue_attempts,
        )
        await self._transitioner.post_comment(
            issue.id,
            "## Implementation Failed — Null Delivery\n\n"
            "The implementation produced only planner diagrams / "
            "auto-generated artifacts and no code, tests, or assets. "
            "No PR was opened (merging one would have falsely closed this "
            f"issue). Attempt {attempts}/{self._config.max_issue_attempts}.\n\n"
            "---\n"
            "*Generated by HydraFlow Implementer*",
        )
        self._state.mark_issue(issue.id, "failed")
        return result

    async def _run_spec_compliance_review(
        self, issue: Task, result: WorkerResult
    ) -> None:
        """Run spec-compliance review on a failed attempt (ADR-0063 W5).

        Best-effort, never raises (except auth/credit/bug exceptions which
        propagate through the reviewer module). On success, persists gaps
        into ``WorkerResultMeta.spec_review_gaps`` for the next attempt.

        Skips silently when:
        - the kill-switch ``implement_two_stage_review_enabled`` is False
        - no ``spec_reviewer`` was wired into ``__init__``
        - the issue has already reached the attempt cap (no next attempt
          will run, so gathering gaps wastes a subagent dispatch)
        """
        if not self._config.implement_two_stage_review_enabled:
            return
        if self._spec_reviewer is None:
            return
        attempts = self._state.get_issue_attempts(issue.id)
        if attempts >= self._config.max_issue_attempts:
            # The next call to _check_attempt_cap will escalate this issue
            # to HITL; the gaps would never be read.
            return

        diff = await self._compute_diff_for_review(result)
        plan = self._read_plan_for_recording(issue.id)
        inp = SpecReviewInput(
            issue_number=issue.id,
            issue_title=issue.title,
            issue_body=issue.body or "",
            plan=plan,
            diff=diff,
            commits=result.commits,
            error=result.error or "",
        )

        try:
            review = await self._spec_reviewer.review(inp)
        except Exception as exc:
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            reraise_on_credit_or_bug(exc)
            log_exception_with_bug_classification(
                logger,
                exc,
                f"Spec-compliance review failed for issue #{issue.id}",
            )
            return

        if review.degraded:
            logger.info(
                "Spec-compliance reviewer degraded for issue #%d — "
                "falling through to prior_failure-only retry",
                issue.id,
            )
            return

        if review.compliant or not review.gaps:
            logger.info(
                "Spec-compliance review found no gaps for issue #%d "
                "(failure mode is not spec drift)",
                issue.id,
            )
            return

        formatted = format_gaps_for_prior_failure(review.gaps, review.reasoning)
        self._persist_spec_review_gaps(issue.id, formatted)
        await self._post_spec_review_comment(issue, review.gaps, review.reasoning)
        logger.info(
            "Spec-compliance review captured %d gap(s) for issue #%d — "
            "will be fed into next attempt",
            len(review.gaps),
            issue.id,
        )

    async def _compute_diff_for_review(self, result: WorkerResult) -> str:
        """Return the unified diff of the result's branch vs base, or ''."""
        if not result.workspace_path:
            return ""
        if not Path(result.workspace_path).is_dir():
            return ""
        # AgentRunner exposes a ``_runner`` with run_simple — use it via the
        # injected agents instance so we share the same subprocess plumbing.
        runner = getattr(self._agents, "_runner", None)
        run_simple = getattr(runner, "run_simple", None) if runner else None
        if run_simple is None:
            return ""
        return await compute_branch_diff(
            Path(result.workspace_path),
            result.branch,
            self._config.base_branch(),
            runner_run_simple=run_simple,
            timeout=self._config.git_command_timeout,
        )

    def _persist_spec_review_gaps(self, issue_id: int, formatted: str) -> None:
        """Update WorkerResultMeta with spec_review_gaps, preserving other fields."""
        meta = dict(self._state.get_worker_result_meta(issue_id) or {})
        meta["spec_review_gaps"] = formatted
        self._state.set_worker_result_meta(issue_id, meta)  # type: ignore[arg-type]

    async def _post_spec_review_comment(
        self, issue: Task, gaps: list[str], reasoning: str
    ) -> None:
        """Post the spec-compliance review verdict as an issue comment."""
        lines = ["## Spec-Compliance Review (ADR-0063 W5)\n"]
        lines.append(
            "The previous implementation attempt failed. A spec-compliance "
            "reviewer ran against the diff and surfaced these gaps; the next "
            "attempt will see them as prior-failure context.\n"
        )
        for g in gaps:
            lines.append(f"- {g}")
        if reasoning.strip():
            lines.append("")
            lines.append(f"**Reasoning.** {reasoning.strip()}")
        lines.append("\n---\n*Generated by HydraFlow ImplementPhase*")
        try:
            await self._transitioner.post_comment(issue.id, "\n".join(lines))
        except Exception as exc:
            log_exception_with_bug_classification(
                logger,
                exc,
                f"Failed to post spec-review comment for issue #{issue.id}",
            )

    async def _flag_requirements_gaps(self, issue: Task, transcript: str) -> None:
        """Detect and post requirements gaps discovered during implementation."""
        from spec_match import extract_requirements_gaps  # noqa: PLC0415

        gaps = extract_requirements_gaps(transcript)
        if not gaps:
            return
        lines = ["## Requirements Gaps Discovered During Implementation\n"]
        for gap in gaps:
            lines.append(f"- **Gap:** {gap.get('gap', 'Unknown')}")
            if gap.get("impact"):
                lines.append(f"  - Impact: {gap['impact']}")
            if gap.get("assumption"):
                lines.append(f"  - Assumption made: {gap['assumption']}")
        lines.append(
            "\n*These gaps were flagged by the implementation agent. "
            "Review whether the spec needs updating.*"
        )
        await self._prs.post_comment(issue.id, "\n".join(lines))
        logger.info(
            "Issue #%d: %d requirements gaps flagged during implementation",
            issue.id,
            len(gaps),
        )

    async def _handle_zero_commits(
        self, issue: Task, result: WorkerResult
    ) -> WorkerResult:
        """Handle a zero-commit failure on the retry path.

        Reached only when ``zero-commit-abort`` fell through — the abort is
        disabled (``implement_no_progress_abort_attempts == 0``) or this
        attempt is below its threshold (#11568). Marks as failed so the
        attempt-cap mechanism can retry with corrective context
        (prior_failure feedback) instead of escalating immediately.
        """
        attempts = self._state.get_issue_attempts(issue.id)
        logger.warning(
            "Issue #%d: zero commits after implementation (attempt %d/%d)",
            issue.id,
            attempts,
            self._config.max_issue_attempts,
        )
        await self._transitioner.post_comment(
            issue.id,
            "## Implementation Failed — Zero Commits\n\n"
            "The implementation agent ran but produced no commits. "
            f"Attempt {attempts}/{self._config.max_issue_attempts}.\n\n"
            "---\n"
            "*Generated by HydraFlow Implementer*",
        )
        self._state.mark_issue(issue.id, "failed")
        return result

    async def _resolve_pr(
        self, issue: Task, result: WorkerResult, is_retry: bool
    ) -> PRInfo | None:
        """Create a new PR or recover an existing one, updating result.pr_info."""
        if not is_retry:
            if await self._ensure_fresh_base(issue, result):
                gh_issue = GitHubIssue.from_task(issue)
                pr = await self._prs.create_pr(gh_issue, result.branch)
            else:
                # Base-freshness guard refused (#10101): the zero-PR sentinel
                # routes through the existing "implementation succeeded but
                # no PR exists" fallback (_handle_no_pr_fallback), which
                # keeps the issue in the ready queue for retry instead of
                # silently opening a born-red PR against a stale base.
                pr = PRInfo(number=0, issue_number=issue.id, branch=result.branch)
        else:
            pr = await self._prs.find_open_pr_for_branch(
                result.branch, issue_number=issue.id
            )
            if pr is not None and pr.number > 0:
                from pr_manager import PRManager as _PRManager  # noqa: PLC0415

                expected_title = _PRManager.expected_pr_title(issue.id, issue.title)
                await self._prs.update_pr_title(pr.number, expected_title)
        result.pr_info = pr
        return pr

    @staticmethod
    async def _run_git_read(
        run_simple: Callable[..., Awaitable[object]],
        cmd: list[str],
        *,
        cwd: str,
        timeout: float,
    ) -> str | None:
        """Run a local read-only git command; stripped stdout, or None on any failure.

        Shared by ``_merge_base_age_days``'s two reads. A non-string
        ``stdout`` (e.g. an unconfigured test double) fails open the same
        as a real git error — this helper must never raise.
        """
        try:
            out = await run_simple(cmd, cwd=cwd, timeout=timeout)
        except (TimeoutError, FileNotFoundError, OSError):
            return None
        stdout = getattr(out, "stdout", "")
        if not isinstance(stdout, str):
            return None
        return stdout.strip()

    async def _merge_base_age_days(self, result: WorkerResult) -> float | None:
        """Return the age in days of *result.branch*'s merge-base with the base branch.

        Mirrors ``_branch_changed_files``: reads locally via the agent
        runner's ``run_simple`` so it works uniformly under host/Docker
        execution without a dedicated Port (#10101). Fails open (returns
        ``None``) on any git error, a missing runner, or an unparsable
        result — a freshness check must never itself block a PR.
        """
        if not result.workspace_path or not Path(result.workspace_path).is_dir():
            return None
        runner = getattr(self._agents, "_runner", None)
        run_simple = getattr(runner, "run_simple", None) if runner else None
        if run_simple is None:
            return None
        base = self._config.base_branch()
        timeout = self._config.git_command_timeout
        sha = await self._run_git_read(
            run_simple,
            ["git", "merge-base", result.branch, f"origin/{base}"],
            cwd=result.workspace_path,
            timeout=timeout,
        )
        if not sha:
            return None
        ts_str = await self._run_git_read(
            run_simple,
            ["git", "log", "-1", "--format=%ct", sha],
            cwd=result.workspace_path,
            timeout=timeout,
        )
        if not ts_str or not ts_str.isdigit():
            return None
        epoch = int(ts_str)
        return max(time.time() - epoch, 0.0) / 86400.0

    async def _ensure_fresh_base(self, issue: Task, result: WorkerResult) -> bool:
        """Refuse or auto-update a stale merge-base before ``gh pr create`` (#10101).

        The #9964 class: a long-lived implementer worktree forks from the
        base branch once at worktree-creation time, then the agent runs for
        however long it takes. New guard rules landed on the base in the
        meantime are invisible to the branch — its PR opens born-red
        against a base that's since drifted. Computes the branch's
        merge-base age with the configured base branch; when it exceeds
        ``pr_base_max_age_days`` this tries an in-place update (fetch +
        merge, reusing the same ``merge_main`` path as post-PR conflict
        resolution) before falling back to refusing the PR open.

        Returns True when it's safe to proceed with ``create_pr``.
        """
        if not self._config.pr_base_freshness_guard_enabled:
            return True
        age_days = await self._merge_base_age_days(result)
        if age_days is None or age_days <= self._config.pr_base_max_age_days:
            return True
        logger.warning(
            "Issue #%d: branch %s has a %.1f-day-old merge-base with %s "
            "(threshold %d days) — attempting auto-update before PR open",
            issue.id,
            result.branch,
            age_days,
            self._config.base_branch(),
            self._config.pr_base_max_age_days,
        )
        updated = False
        if result.workspace_path:
            try:
                updated = bool(
                    await self._workspaces.merge_main(
                        Path(result.workspace_path), result.branch
                    )
                )
            except (RuntimeError, OSError):
                updated = False
            if updated:
                updated = bool(
                    await self._prs.push_branch(
                        Path(result.workspace_path), result.branch
                    )
                )
        if updated:
            logger.info(
                "Issue #%d: base-freshness guard auto-updated %s to a fresh %s",
                issue.id,
                result.branch,
                self._config.base_branch(),
            )
            return True
        logger.warning(
            "Issue #%d: base-freshness guard could not auto-update %s "
            "(merge conflict or push failure) — refusing PR open",
            issue.id,
            result.branch,
        )
        return False

    async def _handle_successful_push(
        self, issue: Task, result: WorkerResult, is_retry: bool
    ) -> WorkerResult | None:
        """Create/find PR after a successful push.

        Returns a ``WorkerResult`` to short-circuit the caller when the
        outcome is fully resolved (PR-less failure or zero-diff escalation).
        Returns ``None`` when the caller should continue to the final
        status-marking step.

        On a fresh attempt with ``result.success`` False, returns ``None``
        without resolving a PR. Creating a PR for failed work caused
        state-machine drift: the issue stayed at ``hydraflow-ready`` while
        the PR sat unlabeled. The attempt-cap mechanism retries with
        ``prior_failure`` feedback. Retry path is unchanged.
        """
        if not result.success and not is_retry:
            return None

        pr = await self._resolve_pr(issue, result, is_retry)

        if result.success and (pr is None or pr.number <= 0):
            return await self._handle_no_pr_fallback(issue, result)

        if result.success:
            self._store.enqueue_transition(issue, "review")
            await self._transitioner.transition(
                issue.id,
                "review",
                pr_number=pr.number if pr and pr.number > 0 else None,
            )
            self._state.increment_session_counter("implemented")

        return None

    async def _escalate_no_changes_to_hitl(
        self, issue: Task, result: WorkerResult
    ) -> WorkerResult:
        """Escalate to HITL when the branch has no diff from main."""
        logger.warning(
            "Issue #%d: agent claimed success but branch has no diff — escalating as failure",
            issue.id,
        )
        await self._transitioner.post_comment(
            issue.id,
            "## Implementation Failed — No Changes Detected\n\n"
            "The implementation agent reported success but the branch "
            "has no diff from main. The agent likely concluded no work "
            "was needed incorrectly.\n\n"
            "Escalating for human review.\n\n"
            "---\n"
            "*Generated by HydraFlow Implementer*",
        )
        self._state.mark_issue(issue.id, "failed")
        context = EscalationContext(
            cause=self._hitl_cause(
                issue, "implementation produced no changes (zero diff)"
            ),
            origin_phase="implement",
            agent_transcript=result.transcript if result.transcript else None,
        )
        await self._escalator(
            issue,
            cause=context.cause,
            details="Implementation produced no changes (zero diff)",
            category=FailureCategory.HITL_ESCALATION,
            context=context,
        )
        if result.transcript:
            await self._suggest_memory(
                result.transcript,
                "implement_zero_diff",
                f"issue #{issue.id}",
            )
            self._zero_diff_memory_filed.add(issue.id)
        return result

    async def _handle_no_pr_fallback(
        self, issue: Task, result: WorkerResult
    ) -> WorkerResult:
        """Handle the case where implementation succeeded but no PR exists.

        If the branch has no diff from main, escalates to HITL.  Otherwise the
        work was really committed and pushed — the PR-open step just never ran
        (e.g. a long local verification step got reaped by a subprocess timeout
        AFTER commit+push but BEFORE ``gh pr create``; issue #10493). Recover
        idempotently instead of discarding the delivered work: re-check for an
        open PR, then open one from the already-pushed branch, mirroring the
        happy path. Only a genuine PR-open failure falls through to the "mark
        failed / retry" path (which would rebuild the work from scratch).
        """
        has_diff = await self._prs.branch_has_diff_from_main(result.branch)
        if not has_diff:
            return await self._escalate_no_changes_to_hitl(issue, result)

        # Idempotent recovery (#10493): the branch carries a real diff and is
        # already pushed on origin, so deliver it rather than bouncing the
        # issue back to hydraflow-ready for a full rebuild. A PR may have been
        # created since the initial resolve; otherwise open one now from the
        # pushed branch (the same call the happy path uses in _resolve_pr).
        pr = await self._prs.find_open_pr_for_branch(
            result.branch, issue_number=issue.id
        )
        if pr is None or pr.number <= 0:
            gh_issue = GitHubIssue.from_task(issue)
            pr = await self._prs.create_pr(gh_issue, result.branch)

        if pr is not None and pr.number > 0:
            logger.info(
                "Recovered PR #%d for issue #%d from already-pushed branch %s "
                "(no PR existed after successful implementation)",
                pr.number,
                issue.id,
                result.branch,
            )
            # Mirror the happy-path post-create state marking so the delivered
            # work advances to review instead of being rebuilt: enqueue +
            # drive the review transition, bump the session counter, and mark
            # the issue "success" (what _handle_successful_push's caller does).
            self._store.enqueue_transition(issue, "review")
            await self._transitioner.transition(issue.id, "review", pr_number=pr.number)
            self._state.increment_session_counter("implemented")
            self._state.mark_issue(issue.id, "success")
            result.success = True
            result.pr_info = pr
            result.error = None
            return result

        logger.warning(
            "Implementation succeeded for issue #%d but PR recovery failed for "
            "branch %s — keeping in ready queue for retry",
            issue.id,
            result.branch,
        )
        await self._transitioner.post_comment(
            issue.id,
            "PR creation/recovery failed after successful implementation. "
            "Keeping issue in ready queue for retry.",
        )
        self._state.mark_issue(issue.id, "failed")
        result.success = False
        if not result.error:
            result.error = "PR creation failed"
        return result

    def _prepare_adr_plan(self, issue: Task) -> None:
        """Seed a deterministic ADR execution plan when an ADR issue lacks one."""
        if not is_adr_issue_title(issue.title):
            return

        plan_path = self._config.plans_dir / f"issue-{issue.id}.md"
        if plan_path.exists():
            return

        # Reserve a unique ADR number by scanning the primary repo (not the
        # worktree copy) and the in-process assignment set.
        primary_adr_dir = self._config.repo_root / "docs" / "adr"
        adr_number = next_adr_number(primary_adr_dir)
        adr_number_str = f"{adr_number:04d}"

        body = issue.body.strip() or "No ADR draft body provided."
        plan_text = (
            "## Implementation Plan\n\n"
            f"1. Create a single ADR markdown file named "
            f"`docs/adr/{adr_number_str}-<slug>.md` (ADR number "
            f"**{adr_number_str}** is pre-assigned — do NOT pick a different "
            f"number).\n"
            "2. Preserve and refine the ADR sections (`Context`, `Decision`, "
            "`Consequences`) using the issue draft as source material.\n"
            "3. Ensure the ADR content is actionable and concrete enough for "
            "review (explicit decision, tradeoffs, and impact).\n"
            "4. Add/update references so the ADR links back to this issue.\n"
            "   - Anywhere in the ADR (Related, Context, Decision, Consequences), "
            "cite source files by function/class name only "
            "(e.g. `src/config.py:_resolve_base_paths`). Do NOT include line numbers — "
            "they become stale as source files change.\n"
            "5. **Do NOT create tests for ADR markdown content.** ADRs are "
            "documentation — never add `test_adr_*.py` files that assert on "
            "headings, status, or prose.\n\n"
            "## ADR Draft From Issue\n\n"
            f"{body}\n"
        )
        try:
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(plan_text)
            logger.info(
                "Prepared ADR implementation plan fallback for issue #%d at %s",
                issue.id,
                plan_path,
            )
        except OSError:
            logger.warning(
                "Failed to prepare ADR plan fallback for issue #%d",
                issue.id,
                exc_info=True,
            )
