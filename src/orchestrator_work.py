"""Stage work functions of :class:`orchestrator.HydraFlowOrchestrator`.

Extracted VERBATIM from ``orchestrator.py`` (god-class decomposition, Refs
#11547) as a mixin; ``HydraFlowOrchestrator`` inherits
:class:`OrchestratorWorkMixin`.

One cohesive concern: the bodies the implement and review loops call once per
cycle — the batch hand-off to ``ImplementPhase``, the continuous slot-filling
review pool, and the #9815 orphan requeue for a review-labeled issue whose
agent PR does not exist. These are the ``work_fn`` arguments
``_polling_loop`` drives; the loops themselves live in ``orchestrator_loops``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, cast

from adr_utils import is_adr_issue_title
from models import GitHubIssue, Task
from orchestrator_common import _POST_MERGE_DELAY
from phase_utils import handle_pool_worker_exception, release_batch_in_flight

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from issue_store import IssueStore
    from service_registry import ServiceRegistry
    from state import StateTracker

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.orchestrator`` origin.
logger = logging.getLogger("hydraflow.orchestrator")


class OrchestratorWorkMixin:
    """Stage work functions of :class:`orchestrator.HydraFlowOrchestrator`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by HydraFlowOrchestrator or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _active_issues_lock: asyncio.Lock
    _config: HydraFlowConfig
    _recovered_issues: set[int]
    _session_issue_results: dict[int, bool]
    _state: StateTracker
    _stop_event: asyncio.Event
    _svc: ServiceRegistry

    if TYPE_CHECKING:

        async def _sleep_or_stop(
            self, seconds: int | float
        ) -> None: ...  # provided by OrchestratorLoopsMixin

        def _sync_active_issue_numbers(
            self,
        ) -> None: ...  # provided by OrchestratorHITLMixin

    async def _do_implement_work(self) -> bool:
        """Work function for the implement loop."""
        did_work = False
        # After one poll cycle, release crash-recovered issues
        if self._recovered_issues:
            async with self._active_issues_lock:
                self._svc.implementer.active_issues.difference_update(
                    self._recovered_issues
                )
                self._recovered_issues.clear()
                self._sync_active_issue_numbers()
        while not self._stop_event.is_set():
            results, issues = await self._svc.implementer.run_batch()
            if not issues:
                break
            did_work = True
            await self._svc.implementer.post_impl_transcript_hooks(results)
            for result in results:
                self._session_issue_results[result.issue_number] = result.success
        return did_work

    async def _do_review_work(self) -> bool:
        """Work function for the review loop — continuous slot-filling pool.

        Instead of fetching a batch and waiting for all reviews to finish,
        this maintains a pool of up to ``max_reviewers`` concurrent tasks.
        As each review completes, the freed slot is immediately refilled
        from the queue so no capacity sits idle.
        """
        did_work = False
        pending: set[asyncio.Task[bool]] = set()
        max_slots = self._config.max_reviewers

        while not self._stop_event.is_set():
            # Fill empty slots from the queue
            free_slots = max_slots - len(pending)
            if free_slots > 0:
                new_issues = self._svc.store.get_reviewable(free_slots)
                for issue in new_issues:
                    task = asyncio.create_task(
                        self._review_single_issue(issue),
                        name=f"review-issue-{issue.id}",
                    )
                    pending.add(task)

            if not pending:
                break

            # Wait for at least one review to complete, then refill
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            batch_did_work = False
            for task in done:
                exc = task.exception()
                if exc is not None:
                    await handle_pool_worker_exception(
                        exc,
                        pending,
                        log=logger,
                        context="Review worker failed unexpectedly",
                    )
                elif task.result():
                    did_work = True
                    batch_did_work = True

            # When all completed tasks did no real work (e.g. PR not visible,
            # re-queued), pause briefly to avoid a hot spin loop.
            if not batch_did_work and not pending:
                break

        # Cancel stragglers on stop
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        return did_work

    async def _review_single_issue(self, issue: Task) -> bool:
        """Fetch PR and run review for a single issue, handling results inline.

        Returns ``True`` when a review actually ran, ``False`` when the
        issue was only re-queued (e.g. PR not visible yet).
        """
        try:
            if is_adr_issue_title(issue.title):
                await self._svc.reviewer.review_adrs([issue])
                return True

            # ``get_active_issues`` is orchestrator-only — not on IssueStorePort.
            active_in_store = set(
                cast("IssueStore", self._svc.store).get_active_issues().keys()
            )
            gh_issue = GitHubIssue.from_task(issue)
            prs, gh_issues = await self._svc.fetcher.fetch_reviewable_prs(
                active_in_store, prefetched_issues=[gh_issue]
            )
            if not prs:
                # PR not visible yet — usually propagation delay, but after a
                # restart mid-implement the PR may NOT EXIST and the issue
                # would otherwise sit review-labeled forever (#9815). Count
                # strikes; at the threshold, requeue with fresh budget
                # (bounded, then HITL) instead of waiting eternally.
                if await self._handle_review_orphan(issue):
                    return False
                await self._sleep_or_stop(min(self._config.poll_interval, 30))
                self._svc.store.enqueue_transition(issue, "review")
                return False
            self._state.clear_review_orphan_strikes(issue.id)

            review_results = await self._svc.reviewer.review_prs(
                prs, [i.to_task() for i in gh_issues]
            )
            await self._svc.reviewer.post_review_transcript_hooks(review_results)
            if any(r.merged for r in review_results):
                await asyncio.sleep(_POST_MERGE_DELAY)
                await self._svc.prs.pull_main()
            return True
        finally:
            release_batch_in_flight(self._svc.store, {issue.id})

    async def _handle_review_orphan(self, issue: Task) -> bool:
        """Requeue a review-labeled issue whose agent PR does not exist (#9815).

        Returns True when the issue was requeued (to ready) or escalated (to
        HITL) — the caller must NOT re-enqueue it to review. Returns False
        while strikes are below the threshold (normal PR-propagation wait) or
        when the feature is disabled (``review_orphan_max_requeues=0``).
        Every gh failure is fail-soft back to the legacy wait path.
        """
        if self._config.review_orphan_max_requeues <= 0:
            return False
        strikes = self._state.increment_review_orphan_strike(issue.id)
        if strikes < self._config.review_orphan_strike_threshold:
            return False

        self._state.clear_review_orphan_strikes(issue.id)
        requeues = self._state.increment_review_orphan_requeue(issue.id)
        try:
            if requeues > self._config.review_orphan_max_requeues:
                cause = (
                    f"review-labeled with no agent PR after "
                    f"{requeues - 1} orphan requeue(s) — needs a human"
                )
                self._state.set_hitl_cause(issue.id, cause)
                await self._svc.prs.swap_pipeline_labels(
                    issue.id, self._config.hitl_label[0]
                )
                await self._svc.prs.post_comment(
                    issue.id,
                    "## Review Orphan Escalation\n\n"
                    f"{cause}. Escalating to HITL (#9815).",
                )
                logger.warning(
                    "Issue #%d: review orphan exhausted %d requeues — HITL",
                    issue.id,
                    self._config.review_orphan_max_requeues,
                )
                return True

            self._state.reset_issue_attempts(issue.id)
            self._state.clear_diagnostic_state(issue.id)
            await self._svc.prs.swap_pipeline_labels(
                issue.id, self._config.ready_label[0]
            )
            await self._svc.prs.post_comment(
                issue.id,
                "## Review Orphan Requeue\n\n"
                "This issue was review-labeled with no open agent PR "
                "(interrupted implement, e.g. a factory restart). Attempt "
                f"counters reset; requeued to ready for a fresh build "
                f"(requeue {requeues}/"
                f"{self._config.review_orphan_max_requeues}, #9815).",
            )
            logger.info(
                "Issue #%d: review orphan requeued to ready (%d/%d)",
                issue.id,
                requeues,
                self._config.review_orphan_max_requeues,
            )
            return True
        except RuntimeError as exc:
            logger.warning(
                "Issue #%d: review orphan handling failed (%s) — keeping "
                "legacy review wait",
                issue.id,
                exc,
            )
            return False
