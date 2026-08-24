"""Per-child enrichment: what one sub-issue looks like inside an epic.

Split from ``_detail`` because it fails for different reasons. A detail
breaks when the epic's own shape changes; this breaks when GitHub or the
worker fleet reports a child differently — a stage label renamed, a PR
status field moved, a queue accessor gone. It is also the only consumer
of ``_stage_from_labels``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from issue_fetcher import IssueFetcher
from models import (
    CIStatus,
    EpicChildInfo,
    EpicChildPRState,
    EpicChildState,
    EpicChildStatus,
    EpicState,
    ReviewStatus,
)
from pr_manager import PRManager
from state import StateTracker

from ._parse import _stage_from_labels

if TYPE_CHECKING:
    from ._manager import WorkerTruthStore

logger = logging.getLogger("hydraflow.epic")


class EpicChildInfoMixin:
    """Per-child enrichment: what one sub-issue looks like inside an epic."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``EpicManager.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _fetcher: IssueFetcher
    _issue_store: WorkerTruthStore | None
    _prs: PRManager
    _state: StateTracker

    async def _build_child_info(
        self,
        child_num: int,
        epic: EpicState,
        repo: str,
        fixed_label: str,
        worker_held: dict[int, str] | None = None,
        queued: dict[int, str] | None = None,
    ) -> EpicChildInfo:
        """Build enriched child info for a single sub-issue.

        ``worker_held``/``queued`` are the worker-truth snapshots (issue
        #10299). When omitted, they default to empty and — combined with no
        wired store — the child's running/queued state falls back to labels.
        """
        worker_held = worker_held or {}
        queued = queued or {}
        is_completed = child_num in epic.completed_children
        is_failed = child_num in epic.failed_children
        is_approved = child_num in epic.approved_children
        child_info = EpicChildInfo(
            issue_number=child_num,
            url=f"https://github.com/{repo}/issues/{child_num}",
            is_completed=is_completed,
            is_failed=is_failed,
            is_approved=is_approved,
        )

        # Determine stage/status from completion state
        if is_completed:
            child_info.current_stage = "merged"
            child_info.stage = "merged"
            child_info.status = EpicChildStatus.DONE
            child_info.state = EpicChildState.CLOSED
        elif is_failed:
            child_info.status = EpicChildStatus.FAILED

        # Fetch live data from GitHub
        try:
            gh_issue = await self._fetcher.fetch_issue_by_number(child_num)
            if gh_issue is not None:
                child_info.title = gh_issue.title
                if fixed_label and fixed_label in gh_issue.labels:
                    child_info.state = EpicChildState.CLOSED
                # Derive stage from labels for display. A ``merged`` label is
                # terminal (DONE); running-vs-queued is decided by worker truth
                # below, NOT by the implement/review label alone (#10299).
                if not child_info.current_stage:
                    stage = _stage_from_labels(gh_issue.labels, self._config)
                    child_info.stage = stage
                    child_info.current_stage = stage
                    if stage == "merged":
                        child_info.status = EpicChildStatus.DONE
        except RuntimeError:
            logger.debug(
                "Could not fetch child #%d for epic detail", child_num, exc_info=True
            )

        # Worker-derived execution state (#10299): only a worker actually
        # holding the child makes it RUNNING; a store-wired-but-unheld child is
        # QUEUED regardless of an implement/review label. Skip terminal states.
        if child_info.status not in (EpicChildStatus.DONE, EpicChildStatus.FAILED):
            self._apply_execution_state(child_info, worker_held, queued)

        # Enrich with branch/PR data from state
        branch = self._state.get_branch(child_num)
        if branch:
            child_info.branch = branch
            try:
                pr_info = await self._prs.find_open_pr_for_branch(
                    branch, issue_number=child_num
                )
                if pr_info is not None:
                    child_info.pr_number = pr_info.number
                    child_info.pr_url = pr_info.url
                    child_info.pr_state = (
                        EpicChildPRState.DRAFT
                        if pr_info.draft
                        else EpicChildPRState.OPEN
                    )
                    # Fetch CI and review status
                    await self._enrich_pr_status(child_info, pr_info.number)
            except RuntimeError:
                logger.debug(
                    "Could not fetch PR info for child #%d branch %s",
                    child_num,
                    branch,
                    exc_info=True,
                )

        return child_info

    def _apply_execution_state(
        self,
        child_info: EpicChildInfo,
        worker_held: dict[int, str],
        queued: dict[int, str],
    ) -> None:
        """Set a non-terminal child's running/queued status + worker.

        Worker-truth path (a store is wired): a child is RUNNING only when it
        appears in ``worker_held`` (``IssueStore._active`` ∪ ``_in_flight``),
        and it carries the holding stage in ``worker``. Otherwise it is QUEUED,
        even if it carries an implement/review label — a label no longer
        implies a worker is on it. Parked/idle children land here as QUEUED but
        are excluded from the epic's ``queued_children`` count (they are in
        neither the worker nor queue set), so the epic reads paused.

        Legacy path (no store wired): fall back to the child's stage label so
        prior behaviour is preserved (implement/review -> RUNNING).
        """
        if self._issue_store is None:
            if child_info.current_stage in ("implement", "review"):
                child_info.status = EpicChildStatus.RUNNING
            elif child_info.current_stage:
                child_info.status = EpicChildStatus.QUEUED
            return

        issue_number = child_info.issue_number
        if issue_number in worker_held:
            child_info.status = EpicChildStatus.RUNNING
            child_info.worker = worker_held[issue_number]
        else:
            child_info.status = EpicChildStatus.QUEUED

    async def _enrich_pr_status(
        self, child_info: EpicChildInfo, pr_number: int
    ) -> None:
        """Fetch CI checks and review status for a PR."""
        try:
            checks = await self._prs.get_pr_checks(pr_number)
            if checks:
                states = {c.get("state", "") for c in checks}
                if all(s == "success" for s in states):
                    child_info.ci_status = CIStatus.PASSING
                elif "failure" in states or "error" in states:
                    child_info.ci_status = CIStatus.FAILING
                else:
                    child_info.ci_status = CIStatus.PENDING
        except RuntimeError:
            logger.debug(
                "Could not fetch CI checks for PR #%d", pr_number, exc_info=True
            )

        try:
            reviews = await self._prs.get_pr_reviews(pr_number)
            if reviews:
                review_states = [r.get("state", "") for r in reviews]
                if "APPROVED" in review_states:
                    child_info.review_status = ReviewStatus.APPROVED
                elif "CHANGES_REQUESTED" in review_states:
                    child_info.review_status = ReviewStatus.CHANGES_REQUESTED
                else:
                    child_info.review_status = ReviewStatus.PENDING
        except RuntimeError:
            logger.debug("Could not fetch reviews for PR #%d", pr_number, exc_info=True)

        try:
            child_info.mergeable = await self._prs.get_pr_mergeable(pr_number)
        except RuntimeError:
            logger.debug(
                "Could not fetch mergeable status for PR #%d", pr_number, exc_info=True
            )
