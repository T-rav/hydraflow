"""ADR-review surface of ``ReviewPhase`` (#10371).

Extracted VERBATIM from ``_phase.py`` (god-class decomposition, Refs #11547)
as a mixin — the same shape ``_visual_gate.py`` took in the #10840 pass.
``ReviewPhase`` inherits it, so every method here still resolves as an
attribute of ``ReviewPhase`` and instance/class-level patching in tests still
lands.

One concern: reviewing an ADR *draft issue* rather than a PR. The ADR surface
has no unified diff — the draft lives in the issue body — so it needs its own
validation, duplicate check, and its own pre-flight / post-verify advisor
calls that declare ``docs/adr/`` explicitly for blast-radius classification.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from adr_utils import (
    adr_validation_reasons,
    check_adr_duplicate,
    extract_adr_section,
    is_adr_issue_title,
)
from events import EventType, HydraFlowEvent
from judge_calibration import judge_verdict_ledger_path, subject_for_issue
from models import ReviewResult, ReviewVerdict
from phase_utils import store_lifecycle

if TYPE_CHECKING:
    import asyncio

    from config import HydraFlowConfig
    from events import EventBus
    from models import Task
    from ports import IssueStorePort, PRPort
    from review_advisor import PostVerifyResult, ReviewPlan
    from state import StateTracker
    from task_source import TaskTransitioner

#: The ADR-review surface declares its corpus path explicitly for
#: blast-radius classification — see the note in ``_phase.py`` history
#: (#10371): with no ``+++ b/`` headers to read, ``classify_diff`` would
#: return "unclassed" and silently deny the ADR its independent verdict.
_ADR_REVIEW_CLASSIFICATION_PATHS: tuple[str, ...] = ("docs/adr/",)

logger = logging.getLogger("hydraflow.review_phase")


class AdrReviewMixin:
    """ADR-review surface of ``ReviewPhase`` (#10371)."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewPhase.__init__`` or by a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would win over the real
    # implementation whenever this mixin precedes the implementing one
    # in ``ReviewPhase``'s MRO.
    # ------------------------------------------------------------------
    _advisor_pre_flight_plan: dict[tuple[str, int], ReviewPlan]
    _bus: EventBus
    _config: HydraFlowConfig
    _post_verify_runner: Any
    _prs: PRPort
    _state: StateTracker
    _stop_event: asyncio.Event
    _store: IssueStorePort
    _transitioner: TaskTransitioner

    if TYPE_CHECKING:

        async def _run_post_verify_for_surface(
            self,
            *,
            surface: str,
            diff: str,
            spec: str | None,
            executor_verdict_summary: str,
            executor_fix_diff: str | None = None,
            pre_flight_plan: ReviewPlan | None = None,
            attempt_number: int = 0,
            issue_number: int,
            log_pr_number: int | None = None,
            lens: Literal["correctness", "security", "spec"] | None = None,
            classification_paths: list[str] | None = None,
        ) -> PostVerifyResult | None: ...  # provided by _advisors

    async def review_adrs(self, issues: list[Task]) -> list[ReviewResult]:
        """Review ADR issues that intentionally have no PR."""
        adr_issues = [issue for issue in issues if is_adr_issue_title(issue.title)]
        if not adr_issues:
            return []

        results: list[ReviewResult] = []
        for issue in adr_issues:
            if self._stop_event.is_set():
                break
            async with store_lifecycle(self._store, issue.id, "review"):
                adr_result = await self._review_single_adr(issue)
                if adr_result.merged:
                    self._store.mark_merged(issue.id)
                results.append(adr_result)
        return results

    async def _review_single_adr(self, issue: Task) -> ReviewResult:
        """Validate ADR quality and either finalize or escalate to HITL.

        T26: PreFlightAdvisor (AlwaysTrigger) runs after the duplicate guard
        and before the structural validator; PostVerifyAdvisor runs after
        the structural validator approves and gates the finalize path. Both
        use surface ``"adr_review"`` (no mid-flight — ADRs have no fix loop).
        On VETO the advisor's reasoning is folded into the existing
        requeue-to-plan path so the author can revise the ADR draft.
        """
        topic_key = check_adr_duplicate(issue.title, self._config.repo_root)
        if topic_key:
            await self._transitioner.post_comment(
                issue.id,
                f"## Closing as Duplicate\n\n"
                f"An ADR already exists for this topic in `docs/adr/`. "
                f"Normalized topic: *{topic_key}*",
            )
            await self._transitioner.close_task(issue.id)
            self._state.mark_issue(issue.id, "completed")
            logger.info(
                "ADR issue #%d closed as duplicate — topic %r exists in docs/adr/",
                issue.id,
                topic_key,
            )
            return ReviewResult(
                pr_number=0,
                issue_number=issue.id,
                verdict=ReviewVerdict.APPROVE,
                summary="Closed as duplicate ADR",
                merged=True,
            )

        # T26 pre-flight (AlwaysTrigger). The ADR body is the "diff" for the
        # advisor — there is no PR or unified diff. Plan is keyed by
        # ``("adr_review", issue.id)`` (T38; no PR number, surface-scoped)
        # and consumed by the post-verify call below for plan-aware
        # second-opinion.
        adr_content = issue.body or ""
        self._advisor_pre_flight_plan.pop(("adr_review", issue.id), None)
        await self._run_pre_flight_advisor_for_adr(issue=issue, diff=adr_content)

        reasons = adr_validation_reasons(issue.body)
        decision_detail = extract_adr_section(issue.body, "decision")
        if len(decision_detail.strip()) < 60:
            reasons.append(
                "Decision section lacks actionable detail (minimum 60 chars)"
            )

        if reasons:
            # Re-queue for planning instead of HITL — ADR needs author fixes
            await self._prs.post_comment(
                issue.id,
                "## ADR Review — Changes Needed\n\n"
                "The ADR draft needs fixes before finalization.\n\n"
                "**Required fixes:**\n"
                + "\n".join(f"- {reason}" for reason in reasons)
                + "\n\nUpdate the ADR and re-label to re-enter the pipeline.",
            )
            if issue is not None:
                self._store.enqueue_transition(issue, "plan")
            await self._transitioner.transition(issue.id, "plan")
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_REROUTE,
                    data={
                        "issue": issue.id,
                        "action": "requeued_to_plan",
                        "reasons": reasons,
                    },
                )
            )
            return ReviewResult(
                pr_number=0,
                issue_number=issue.id,
                verdict=ReviewVerdict.REQUEST_CHANGES,
                summary=f"ADR re-queued for fixes: {'; '.join(reasons)}",
            )

        # T26 post-verify (veto). The structural validator returned APPROVE
        # ("no reasons") — give the advisor a chance to second-opinion the
        # ADR's content before finalize. On VETO, requeue to plan with the
        # advisor's reasoning so the author can revise. ADR has no fix loop
        # (mid_flight=False), so this is a one-shot binary gate, mirroring
        # the pre_merge_spec_check pattern.
        veto_result = await self._run_post_verify_advisor_for_adr(
            issue=issue,
            diff=adr_content,
            executor_verdict_summary="ADR structural validation passed",
        )
        if veto_result is not None:
            return veto_result

        await self._transitioner.post_comment(
            issue.id,
            "## ADR Review Approved\n\n"
            "ADR draft validated and finalized by the review phase.\n\n"
            "Closing issue as complete.",
        )
        await self._prs.swap_pipeline_labels(issue.id, self._config.fixed_label[0])
        await self._transitioner.close_task(issue.id)
        self._state.mark_issue(issue.id, "completed")
        self._state.record_issue_completed()
        self._state.increment_session_counter("reviewed")
        return ReviewResult(
            pr_number=0,
            issue_number=issue.id,
            verdict=ReviewVerdict.APPROVE,
            summary="ADR review approved",
            merged=True,
        )

    async def _run_pre_flight_advisor_for_adr(
        self,
        *,
        issue: Task,
        diff: str,
    ) -> None:
        """Run :class:`PreFlightAdvisor` for the ``adr_review`` surface (T26).

        ADR review has no PR; this thin wrapper mirrors
        ``_run_pre_flight_advisor`` but keys ``self._advisor_pre_flight_plan``
        by ``("adr_review", issue.id)`` (T38) and the log path by
        ``issue.id`` instead of ``pr.number``. Same advisor logic, same
        kill-switch behaviour, same scratchpad convention. The trigger is
        :class:`AlwaysTrigger` per spec, so the advisor runs whenever the
        surface kill-switch allows.

        Function-local imports keep the dependency on ``review_advisor``
        contained to where it's used and avoid the auto-lint hook stripping
        an "unused" top-level import.
        """
        from review_advisor import (  # noqa: PLC0415
            PreFlightAdvisor,
            PreFlightInput,
            build_surface_config,
            diff_stats_from_text,
            is_advisor_enabled,
        )

        surface = "adr_review"
        surface_cfg = build_surface_config(surface)
        if (
            not surface_cfg.pre_flight_enabled
            or surface_cfg.pre_flight_trigger is None
            or not is_advisor_enabled(surface, "pre_flight")
        ):
            return

        diff_stats = diff_stats_from_text(diff)
        from review_advisor import PRContext  # noqa: PLC0415

        pr_ctx = PRContext(prior_fix_attempts=0)
        if not surface_cfg.pre_flight_trigger.should_run(diff_stats, pr_ctx):
            return

        log_path = (
            self._config.repo_root
            / "review_logs"
            / str(issue.id)
            / "advisor_session.jsonl"
        )
        advisor = PreFlightAdvisor(
            runner=self._post_verify_runner,
            surface_config=surface_cfg,
            log_path=log_path,
            pr_number=issue.id,
            # #10836 phase 2: the pre-PR path has no PR yet — join by issue,
            # the same fallback PostVerifyAdvisor's recorder uses.
            judge_verdict_ledger_path=judge_verdict_ledger_path(self._config.data_root),
            calibration_subject_id=subject_for_issue(issue.id),
        )
        # Human-on-the-loop continuous steering (ADR-0099 #4): the advisor
        # reviews the same issue as the executor, so live operator guidance
        # should reach its prompt too.
        human_guidance = self._state.get_human_steering(str(issue.id)).guidance or ""
        try:
            plan = await advisor.run(
                PreFlightInput(
                    surface=surface,
                    diff=diff,
                    spec=issue.body or None,
                    related_paths=diff_stats.changed_paths,
                    prior_attempts=0,
                    issue_number=issue.id,
                    human_guidance=human_guidance,
                )
            )
        except Exception as exc:
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            reraise_on_credit_or_bug(exc)
            logger.warning(
                "pre_flight advisor errored for ADR issue #%d — "
                "proceeding without plan",
                issue.id,
                exc_info=True,
            )
            return

        if plan is None:
            return
        self._advisor_pre_flight_plan[("adr_review", issue.id)] = plan
        scratchpad = (
            self._config.repo_root / "review_logs" / str(issue.id) / "preflight.json"
        )
        try:
            scratchpad.parent.mkdir(parents=True, exist_ok=True)
            scratchpad.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        except Exception:
            logger.debug("preflight scratchpad write failed", exc_info=True)

    async def _run_post_verify_advisor_for_adr(
        self,
        *,
        issue: Task,
        diff: str,
        executor_verdict_summary: str,
    ) -> ReviewResult | None:
        """Run :class:`PostVerifyAdvisor` for the ``adr_review`` surface (T26).

        Returns a :class:`ReviewResult` (REQUEST_CHANGES) when the advisor
        VETOes — the caller skips the finalize/approve path. Returns
        ``None`` when the advisor APPROVEs, the kill-switches are off, or
        the advisor degrades on a non-fatal error (proceed with finalize).

        ADR review has no fix loop (``mid_flight_enabled=False``), so this
        is a one-shot binary gate — there's no executor fix step that a
        retry could give different input to. On VETO we requeue the issue
        to ``plan`` with the advisor's reasoning, mirroring the existing
        structural-validation requeue path. ``reraise_on_credit_or_bug``
        discipline is preserved inside :meth:`_run_post_verify_for_surface`
        per ``docs/wiki/dark-factory.md`` §2.2.

        T29 self-modification guard: when the ADR content touches advisor's
        own implementation files, ``resolve_post_verify_authority`` forces
        veto authority regardless of surface config.
        """
        pv_result = await self._run_post_verify_for_surface(
            surface="adr_review",
            diff=diff,
            spec=issue.body or None,
            executor_verdict_summary=executor_verdict_summary,
            pre_flight_plan=self._advisor_pre_flight_plan.get(("adr_review", issue.id)),
            issue_number=issue.id,
            # #10371: the ADR body carries no unified-diff headers; declare the
            # ADR corpus path so the change classifies as STRUCTURAL (and, with
            # the independence flag on, routes to an independent judge family)
            # instead of silently falling through as "unclassed".
            classification_paths=list(_ADR_REVIEW_CLASSIFICATION_PATHS),
        )
        if pv_result is None or pv_result.verdict != "VETO":
            return None

        # VETO — requeue to plan with the advisor's reasoning surfaced.
        logger.warning(
            "ADR issue #%d post_verify VETO from advisor — requeueing to plan",
            issue.id,
        )
        veto_reason = pv_result.reasoning or "advisor vetoed without reasoning"
        suggested = pv_result.suggested_fix_direction
        comment_lines = [
            "## ADR Review — Advisor Veto",
            "",
            "The ADR draft passed structural validation but the post-verify "
            "advisor flagged blocking concerns:",
            "",
            f"**Reasoning:** {veto_reason}",
        ]
        if pv_result.disagreements:
            comment_lines.append("")
            comment_lines.append("**Disagreements:**")
            for d in pv_result.disagreements:
                comment_lines.append(f"- [{d.severity}] {d.advisor_assessment}")
        if suggested:
            comment_lines.append("")
            comment_lines.append(f"**Suggested direction:** {suggested}")
        comment_lines.append("")
        comment_lines.append("Update the ADR and re-label to re-enter the pipeline.")
        await self._prs.post_comment(issue.id, "\n".join(comment_lines))

        if issue is not None:
            self._store.enqueue_transition(issue, "plan")
        await self._transitioner.transition(issue.id, "plan")
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_REROUTE,
                data={
                    "issue": issue.id,
                    "action": "requeued_to_plan",
                    "reasons": [f"advisor veto: {veto_reason}"],
                },
            )
        )
        return ReviewResult(
            pr_number=0,
            issue_number=issue.id,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary=f"ADR re-queued — advisor veto: {veto_reason}",
        )
