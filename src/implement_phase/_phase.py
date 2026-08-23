"""The ``ImplementPhase`` spine.

What stays here is the public surface the orchestrator drives: construction,
the ``run_batch`` slot-filling pool that dispatches one build per free slot,
the ``_worker_inner`` / ``_handle_implementation_result`` flow entry points,
and the post-batch transcript hooks. Every other slice lives in a sibling
mixin module (Refs #11547) and is part of this class by inheritance, so the
public surface is unchanged.

External callers continue to import via ``from implement_phase import
ImplementPhase`` — see ``__init__.py`` for the back-compat re-exports.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from dispatch_overlap import DispatchOverlapTracker
from exception_classify import reraise_on_credit_or_bug
from harness_insights import FailureCategory
from models import PipelineStage, WorkerResult
from phase_utils import (
    MemorySuggester,
    PipelineEscalator,
    _sentry_transaction,
    log_exception_with_bug_classification,
    record_harness_failure,
    release_batch_in_flight,
    run_refilling_pool,
    run_with_fatal_guard,
    store_lifecycle,
)

# One cohesive slice of ``ImplementPhase`` per module, each extracted verbatim
# and mixed back in by inheritance so the public surface is unchanged — every
# moved method still resolves as an attribute of ``ImplementPhase`` exactly as
# before, and class-level patching in tests still lands (Refs #11547).
from ._abort import ImplementAbortMixin
from ._beads import ImplementBeadsMixin
from ._build import ImplementBuildMixin
from ._flow import ImplementFlowMixin
from ._pr import ImplementPRMixin
from ._screen import ImplementScreeningMixin
from ._spec_review import ImplementSpecReviewMixin

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent import AgentRunner
    from beads_manager import BeadsManager
    from config import HydraFlowConfig
    from flows import FlowState
    from harness_insights import HarnessInsightStore
    from implement_spec_reviewer import SpecComplianceReviewer
    from issue_cache import IssueCache
    from models import Task
    from ports import IssueStorePort, PRPort, WorkspacePort
    from precondition_gate import PreconditionGate
    from run_recorder import RunRecorder
    from state import StateTracker
    from task_source import TaskTransitioner
    from transcript_summarizer import TranscriptSummarizer

logger = logging.getLogger("hydraflow.implement_phase")


class ImplementPhase(
    ImplementAbortMixin,
    ImplementBeadsMixin,
    ImplementBuildMixin,
    ImplementFlowMixin,
    ImplementPRMixin,
    ImplementScreeningMixin,
    ImplementSpecReviewMixin,
):
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
                # Best-effort summary posting, but not for infra-fatal errors:
                # this path spawns an LLM, so credit/auth exhaustion here must
                # reach the loop's pause handler (#6855 class, #11666 sweep).
                reraise_on_credit_or_bug(exc)
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
                        # Best-effort summary posting, but not for infra-fatal errors:
                        # this path spawns an LLM, so credit/auth exhaustion here must
                        # reach the loop's pause handler (#6855 class, #11666 sweep).
                        reraise_on_credit_or_bug(exc)
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
