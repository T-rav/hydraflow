"""Plan finalization and cache records of :class:`plan_phase.PlanPhase`.

Extracted VERBATIM from ``plan_phase.py`` (god-class decomposition, Refs
#11547) as a mixin; ``PlanPhase`` inherits :class:`PlanRecordsMixin`.

One cohesive concern: turning a drafted plan into durable artifacts — posting
it, running ``PlanReviewer`` and writing the ``plan_stored`` /
``review_stored`` cache records, reading back the prior round's review for the
next one, and the ADR-0063 W3b touchpoint-expander re-review that fires on the
first blocking failure.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from analysis import PlanAnalyzer
from exception_classify import reraise_on_credit_or_bug
from models import PlanFinding, PlanResult, PlanReview, Task
from pending_concerns import AdversarialState
from planner import PlannerRunner
from traceability import extract_req_id, missing_required_req_id

if TYPE_CHECKING:
    from adversarial_agents import AgentLike
    from config import HydraFlowConfig
    from issue_cache import IssueCache
    from plan_reviewer import PlanReviewer
    from plan_touchpoint_expander import PlanTouchpointExpander
    from state import StateTracker
    from task_source import TaskTransitioner

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.plan_phase`` origin.
logger = logging.getLogger("hydraflow.plan_phase")


class PlanRecordsMixin:
    """Plan finalization and cache records of :class:`plan_phase.PlanPhase`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PlanPhase or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _issue_cache: IssueCache | None
    _plan_reviewer: PlanReviewer | None
    _planners: PlannerRunner
    _spec_ac_agent: AgentLike | None
    _spec_judge_agent: AgentLike | None
    _state: StateTracker
    _touchpoint_expander: PlanTouchpointExpander | None
    _transitioner: TaskTransitioner

    if TYPE_CHECKING:

        async def _is_product_track_issue(
            self, issue: Task
        ) -> bool: ...  # provided by PlanPrepassMixin

        async def _run_spec_ac_and_judge(
            self, issue: Task, adv: AdversarialState, plan_text: str
        ) -> None: ...  # provided by PlanAdversarialMixin

        def _skip_plan_review(
            self, issue: Task
        ) -> tuple[bool, int]: ...  # provided by PlanTieringMixin

        async def _wiki_ingest_plan(
            self, issue_number: int, plan_text: str
        ) -> None: ...  # provided by PlanWikiIngestMixin

    async def _run_plan_finalization(
        self, issue: Task, result: PlanResult
    ) -> PlanResult:
        """Post the plan, write records (+ touchpoint re-review), run SpecAC/Judge.

        The pre-gate half of the former ``_handle_plan_success`` (P3a of #10682):
        everything up to — but not including — the #10659 design-decision gate,
        which is now the explicit ``gate`` flow node. Returns the (possibly
        product-track decompose-retried) ``PlanResult`` the ready swap files
        sub-issues from; the caller threads it to :meth:`_swap_plan_to_ready`.
        The original ``PlanResult`` the plan flow transcribes/returns is
        unaffected — the retry rebind was, and stays, local here.
        """
        # Product-track decomposition check: if issue came from Shape and
        # the planner didn't produce enough sub-issues, retry with feedback
        if (
            await self._is_product_track_issue(issue)
            and len(result.new_issues) < 3
            and not getattr(result, "_decompose_retried", False)
        ):
            logger.info(
                "Issue #%d is product-track but planner only produced %d sub-issues "
                "(need ≥3) — retrying with decomposition feedback",
                issue.id,
                len(result.new_issues),
            )
            retry_result = await self._planners.plan(
                issue,
                research_context=(
                    f"IMPORTANT: This issue came through the product track and "
                    f"MUST be decomposed into 3-8 concrete sub-issues using "
                    f"NEW_ISSUES_START/NEW_ISSUES_END markers. Your previous "
                    f"plan only produced {len(result.new_issues)} sub-issues. "
                    f"Break the work into independently implementable pieces."
                ),
            )
            if retry_result.success and len(retry_result.new_issues) >= 3:
                result = retry_result
            else:
                logger.warning(
                    "Decomposition retry for #%d still insufficient (%d issues)",
                    issue.id,
                    len(retry_result.new_issues) if retry_result.success else 0,
                )
                # Proceed with whatever we have

        branch = self._config.branch_for_issue(issue.id)
        score_line = ""
        if result.actionability_rank != "unknown":
            score_line = (
                f"**Actionability score:** {result.actionability_score}/100 "
                f"({result.actionability_rank})\n"
            )
        # Collect any architecture diagrams the planner wrote to /tmp
        diagram_attachments = PlannerRunner.collect_diagram_attachments(issue.id)
        diagram_section = ""
        if diagram_attachments:
            diagram_section = f"\n\n## Architecture Diagrams\n\n{diagram_attachments}\n"

        # CH-5 traceability: carry the requirement ID (req:<id> label or
        # Req-ID: body line) into the plan comment immediately AFTER the
        # "## Implementation Plan" heading, ABOVE the plan body. The
        # implementer prompt extracts the plan from the heading up to the
        # FIRST ^---$ line (AgentRunner._strip_plan_noise, agent.py) — a
        # bare horizontal rule inside the plan body would sever anything
        # placed below it, so the Req-ID must lead.
        req_id = extract_req_id(labels=issue.tags, body=issue.body)
        req_line = f"**Req-ID:** `{req_id}`\n\n" if req_id else ""
        req_warning = ""
        if missing_required_req_id(
            labels=issue.tags,
            body=issue.body,
            regulated_labels=self._config.regulated_label_set(),
        ):
            req_warning = (
                "> ⚠️ **Req-ID required:** this issue is in the regulated "
                "change class but declares no requirement ID. Add a "
                "`req:<id>` label or a `Req-ID:` line to the issue body so "
                "the change is traceable in the requirements matrix.\n\n"
            )

        comment_body = (
            f"## Implementation Plan\n\n"
            f"{req_line}"
            f"{req_warning}"
            f"{result.plan}\n\n"
            f"{diagram_section}"
            f"**Branch:** `{branch}`\n\n"
            f"---\n"
            f"{score_line}"
            f"*Generated by HydraFlow Planner*"
        )
        await self._transitioner.post_comment(issue.id, comment_body)

        analyzer = PlanAnalyzer(repo_root=self._config.repo_root)
        analysis = analyzer.analyze(result.plan, issue.id)
        await self._transitioner.post_comment(issue.id, analysis.format_comment())

        # Ingest plan knowledge into the per-repo wiki
        await self._wiki_ingest_plan(issue.id, result.plan)

        # IMPORTANT: cache writes (plan_stored + review_stored) and the
        # adversarial reviewer MUST run BEFORE the label swap to ready.
        # If the swap happened first, the implement loop could pick up
        # the issue and the READY-stage precondition gate would find
        # no records and route the issue back to plan — causing an
        # infinite ping-pong loop. The eager-transition guard at
        # `enqueue_transition` is in-memory only and does not protect
        # against the GitHub label being visible to other pollers.
        await self._write_plan_records(issue, result)

        # Earlier-adversarial pipeline stages 5+6: SpecACGenerator + SpecJudge.
        # Run AFTER PlanReviewer (which is invoked from inside
        # ``_write_plan_records``). No-op when SpecAC/Judge agents are
        # not configured.
        if (
            self._spec_ac_agent is not None
            and self._spec_judge_agent is not None
            and result.plan
        ):
            adv = self._state.get_adversarial_state(issue.id) or AdversarialState(
                phase="plan"
            )
            try:
                await self._run_spec_ac_and_judge(issue, adv, result.plan)
            except Exception as exc:  # noqa: BLE001
                # Dark-factory contract: credit-exhaustion / auth / likely-bug
                # exceptions MUST propagate so the outer loop pauses on the
                # billing signal instead of swallowing it and marching the
                # issue toward 'ready'. Everything else soft-fails (concerns
                # forward unchanged).
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "SpecAC/Judge stage failed for issue #%d — forwarding "
                    "concerns unchanged",
                    issue.id,
                    exc_info=True,
                )
        return result

    async def _write_plan_records(self, issue: Task, result: PlanResult) -> int:
        """Write plan_stored + review_stored cache records.

        Called BEFORE the label swap to ready so the records exist
        before the implement loop can observe the new label and run
        the READY-stage precondition gate. Returns the plan version
        assigned by the cache (1 if no cache configured).

        Best-effort across both writes — failures log at warning and
        do not raise into the caller, so the plan still proceeds and
        the gate handles the missing-record case via route-back with
        the cause "no review_stored record" (effectively the same as
        a blocking review, with a clearer human-readable cause).

        Adversarial findings live in the review_stored record, not in
        plan_stored — conflating validation_errors with PlanFinding-
        shaped findings would poison the cache for review-stage
        consumers.
        """
        plan_version = 1
        if self._issue_cache is None:
            return plan_version

        plan_version = self._issue_cache.record_plan_stored(
            issue.id,
            plan_text=result.plan,
            actionability_score=result.actionability_score,
        )

        if self._plan_reviewer is None:
            return plan_version

        # #11298 size tiering: low-complexity, never-cycled, unescalated
        # issues skip the agentic review spawn. A review_stored record is
        # still written (has_blocking=False) so the READY-stage gate's
        # "no review_stored record" route-back never fires for the light
        # tier — the skip is an explicit, audited verdict, not a gap.
        skip, complexity = self._skip_plan_review(issue)
        if skip:
            threshold = self._config.plan_review_min_complexity
            summary = (
                f"light-tier: adversarial plan review skipped "
                f"(complexity {complexity} <= {threshold}; #11298)"
            )
            logger.info("Plan review skipped for issue #%d — %s", issue.id, summary)
            self._issue_cache.record_review_stored(
                issue.id,
                review_text=summary,
                has_blocking=False,
                findings=[],
            )
            return plan_version

        try:
            # #11298 delta re-review: after a route-back this is round >= 2 —
            # feed the prior round's cached findings so the reviewer verifies
            # fixes instead of re-exploring the repo (plan_reviewer measured
            # at 42% of all factory tokens, dominated by re-exploration).
            prior_summary, prior_findings = self._prior_review_context(issue.id)
            review = await self._plan_reviewer.review(
                issue,
                result,
                plan_version=plan_version,
                prior_summary=prior_summary,
                prior_findings=prior_findings,
            )
            # ADR-0063 W3b: on the FIRST blocking review, dispatch the
            # touchpoint-expander (if wired) and re-run the reviewer
            # against an enriched plan. Bounded to one expansion attempt
            # — if the second pass still flags blocking findings, the
            # existing READY-stage gate routes the issue back to plan
            # (or escalates after the per-issue route-back cap).
            review = await self._maybe_expand_touchpoints(
                issue, result, review, plan_version
            )
            if review.success:
                self._issue_cache.record_review_stored(
                    issue.id,
                    review_text=review.summary,
                    has_blocking=review.has_blocking_findings,
                    findings=[f.model_dump() for f in review.findings],
                )
                if review.has_blocking_findings:
                    logger.warning(
                        "Plan review for issue #%d found blocking "
                        "findings — READY-stage gate will route back "
                        "to PLAN: %s",
                        issue.id,
                        review.summary,
                    )
            else:
                logger.warning(
                    "Plan review skipped for issue #%d: %s",
                    issue.id,
                    review.error or "reviewer returned no result",
                )
        except Exception:
            logger.warning(
                "Plan reviewer raised for issue #%d — leaving plan "
                "without a review record",
                issue.id,
                exc_info=True,
            )

        return plan_version

    def _prior_review_context(
        self, issue_id: int
    ) -> tuple[str | None, list[PlanFinding] | None]:
        """Prior round's cached review (summary, findings) for issue_id.

        (None, None) on round 1 (no cached review) or when the cache is
        unavailable/malformed — the reviewer then runs a normal full
        first-round review (#11298 delta re-review is fail-open).
        """
        if self._issue_cache is None:
            return None, None
        try:
            record = self._issue_cache.latest_review(issue_id)
            payload = getattr(record, "payload", None)
            if not isinstance(payload, dict):
                return None, None
            summary = payload.get("review_text") or None
            findings: list[PlanFinding] = []
            for raw in payload.get("findings") or []:
                try:
                    findings.append(PlanFinding.model_validate(raw))
                except (ValueError, TypeError):
                    continue  # one bad row never blocks review
            if not isinstance(summary, str):
                summary = None
            return summary, (findings or None)
        except (AttributeError, TypeError, ValueError):
            # Malformed cache (or a test double with a different shape) —
            # degrade to a normal full first-round review.
            return None, None

    async def _maybe_expand_touchpoints(
        self,
        issue: Task,
        result: PlanResult,
        first_review: PlanReview,
        plan_version: int,
    ) -> PlanReview:
        """Run the touchpoint-expander + re-review on FIRST blocking failure.

        Returns the review that should be cached. When no expander is
        wired, the first review has no blocking findings, the expander
        surfaces no touchpoints, or the reviewer is missing, returns
        ``first_review`` unchanged so the existing route-back path runs.

        Bounded to one expansion attempt per ADR-0063 W3b — the second
        review's verdict (clean or still-blocking) is what the cache
        records. A still-blocking second review routes back via the
        existing READY-stage gate.
        """
        if (
            self._touchpoint_expander is None
            or self._plan_reviewer is None
            or not first_review.success
            or not first_review.has_blocking_findings
        ):
            return first_review

        try:
            expansion = await self._touchpoint_expander.expand_touchpoints(
                original_plan=result.plan,
                reviewer_failure=first_review,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Touchpoint expander raised for issue #%d — falling back "
                "to existing route-back path",
                issue.id,
                exc_info=True,
            )
            return first_review

        context_block = expansion.render_context_block()
        if not context_block:
            logger.info(
                "Touchpoint expander surfaced no touchpoints for issue #%d "
                "— skipping re-review",
                issue.id,
            )
            return first_review

        # Build an enriched plan_result for the second review pass. We
        # do NOT mutate the original result — the cached plan_stored
        # record (already written above) reflects the planner's output,
        # not the enrichment. The expansion is a reviewer-side aid.
        enriched_plan = f"{result.plan}\n\n{context_block}"
        enriched_result = result.model_copy(update={"plan": enriched_plan})

        try:
            second_review = await self._plan_reviewer.review(
                issue,
                enriched_result,
                plan_version=plan_version,
                prior_summary=first_review.summary,
                prior_findings=list(first_review.findings),
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Re-review with expanded touchpoints raised for issue #%d "
                "— falling back to original review",
                issue.id,
                exc_info=True,
            )
            return first_review

        logger.info(
            "Touchpoint-expander re-review for issue #%d: %d touchpoints "
            "surfaced, blocking=%s → %s",
            issue.id,
            len(expansion.touchpoints),
            first_review.has_blocking_findings,
            second_review.has_blocking_findings,
        )
        return second_review
