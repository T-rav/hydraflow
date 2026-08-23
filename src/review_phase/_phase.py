"""Main ``ReviewPhase`` class.

Split out of the original ``src/review_phase.py`` (T36) for file-size
discipline. The module-level constants, dataclasses, regex patterns, and
standalone helper functions live in ``_common.py``; this file holds the
``ReviewPhase`` class body unchanged.

External callers continue to import via ``from review_phase import ReviewPhase``
— see ``__init__.py`` for back-compat re-exports.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

# Light, pure, cycle-free (review_advisor imports it at module top too) —
# the #10836 phase-2 subject-join helpers both advisor constructions need.

if TYPE_CHECKING:
    from issue_cache import IssueCache
    from ports import IssueStorePort, PRPort, ReviewInsightStorePort, WorkspacePort
    from precondition_gate import PreconditionGate
    from retrospective_queue import RetrospectiveQueue
    from review_advisor import (  # noqa: TCH004 — used in __init__ + sig
        ReviewPlan,
    )
    from visual_validator import VisualValidator
    from wiki_compiler import (  # noqa: TCH004 — used in __init__ signature
        WikiCompiler,
    )


# Late-binding access for symbols that tests patch via
# ``unittest.mock.patch("review_phase.<name>")``. The patch installs the
# mock on the package module object, so call sites must look up the
# attribute at *call time* rather than caching a local binding at import
# time. Today this covers ``record_harness_failure`` and
# ``analyze_patterns``; if you add another patchable name, expose it from
# ``__init__.py`` and reference it as ``review_phase.<name>`` here.
#
# ``import review_phase`` is circular-safe: the package is already in
# ``sys.modules`` (partially initialized) when this submodule loads, so
# the bound name resolves to the same module object the patch will
# mutate later. Attribute access at call time sees the fully-loaded
# package.
# Late-binding access for symbols that tests patch via
# ``unittest.mock.patch("review_phase.<name>")``. The patch installs the
# mock on the package module object, so call sites must look up the
# attribute at *call time* rather than caching a local binding at
# import time. Today this covers ``record_harness_failure`` and
# ``analyze_patterns``; if you add another patchable name, expose it
# from ``__init__.py`` and reference it as ``review_phase.<name>``.
#
# ``import review_phase`` is circular-safe: the package is already in
# ``sys.modules`` (partially initialized) when this submodule loads, so
# the bound name resolves to the same module object the patch mutates
# later. Attribute access at call time sees the fully-loaded package.
import review_phase  # noqa: E402, F401  — used by call sites below
from baseline_policy import BaselinePolicy
from comment_formatter import SelfReviewError
from config import HydraFlowConfig
from events import EventBus
from exception_classify import reraise_on_credit_or_bug
from harness_insights import FailureCategory, HarnessInsightStore
from merge_conflict_resolver import MergeConflictResolver
from models import (
    BaselineApprovalResult,
    CodeScanningAlert,
    ConflictResolutionResult,
    JudgeResult,
    PipelineStage,
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    StatusCallback,
    Task,
)
from phase_utils import (
    MemorySuggester,
    _sentry_transaction,
    log_exception_with_bug_classification,
    release_batch_in_flight,
    run_concurrent_batch,
    run_with_fatal_guard,
    store_lifecycle,
)
from post_merge_handler import PostMergeHandler
from repo_wiki import (
    RepoWikiStore,
)
from reviewer import ReviewRunner
from state import StateTracker
from task_source import TaskTransitioner
from transcript_summarizer import TranscriptSummarizer

# One cohesive slice of ``ReviewPhase`` per module, each extracted verbatim
# and mixed back in by inheritance so the public surface is unchanged — every
# moved method still resolves as an attribute of ``ReviewPhase`` exactly as
# before, and class-level patching in tests still lands. ``_visual_gate`` came
# from the #10840 god-file pass; the rest from the Refs #11547 god-class pass.
from ._adr import AdrReviewMixin
from ._advisors import AdvisorMixin
from ._ci import CiWaitMixin
from ._common import (
    _is_meaningful_verdict,
)
from ._flow import ReviewFlowMixin
from ._insights import ReviewInsightsMixin
from ._judge import ConvergenceJudgeMixin
from ._outcome import ReviewOutcomeMixin
from ._self_fix import SelfFixMixin
from ._ultra import UltraReviewMixin
from ._visual_gate import VisualGateMixin
from ._wiki_ingest import WikiIngestMixin

logger = logging.getLogger("hydraflow.review_phase")


class ReviewPhase(
    AdrReviewMixin,
    AdvisorMixin,
    CiWaitMixin,
    ConvergenceJudgeMixin,
    ReviewFlowMixin,
    ReviewInsightsMixin,
    ReviewOutcomeMixin,
    SelfFixMixin,
    UltraReviewMixin,
    VisualGateMixin,
    WikiIngestMixin,
):
    """Runs reviewer agents on PRs, merging approved ones inline.

    What stays in ``_phase.py`` is the spine: construction, the ``review_prs``
    batch entry point, the per-PR ``_review_one_inner`` scaffolding, the
    worktree/merge plumbing, and the delegate properties tests bind to. Every
    other slice lives in a sibling mixin module (Refs #11547) and is part of
    this class by inheritance, so the public surface is unchanged.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        workspaces: WorkspacePort,
        reviewers: ReviewRunner,
        prs: PRPort,
        stop_event: asyncio.Event,
        store: IssueStorePort,
        conflict_resolver: MergeConflictResolver,
        post_merge: PostMergeHandler,
        review_insights: ReviewInsightStorePort,
        event_bus: EventBus | None = None,
        harness_insights: HarnessInsightStore | None = None,
        update_bg_worker_status: StatusCallback | None = None,
        baseline_policy: BaselinePolicy | None = None,
        active_issues_cb: Callable[[], None] | None = None,
        transcript_summarizer: TranscriptSummarizer | None = None,
        wiki_store: RepoWikiStore | None = None,
        wiki_compiler: WikiCompiler | None = None,
        retrospective_queue: RetrospectiveQueue | None = None,
        precondition_gate: PreconditionGate | None = None,
        issue_cache: IssueCache | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._workspaces = workspaces
        self._reviewers = reviewers
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._stop_event = stop_event
        self._store = store
        self._bus = event_bus or EventBus()
        self._suggest_memory = MemorySuggester(config)
        self._summarizer = transcript_summarizer
        self._wiki_store = wiki_store
        self._wiki_compiler = wiki_compiler
        self._update_bg_worker_status = update_bg_worker_status
        self._harness_insights = harness_insights
        self._insights: ReviewInsightStorePort = review_insights
        self._active_issues_cb = active_issues_cb
        self._active_issues: set[int] = set()
        # In-memory window guard for the stale-insight fallback branch
        # (mirror of ``RetrospectiveLoop._insight_escalated_at``). Two PR
        # reviews completing back-to-back for the same stale category
        # could otherwise both call ``find_existing_issue`` before
        # either write is indexed by GitHub search, and both file.
        self._insight_escalated_at: dict[str, datetime] = {}
        self._active_issues_lock = asyncio.Lock()
        self._conflict_resolver = conflict_resolver
        self._post_merge = post_merge
        self._baseline_policy = baseline_policy
        self._retrospective_queue = retrospective_queue
        self._precondition_gate = precondition_gate
        self._issue_cache = issue_cache
        self._visual_validator: VisualValidator | None = None
        if config.visual_validation_enabled:
            from visual_validator import VisualValidator  # noqa: PLC0415

            self._visual_validator = VisualValidator(config)

        # Per-PR advisor retry counter — incremented on VETO. Used by
        # PRContext to pass prior_fix_attempts to the composite trigger.
        self._advisor_attempt: dict[int, int] = {}
        # Per-PR list of advisor PostVerifyResults collected this run. The
        # transcript hand-back to the executor (on VETO) is rendered from
        # this list. T12 will replace this with persistent advisor_session.jsonl.
        self._advisor_results: dict[int, list[Any]] = {}
        # Per-surface pre-flight ReviewPlan, captured by
        # ``_run_pre_flight_advisor`` before the executor runs and threaded
        # into both the executor's review prompt and the post-verify
        # advisor's input. Reset on every ``_review_one_inner`` entry so
        # plans don't leak across reviews.
        #
        # Keyed by ``(surface, identifier)`` (T38) so per-surface plans
        # don't collide when identifier sequences overlap — e.g., ADR-on-fork
        # renumbering, third-party adapters with their own counters, or any
        # future surface that doesn't share GitHub's global PR/issue sequence.
        # In production today PR numbers and issue numbers come from disjoint
        # segments of one sequence so the int-keyed dict was safe in practice,
        # but the tuple key removes the "could be either id" ambiguity at
        # read sites.
        self._advisor_pre_flight_plan: dict[tuple[str, int], ReviewPlan] = {}
        self._post_verify_runner = self._build_post_verify_runner()
        # Opt-in ultra deep-review tier (#10555). Default OFF via
        # config.review_ultra_enabled; the runner is always built (cheap) but
        # only invoked when should_ultra_review() opens the gate.
        self._ultra_runner = self._build_ultra_runner()

    _WIKI_INGEST_MAX_CHARS = 40_000

    @property
    def active_issues(self) -> set[int]:
        return self._active_issues

    async def post_review_transcript_hooks(
        self, review_results: list[ReviewResult]
    ) -> None:
        """File memory suggestions and post transcript summaries for review results."""
        for result in review_results:
            if not result.transcript:
                continue
            if result.merged:
                review_status = "success"
            elif result.ci_passed is False:
                review_status = "failed"
            else:
                review_status = "completed"
            await self._post_review_transcript(result, status=review_status)

    async def _post_review_transcript(
        self, result: ReviewResult, *, status: str
    ) -> None:
        """File memory suggestion and post transcript summary for a single review."""
        if result.transcript:
            await self._suggest_memory(
                result.transcript, "reviewer", f"PR #{result.pr_number}"
            )
        if self._summarizer and result.transcript and result.issue_number > 0:
            try:
                await self._summarizer.summarize_and_comment(
                    transcript=result.transcript,
                    issue_number=result.issue_number,
                    phase="review",
                    status=status,
                    duration_seconds=result.duration_seconds,
                    log_file=self._review_log_reference(result.pr_number),
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

    def _review_log_reference(self, pr_number: int) -> str:
        """Return a display-friendly log path for reviewer transcripts."""
        log_path = self._config.log_dir / f"review-pr-{pr_number}.txt"
        return self._config.format_path_for_display(log_path)

    async def review_prs(
        self,
        prs: list[PRInfo],
        issues: list[Task],
    ) -> list[ReviewResult]:
        """Run reviewer agents on non-draft PRs, merging approved ones inline."""
        if not prs:
            return []

        # Apply the precondition gate (#6423) before reviewing. Issues
        # whose plan/review records are missing get routed back to the
        # ready stage; only PRs whose underlying issues pass the gate
        # are reviewed in this cycle.
        if self._precondition_gate is not None:
            from stage_preconditions import Stage  # noqa: PLC0415

            gated = await self._precondition_gate.filter_and_route(issues, Stage.REVIEW)
            gated_ids = {i.id for i in gated}
            issues = gated
            prs = [pr for pr in prs if pr.issue_number in gated_ids]
            if not prs:
                return []

        # Skip term-proposer / term-pruner / edge-proposer PRs (handled by
        # DependabotMergeLoop, ADR-0054 / ADR-0057 / ADR-0058 / ADR-0062).
        # All four loops open auto-merging bot PRs whose content is purely
        # generated; the agent pipeline must not route them.
        #
        # Also skip PRs carrying adversarial-pipeline transient labels
        # (Task 10 of earlier-adversarial-pipeline). These labels are
        # intra-stage issue markers, not review work — if one ever leaks
        # onto a PR, the agent reviewer should not process it.
        from adversarial_labels import (  # noqa: PLC0415
            LABELS_ADVERSARIAL_TRANSIENT,
        )
        from edge_proposer_loop import EDGE_PROPOSER_PR_LABEL  # noqa: PLC0415
        from entry_evidence_loop import ENTRY_EVIDENCE_PR_LABEL  # noqa: PLC0415
        from term_proposer_loop import TERM_PROPOSER_PR_LABEL  # noqa: PLC0415
        from term_pruner_loop import TERM_PRUNER_PR_LABEL  # noqa: PLC0415

        _skip_pr_labels = {
            TERM_PROPOSER_PR_LABEL,
            TERM_PRUNER_PR_LABEL,
            EDGE_PROPOSER_PR_LABEL,
            ENTRY_EVIDENCE_PR_LABEL,
        } | set(LABELS_ADVERSARIAL_TRANSIENT)
        prs = [pr for pr in prs if not (set(pr.labels or []) & _skip_pr_labels)]
        if not prs:
            logger.debug(
                "review_phase: all PRs filtered out "
                "(term-proposer/pruner/edge-proposer/entry-evidence "
                "or adversarial-transient candidates)"
            )
            return []

        issue_map = {i.id: i for i in issues}
        semaphore = asyncio.Semaphore(self._config.max_reviewers)

        async def _review_one(idx: int, pr: PRInfo) -> ReviewResult:
            """Review a single PR under the concurrency semaphore."""
            if self._stop_event.is_set():
                return ReviewResult(
                    pr_number=pr.number,
                    issue_number=pr.issue_number,
                    summary="stopped",
                )
            async with semaphore:
                if self._stop_event.is_set():
                    return ReviewResult(
                        pr_number=pr.number,
                        issue_number=pr.issue_number,
                        summary="stopped",
                    )
                async with self._active_issues_lock:
                    self._active_issues.add(pr.issue_number)
                    if self._active_issues_cb:
                        self._active_issues_cb()
                with _sentry_transaction("pipeline.review", f"review:PR#{pr.number}"):
                    async with store_lifecycle(self._store, pr.issue_number, "review"):
                        try:
                            return await run_with_fatal_guard(
                                self._review_one_inner(idx, pr, issue_map),
                                on_failure=lambda exc_name: ReviewResult(
                                    pr_number=pr.number,
                                    issue_number=pr.issue_number,
                                    summary=f"Review failed due to unexpected error ({exc_name})",
                                ),
                                context=f"Review failed for PR #{pr.number} (issue #{pr.issue_number})",
                                log=logger,
                            )
                        finally:
                            await self._publish_review_status(pr, idx, "done")
                            async with self._active_issues_lock:
                                self._active_issues.discard(pr.issue_number)
                                if self._active_issues_cb:
                                    self._active_issues_cb()

        try:
            results = await run_concurrent_batch(prs, _review_one, self._stop_event)
        finally:
            release_batch_in_flight(self._store, {pr.issue_number for pr in prs})

        # Mirror review verdicts into the issue cache as review_stored
        # records (#6422 + #6421). The READY-stage precondition gate
        # for downstream PR-driven re-review reads has_blocking from
        # these records. Only meaningful verdicts produce a cache
        # record:
        #   APPROVE          → has_blocking=False (good to go)
        #   REQUEST_CHANGES  → has_blocking=True  (must re-review)
        # No-verdict / stopped / errored results are SKIPPED entirely
        # so they cannot poison a downstream gate by silently caching
        # has_blocking=False for a review that never actually ran.
        # See _is_meaningful_verdict for the skip rules.
        if self._issue_cache is not None:
            for result in results:
                if result.issue_number <= 0:
                    continue
                if not _is_meaningful_verdict(result):
                    continue
                try:
                    self._issue_cache.record_review_stored(
                        result.issue_number,
                        review_text=result.summary,
                        has_blocking=(result.verdict == ReviewVerdict.REQUEST_CHANGES),
                    )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Failed to write review_stored cache record for issue #%d",
                        result.issue_number,
                        exc_info=True,
                    )

        return results

    async def _prepare_review_worktree(
        self, pr: PRInfo, task: Task, idx: int
    ) -> Path | None:
        """Ensure worktree exists and main is merged. Returns path or None on conflict."""
        wt_path = self._config.workspace_path_for_issue(pr.issue_number)
        if not wt_path.exists():
            wt_path = await self._workspaces.create(pr.issue_number, pr.branch)
        merged = await self._merge_with_main(pr, task, wt_path, idx)
        if not merged:
            return None
        return wt_path

    async def _fetch_code_scanning_alerts(
        self, pr: PRInfo
    ) -> list[CodeScanningAlert] | None:
        """Fetch code scanning alerts for the PR branch.

        Returns the alert list or ``None`` on error.
        """
        try:
            alerts = await self._prs.fetch_code_scanning_alerts(pr.branch)
            if alerts:
                logger.info(
                    "PR #%d: fetched %d code scanning alert(s)",
                    pr.number,
                    len(alerts),
                )
            return alerts or None
        except (RuntimeError, OSError):
            logger.debug(
                "Could not fetch code scanning alerts for PR #%d",
                pr.number,
                exc_info=True,
            )
            return None

    async def _check_baseline_policy(
        self, pr: PRInfo, task: Task
    ) -> BaselineApprovalResult | None:
        """Run baseline policy check if a policy is configured.

        Returns the approval result or ``None`` when no policy is active.
        """
        if self._baseline_policy is None:
            return None
        try:
            changed_files = await self._prs.get_pr_diff_names(pr.number)
            if not changed_files:
                return None
            pr_approvers = await self._prs.get_pr_approvers(pr.number)
            commit_sha = await self._prs.get_pr_head_sha(pr.number)
            return await self._baseline_policy.check_approval(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                changed_files=changed_files,
                pr_approvers=pr_approvers,
                commit_sha=commit_sha,
            )
        except (RuntimeError, OSError):
            logger.warning(
                "Baseline policy check failed for PR #%d — failing closed to protect baseline integrity",
                pr.number,
                exc_info=True,
            )
            return BaselineApprovalResult(
                approved=False,
                requires_approval=True,
                reason="Baseline policy check failed — manual review required",
            )

    async def _review_one_inner(
        self,
        idx: int,
        pr: PRInfo,
        issue_map: dict[int, Task],
        surface: str = "pr_review",
    ) -> ReviewResult:
        """Core review logic for a single PR — called inside the semaphore.

        ``surface`` defaults to ``"pr_review"`` for back-compat (T24.7 prep
        for Phase 4). Phase 4 outer helpers may invoke this with other
        surface names; the surface is threaded through the advisor and
        executor prompt-building call sites.

        Runs the per-PR review pipeline as an explicit ``src.flows.Flow`` (P3b
        of #10682, ADR-0111): ``guards -> pre-review -> pre-flight -> review ->
        post-review -> gate -> (route ->) cleanup -> done`` (see the
        module-level diagram). The reviewer tracing lifecycle stays here in the
        outer scaffolding; the pipeline body is the flow. Signature and
        ``ReviewResult`` return contract are unchanged — the final ``result``
        is read off the terminal state.
        """
        from trace_rollup import write_phase_rollup  # noqa: PLC0415
        from tracing_context import (  # noqa: PLC0415
            TracingContext,
            source_to_phase,
        )

        trace_phase = source_to_phase("reviewer")
        run_id = self._state.begin_trace_run(pr.issue_number, trace_phase)
        self._reviewers.set_tracing_context(
            TracingContext(
                issue_number=pr.issue_number,
                phase=trace_phase,
                source="reviewer",
                run_id=run_id,
            )
        )

        try:
            flow = self._build_review_flow()
            outcome = await flow.run(
                self._initial_review_state(idx, pr, issue_map, surface)
            )
            return outcome.state["result"]
        finally:
            self._reviewers.clear_tracing_context()
            try:
                write_phase_rollup(
                    config=self._config,
                    issue_number=pr.issue_number,
                    phase=trace_phase,
                    run_id=run_id,
                )
            except Exception:
                logger.warning(
                    "Phase rollup failed for PR #%d",
                    pr.number,
                    exc_info=True,
                )
            self._state.end_trace_run(pr.issue_number, trace_phase)

    # -- flow nodes ---------------------------------------------------------

    @staticmethod
    def _is_product_track_pr(task: Task) -> bool:
        """Check if the task came through the product discovery/shape track."""
        return any(
            "Selected Product Direction" in c or "DECOMPOSITION REQUIRED" in c
            for c in (task.comments or [])
        )

    async def _check_sha_skip_guard(self, pr: PRInfo) -> ReviewResult | None:
        """Return a skip result if no new commits since last review, else None."""
        current_sha = await self._prs.get_pr_head_sha(pr.number)
        if isinstance(current_sha, str) and current_sha:
            stored_sha = self._state.get_last_reviewed_sha(pr.issue_number)
            if stored_sha and stored_sha == current_sha:
                logger.info(
                    "PR #%d (issue #%d): skipping review — no new commits since "
                    "last review (SHA %s)",
                    pr.number,
                    pr.issue_number,
                    current_sha[:12],
                )
                return ReviewResult(
                    pr_number=pr.number,
                    issue_number=pr.issue_number,
                    summary="Skipped — no new commits since last review",
                )
        return None

    async def _record_review_outcome(self, pr: PRInfo, result: ReviewResult) -> None:
        """Record all post-review state: verdicts, SHA, duration, insights.

        Also records a harness failure for any non-APPROVE verdict.
        """
        self._state.mark_pr(pr.number, result.verdict.value)
        self._state.mark_issue(pr.issue_number, "reviewed")
        self._state.record_review_verdict(result.verdict.value, result.fixes_made)
        if result.verdict == ReviewVerdict.APPROVE:
            self._state.increment_session_counter("reviewed")

        post_review_sha = await self._prs.get_pr_head_sha(pr.number)
        if isinstance(post_review_sha, str) and post_review_sha:
            self._state.set_last_reviewed_sha(pr.issue_number, post_review_sha)

        if result.duration_seconds > 0:
            self._state.record_review_duration(result.duration_seconds)
        await self._record_review_insight(result)
        if result.verdict != ReviewVerdict.APPROVE:
            review_phase.record_harness_failure(
                self._harness_insights,
                pr.issue_number,
                FailureCategory.REVIEW_REJECTION,
                f"Review verdict: {result.verdict.value}. {result.summary[:200]}",
                stage=PipelineStage.REVIEW,
                pr_number=pr.number,
            )

    async def _cleanup_worktree(
        self, pr: PRInfo, result: ReviewResult, skip: bool
    ) -> None:
        """Destroy the worktree unless it should be preserved."""
        # Preserve worktrees for interrupted reviews so work can be resumed.
        # If the PR was already merged, the worktree is no longer needed.
        if self._stop_event.is_set() and not result.merged:
            skip = True

        if not skip:
            try:
                await self._workspaces.post_work_cleanup(
                    pr.issue_number, phase="review"
                )
                self._state.remove_workspace(pr.issue_number)
            except RuntimeError as exc:
                logger.warning(
                    "Could not clean up worktree for issue #%d: %s",
                    pr.issue_number,
                    exc,
                )

    async def _merge_with_main(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        worker_id: int,
    ) -> bool:
        """Merge main into the PR branch, resolving conflicts if needed.

        Returns True on success, False on failure (escalates to HITL).
        """
        return await self._conflict_resolver.merge_with_main(
            pr,
            issue,
            wt_path,
            worker_id,
            escalate_fn=self._escalate_to_hitl,
            publish_fn=self._publish_review_status,
        )

    def _build_bead_review_context(self, issue: Task) -> list[dict[str, object]] | None:
        """Build bead task context for the reviewer."""
        mapping = self._state.get_bead_mapping(issue.id)
        if not mapping:
            return None

        from task_graph import extract_phases  # noqa: PLC0415

        # Try to extract phases from plan comment for file/test info
        phase_info: dict[str, dict[str, object]] = {}
        for comment in issue.comments:
            phases = extract_phases(comment)
            for phase in phases:
                phase_info[phase.id] = {
                    "files": ", ".join(phase.files) or "N/A",
                    "tests": ", ".join(phase.tests) or "N/A",
                }

        bead_tasks: list[dict[str, object]] = []
        for phase_id, bead_id in sorted(mapping.items()):
            info = phase_info.get(phase_id, {})
            bead_tasks.append(
                {
                    "id": bead_id,
                    "phase": phase_id,
                    "status": "closed",  # assume closed after implementation
                    "files": info.get("files", "N/A"),
                    "tests": info.get("tests", "N/A"),
                }
            )

        return bead_tasks if bead_tasks else None

    async def _run_and_post_review(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        diff: str,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        pre_flight_plan: ReviewPlan | None = None,
        surface: str = "pr_review",
    ) -> ReviewResult:
        """Run the reviewer, push fixes, post summary, submit formal review.

        ``pre_flight_plan`` is the optional :class:`ReviewPlan` produced by
        ``PreFlightAdvisor``. When set, it is rendered into the executor's
        review prompt as a focus rubric.

        ``surface`` selects which advisor surface config drives the
        executor's mid-flight prompt assembly. Defaults to ``"pr_review"``
        for back-compat (T24.7).
        """
        # Build bead context for per-bead review when beads are enabled
        bead_tasks = self._build_bead_review_context(issue)

        # Human-on-the-loop continuous steering (ADR-0099 #4): fold live
        # operator guidance into the review prompt. Reference signal only
        # — never blocking; empty when the feature is off or no guidance
        # was posted for this issue.
        human_guidance = self._state.get_human_steering(str(issue.id)).guidance or ""

        result = await self._reviewers.review(
            pr,
            issue,
            wt_path,
            diff,
            worker_id=worker_id,
            code_scanning_alerts=code_scanning_alerts,
            bead_tasks=bead_tasks,
            pre_flight_plan=pre_flight_plan,
            surface=surface,
            human_guidance=human_guidance,
        )

        if result.fixes_made:
            await self._prs.push_branch(wt_path, pr.branch)

        if result.summary and pr.number > 0:
            await self._prs.post_pr_comment(pr.number, result.summary)
            # Ingest review feedback into the per-repo wiki
            await self._wiki_ingest_review(
                pr.issue_number,
                transcript=result.transcript,
                summary=result.summary,
            )

        if pr.number > 0 and result.verdict != ReviewVerdict.APPROVE:
            try:
                await self._prs.submit_review(pr.number, result.verdict, result.summary)
            except SelfReviewError:
                logger.info(
                    "Skipping formal %s review on own PR #%d"
                    " — already posted as comment",
                    result.verdict.value,
                    pr.number,
                )

        if result.verdict == ReviewVerdict.APPROVE:
            result = await self._check_adversarial_threshold(
                pr,
                issue,
                wt_path,
                diff,
                result,
                worker_id,
                code_scanning_alerts=code_scanning_alerts,
            )

        return result

    # ------------------------------------------------------------------
    # Approve-path gate helpers (Task 2 — convergence phase 2)
    # ------------------------------------------------------------------

    _APPROVE_GATE_LENSES: list[Literal["correctness", "security", "spec"]] = [
        "correctness",
        "security",
        "spec",
    ]

    # Delegate properties for backward compatibility in tests
    @property
    def _resolve_merge_conflicts(
        self,
    ) -> Callable[..., Coroutine[Any, Any, ConflictResolutionResult]]:
        """Backward-compatible access to conflict resolver."""
        return self._conflict_resolver.resolve_merge_conflicts

    @property
    def _get_judge_result(self) -> Callable[..., JudgeResult | None]:
        """Backward-compatible access to judge result helper."""
        return self._post_merge._get_judge_result

    @property
    def _run_post_merge_hooks(self) -> Callable[..., Coroutine[Any, Any, None]]:
        """Backward-compatible access to post-merge hooks."""
        return self._post_merge._run_post_merge_hooks

    @property
    def _save_conflict_transcript(self) -> Callable[..., None]:
        """Backward-compatible access to conflict transcript saving."""
        return self._conflict_resolver.save_conflict_transcript

    @property
    def _maybe_summarize_conflict(self) -> Callable[..., Coroutine[Any, Any, None]]:
        """Backward-compatible access to conflict summary."""
        return self._conflict_resolver._maybe_summarize_conflict
