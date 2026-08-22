"""Epic-group planning of :class:`plan_phase.PlanPhase`.

Extracted VERBATIM from ``plan_phase.py`` (god-class decomposition, Refs
#11547) as a mixin; ``PlanPhase`` inherits :class:`PlanEpicMixin`.

One cohesive concern: planning an epic's children together — partitioning the
queue into epic groups, the gap-review parse and comment, the ownership claim
that re-plans a child only while GitHub and the store both still hold PLAN,
and the iterate-until-converged group driver.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from models import EpicGapReview, PlanResult, Task
from phase_utils import release_batch_in_flight, run_concurrent_batch

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from planner import PlannerRunner
    from ports import IssueStorePort, PRPort
    from task_source import TaskTransitioner

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.plan_phase`` origin.
logger = logging.getLogger("hydraflow.plan_phase")


class PlanEpicMixin:
    """Epic-group planning of :class:`plan_phase.PlanPhase`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PlanPhase or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _planners: PlannerRunner
    _prs: PRPort
    _stop_event: asyncio.Event
    _store: IssueStorePort
    _transitioner: TaskTransitioner

    if TYPE_CHECKING:

        async def _plan_one(
            self, idx: int, issue: Task, semaphore: asyncio.Semaphore
        ) -> PlanResult: ...  # provided by PlanFlowMixin

    # ------------------------------------------------------------------
    # Epic group planning helpers
    # ------------------------------------------------------------------

    def _is_epic_child(self, issue: Task) -> bool:
        """Return True if *issue* has an epic-child label."""
        epic_child_labels = {lbl.lower() for lbl in self._config.epic_child_label}
        return bool(epic_child_labels & {t.lower() for t in issue.tags})

    def _resolve_epic_number(self, issue: Task) -> int | None:
        """Extract the parent epic number from metadata or body text."""
        epic_num = issue.metadata.get("epic_number")
        if epic_num:
            return int(epic_num)
        match = re.search(r"[Pp]arent\s+[Ee]pic[:\s#]*(\d+)", issue.body)
        if match:
            return int(match.group(1))
        return None

    def _group_by_epic(
        self, issues: list[Task]
    ) -> tuple[dict[int, list[Task]], list[Task]]:
        """Partition issues into ``{epic_number: [children]}`` and standalone.

        Issues with an epic-child label whose parent cannot be resolved
        are placed in the standalone list.
        """
        epic_groups: dict[int, list[Task]] = {}
        standalone: list[Task] = []
        for issue in issues:
            if not self._is_epic_child(issue):
                standalone.append(issue)
                continue
            epic_num = self._resolve_epic_number(issue)
            if epic_num is None:
                standalone.append(issue)
                continue
            epic_groups.setdefault(epic_num, []).append(issue)
        return epic_groups, standalone

    @staticmethod
    def _parse_gap_review(transcript: str, epic_number: int) -> EpicGapReview:
        """Parse an ``EpicGapReview`` from a gap-review transcript."""
        review = EpicGapReview(epic_number=epic_number)

        start_marker = "GAP_REVIEW_START"
        end_marker = "GAP_REVIEW_END"
        start_idx = transcript.find(start_marker)
        end_idx = transcript.find(end_marker)
        if start_idx == -1:
            return review
        body = transcript[
            start_idx + len(start_marker) : end_idx if end_idx != -1 else None
        ]

        # Extract findings
        findings_match = re.search(
            r"##\s*Findings\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL
        )
        if findings_match:
            review.findings = findings_match.group(1).strip()

        # Extract re-plan issues
        replan_match = re.search(
            r"##\s*Re-plan Required\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL
        )
        if replan_match:
            replan_text = replan_match.group(1).strip()
            if replan_text.lower() != "none":
                review.replan_issues = list(
                    dict.fromkeys(
                        int(m.group(1)) for m in re.finditer(r"#(\d+)", replan_text)
                    )
                )

        # Extract guidance
        guidance_match = re.search(
            r"##\s*Guidance\s*\n(.*?)(?=\n##|\Z)", body, re.DOTALL
        )
        if guidance_match:
            review.guidance = guidance_match.group(1).strip()

        return review

    def _plan_one_with_context(
        self,
        issue: Task,
        gap_guidance: str,
        sibling_plans: dict[int, str],
    ) -> Task:
        """Return a copy of *issue* with gap feedback appended to comments."""
        sibling_summary = "\n\n".join(
            f"### Sibling Issue #{num}\n{plan[:500]}"
            for num, plan in sibling_plans.items()
            if num != issue.id
        )
        extra_comment = (
            f"## Epic Gap Review Feedback\n\n"
            f"{gap_guidance}\n\n"
            f"## Sibling Plan Summaries\n\n"
            f"{sibling_summary}"
        )
        return issue.model_copy(update={"comments": [*issue.comments, extra_comment]})

    async def _post_gap_review_comment(
        self, epic_number: int, review: EpicGapReview, iteration: int
    ) -> None:
        """Post gap review findings as a comment on the epic issue."""
        replan_list = (
            ", ".join(f"#{n}" for n in review.replan_issues)
            if review.replan_issues
            else "None"
        )
        comment = (
            f"## Epic Gap Review (Iteration {iteration})\n\n"
            f"**Findings:**\n{review.findings}\n\n"
            f"**Re-plan required:** {replan_list}\n\n"
            f"**Guidance:**\n{review.guidance}\n\n"
            f"---\n"
            f"*Generated by HydraFlow Planner*"
        )
        await self._transitioner.post_comment(epic_number, comment)

    async def _claim_live_epic_replan(
        self,
        epic_number: int,
        issue: Task,
    ) -> Task | None:
        """Reserve *issue* only while both GitHub and the store still own PLAN.

        Gap review retains the cohort's original ``Task`` objects. A child may
        advance to READY or be claimed by implement while the review provider
        is running, so that snapshot cannot authorize another planner. The
        awaited reads establish durable GitHub state; ``try_claim_stage`` is
        the synchronous post-read compare-and-set that closes the local race.
        """
        try:
            live_state, live_labels = await asyncio.gather(
                self._prs.get_issue_state(issue.id),
                self._prs.get_issue_labels(issue.id),
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Epic #%d: could not revalidate #%d before re-plan — skipping",
                epic_number,
                issue.id,
                exc_info=True,
            )
            return None

        if str(live_state).upper() != "OPEN":
            logger.info(
                "Epic #%d: skipping re-plan of #%d — live state is %s",
                epic_number,
                issue.id,
                live_state,
            )
            return None

        labels = {str(label).lower() for label in live_labels}
        plan_labels = {label.lower() for label in self._config.planner_label}
        allowed_labels = plan_labels | {
            label.lower() for label in self._config.find_label
        }
        blocking_labels = {
            label.lower() for label in self._config.all_pipeline_labels
        } - allowed_labels
        conflicts = sorted(labels & blocking_labels)
        if not labels.intersection(plan_labels) or conflicts:
            reason = (
                f"conflicting live labels {conflicts}"
                if conflicts
                else "PLAN label is absent"
            )
            logger.info(
                "Epic #%d: skipping re-plan of #%d — %s",
                epic_number,
                issue.id,
                reason,
            )
            return None

        live_issue = issue.model_copy(update={"tags": list(live_labels)})
        if not self._store.try_claim_stage(live_issue, "plan"):
            logger.info(
                "Epic #%d: skipping re-plan of #%d — "
                "local stage or worker ownership changed",
                epic_number,
                issue.id,
            )
            return None
        return live_issue

    async def _plan_epic_group(
        self,
        epic_number: int,
        children: list[Task],
        semaphore: asyncio.Semaphore,
    ) -> list[PlanResult]:
        """Plan all children of an epic with gap review and re-planning."""
        logger.info(
            "Planning epic #%d group (%d children)",
            epic_number,
            len(children),
        )

        # Phase 1: plan all children concurrently
        results = await run_concurrent_batch(
            children,
            lambda idx, issue: self._plan_one(idx, issue, semaphore),
            self._stop_event,
        )

        # Collect successful plans
        plan_map: dict[int, str] = {}
        title_map: dict[int, str] = {}
        issue_map: dict[int, Task] = {c.id: c for c in children}
        for r in results:
            if r.success and r.plan:
                plan_map[r.issue_number] = r.plan
                issue = issue_map.get(r.issue_number)
                title_map[r.issue_number] = issue.title if issue else ""
                r.epic_number = epic_number

        # Skip gap review if fewer than 2 successful plans
        max_iterations = self._config.epic_gap_review_max_iterations
        if len(plan_map) < 2 or max_iterations == 0:
            logger.info(
                "Epic #%d: skipping gap review (%d plans, max_iter=%d)",
                epic_number,
                len(plan_map),
                max_iterations,
            )
            return results

        # Phase 2: gap review loop
        # The gap-review prompt embeds every reviewed child's plan, so the
        # CH-6 prompt gate must see the union of those children's labels
        # (any data-class:<class> elevation on ANY child applies).
        gap_review_labels = sorted(
            {tag for c in children if c.id in plan_map for tag in c.tags}
        )
        for iteration in range(1, max_iterations + 1):
            if self._stop_event.is_set():
                break

            logger.info(
                "Epic #%d: gap review iteration %d/%d",
                epic_number,
                iteration,
                max_iterations,
            )
            transcript = await self._planners.run_gap_review(
                epic_number, plan_map, title_map, issue_labels=gap_review_labels
            )
            review = self._parse_gap_review(transcript, epic_number)

            if not review.replan_issues:
                logger.info(
                    "Epic #%d: plans are coherent after iteration %d",
                    epic_number,
                    iteration,
                )
                break

            await self._post_gap_review_comment(epic_number, review, iteration)

            # Re-plan flagged children with gap context
            eligible_replans = 0
            for issue_number in review.replan_issues:
                if self._stop_event.is_set():
                    break
                issue = issue_map.get(issue_number)
                if issue is None:
                    logger.warning(
                        "Epic #%d: gap review flagged #%d but not in group",
                        epic_number,
                        issue_number,
                    )
                    continue

                live_issue = await self._claim_live_epic_replan(epic_number, issue)
                if live_issue is None:
                    continue

                eligible_replans += 1
                enriched = self._plan_one_with_context(
                    live_issue,
                    review.guidance,
                    plan_map,
                )
                try:
                    replan_result = await self._plan_one(0, enriched, semaphore)
                finally:
                    # _plan_one normally consumes the PLAN reservation through
                    # store_lifecycle. Its early-stop/exception paths may not.
                    # Never release a later READY worker's claim.
                    release_batch_in_flight(
                        self._store,
                        {issue_number},
                        expected_stage="plan",
                    )
                if replan_result.success and replan_result.plan:
                    plan_map[issue_number] = replan_result.plan
                    replan_result.epic_number = epic_number
                # Update the results list
                results = [
                    replan_result if r.issue_number == issue_number else r
                    for r in results
                ]

            if eligible_replans == 0:
                logger.info(
                    "Epic #%d: no requested re-plans remain eligible — "
                    "ending gap review",
                    epic_number,
                )
                break

        return results
