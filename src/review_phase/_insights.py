"""Review-insight recording, status publishing, and HITL escalation.

Extracted VERBATIM from ``_phase.py`` (god-class decomposition, Refs #11547)
as a mixin — the same shape ``_visual_gate.py`` took in the #10840 pass.
``ReviewPhase`` inherits it, so every method here still resolves as an
attribute of ``ReviewPhase`` and instance/class-level patching in tests still
lands.

One concern: what the phase *reports* once a review is decided — recording the
insight record (and the stale-proposal / persistent-finding follow-ups it can
spawn), publishing review status, escalating to HITL, and the adversarial
council threshold that decides whether a summary warrants a second reviewer.

``CATEGORY_DESCRIPTIONS`` / ``verify_proposals`` / ``_PROPOSAL_STALE_DAYS``
are read by ``_record_review_insight`` and so are imported here; tests that
patched them at ``review_phase._phase.<name>`` now target
``review_phase._insights.<name>`` — the same target migration
``pr_manager_promotion.run_subprocess`` took in #10840.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import review_phase
from events import EventType, HydraFlowEvent
from models import HitlEscalation
from phase_utils import publish_review_status
from review_insights import (
    _PROPOSAL_STALE_DAYS,
    CATEGORY_DESCRIPTIONS,
    PERSISTENT_FINDING_PREFIX,
    ReviewRecord,
    build_insight_issue_body,
    build_persistent_finding_body,
    extract_categories,
    is_infra_failure_summary,
    reconcile_closed_insight_escalations,
    verify_proposals,
)

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig
    from events import EventBus
    from models import CodeScanningAlert, PRInfo, ReviewResult, StatusCallback, Task
    from ports import IssueStorePort, PRPort, ReviewInsightStorePort
    from retrospective_queue import RetrospectiveQueue
    from review_advisor import ReviewPlan
    from reviewer import ReviewRunner
    from state import StateTracker
    from task_source import TaskTransitioner

#: Mirrors ``retrospective_loop._INSIGHT_DEDUP_WINDOW``. Two PR reviews
#: completing back-to-back for the same stale category could otherwise both
#: call ``find_existing_issue`` before either write is indexed by GitHub
#: search, and both file. The window is intentionally identical between sites
#: so behavior is uniform whether the loop or the fallback fires (#8988).
_INSIGHT_DEDUP_WINDOW = timedelta(hours=1)

logger = logging.getLogger("hydraflow.review_phase")


class ReviewInsightsMixin:
    """Review-insight recording, status publishing, and HITL escalation."""

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
    _insight_escalated_at: dict[str, datetime]
    _insights: ReviewInsightStorePort
    _prs: PRPort
    _retrospective_queue: RetrospectiveQueue | None
    _reviewers: ReviewRunner
    _state: StateTracker
    _store: IssueStorePort
    _transitioner: TaskTransitioner
    _update_bg_worker_status: StatusCallback | None

    async def _record_review_insight(self, result: ReviewResult) -> None:
        """Record a review result and file improvement proposals if patterns emerge.

        Wrapped in try/except so insight failures never interrupt the review flow.
        """
        status = "ok"
        details: dict[str, object] = {
            "issue_number": result.issue_number,
            "pr_number": result.pr_number,
        }
        # API-error / credit-exhaustion summaries are agent-layer telemetry,
        # not a reviewer verdict. Recording them as review feedback poisons
        # the per-category counts (e.g. ``"type":"error"`` was mis-read as a
        # type-annotation flag) and drives perpetual false stale-insight HITL
        # escalations (#9426). Skip the append for these.
        if is_infra_failure_summary(result.summary):
            details["skipped"] = "infra_failure_summary"
            if self._update_bg_worker_status:
                try:
                    self._update_bg_worker_status("retrospective", "ok", details)
                except (RuntimeError, OSError):
                    logger.warning(
                        "retrospective status callback failed for PR #%d",
                        result.pr_number,
                        exc_info=True,
                    )
            return
        try:
            record = ReviewRecord(
                pr_number=result.pr_number,
                issue_number=result.issue_number,
                timestamp=datetime.now(UTC).isoformat(),
                verdict=result.verdict,
                summary=result.summary,
                fixes_made=result.fixes_made,
                categories=extract_categories(result.summary),
                raw_feedback=result.transcript,
            )
            self._insights.append_review(record)

            # Dual-write to Hindsight removed in Phase 3 cutover.

            # Enqueue pattern analysis for the retrospective loop
            if self._retrospective_queue is not None:
                from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

                self._retrospective_queue.append(
                    QueueItem(
                        kind=QueueKind.REVIEW_PATTERNS,
                        pr_number=result.pr_number,
                        issue_number=result.issue_number,
                    )
                )
            else:
                # Fallback: inline analysis when queue not wired
                recent = self._insights.load_recent(self._config.review_insight_window)
                patterns = review_phase.analyze_patterns(
                    recent, self._config.review_pattern_threshold
                )
                proposed = self._insights.get_proposed_categories()

                for category, count, evidence in patterns:
                    if category in proposed:
                        continue
                    body = build_insight_issue_body(
                        category, count, len(recent), evidence
                    )
                    desc = CATEGORY_DESCRIPTIONS.get(category, category)
                    title = f"[Review Insight] Recurring feedback: {desc}"
                    labels = self._config.find_label[:1]
                    await self._transitioner.create_task(title, body, labels)
                    self._insights.mark_category_proposed(category)
                    self._insights.record_proposal(category, pre_count=count)

                stale = verify_proposals(self._insights, recent)
                # Dedup mirror of RetrospectiveLoop._handle_verify_proposals
                # (#8988). This fallback fires only when no retrospective_queue
                # is wired. Like the loop site it routes a stale proposal to the
                # factory as an actionable `find_label` issue (#9227) — not a
                # HITL dead-end — and skips (no duplicate, no comment spam) when
                # one is already open.
                if stale:
                    # Re-arm: any HUMAN-closed escalation clears its category
                    # from the in-memory window-tracker so a still-stale
                    # category can refile fresh. Bot-closed escalations are
                    # retained, not re-armed — same shared contract the loop
                    # site uses (#8996), via the one shared implementation so
                    # this fallback can't drift from it.
                    reconcile_labels = self._config.find_label[:1]
                    if reconcile_labels:
                        rearmed = await reconcile_closed_insight_escalations(
                            prs=self._prs,
                            insight_escalated_at=self._insight_escalated_at,
                            find_label=reconcile_labels[0],
                        )
                        if rearmed:
                            logger.info(
                                "ReviewPhase: re-armed stale-insight tracker for %s",
                                rearmed,
                            )
                now_escalated = datetime.now(UTC)
                for category in stale:
                    desc = CATEGORY_DESCRIPTIONS.get(category, category)
                    title = f"{PERSISTENT_FINDING_PREFIX}{desc}"
                    find_labels = self._config.find_label[:1]
                    # Window guard — protects against back-to-back PR
                    # reviews racing the GitHub search index, same shape
                    # as ``RetrospectiveLoop._handle_verify_proposals``.
                    last = self._insight_escalated_at.get(category)
                    if (
                        last is not None
                        and (now_escalated - last) < _INSIGHT_DEDUP_WINDOW
                    ):
                        continue
                    existing = await self._prs.find_existing_issue(title)
                    if existing:
                        # Factory is already working the routed issue — skip.
                        self._insight_escalated_at[category] = now_escalated
                        continue
                    body = build_persistent_finding_body(
                        category, desc, _PROPOSAL_STALE_DAYS
                    )
                    self._insight_escalated_at[category] = now_escalated
                    try:
                        await self._transitioner.create_task(title, body, find_labels)
                    except Exception:
                        self._insight_escalated_at.pop(category, None)
                        raise
        except (RuntimeError, OSError):
            status = "error"
            details["error"] = "review insight recording failed"
            logger.warning(
                "Review insight recording failed for PR #%d",
                result.pr_number,
                exc_info=True,
            )
        finally:
            if self._update_bg_worker_status:
                try:
                    self._update_bg_worker_status("retrospective", status, details)
                except (RuntimeError, OSError):
                    logger.warning(
                        "retrospective status callback failed for PR #%d",
                        result.pr_number,
                        exc_info=True,
                    )

    async def _publish_review_status(
        self, pr: PRInfo, worker_id: int, status: str
    ) -> None:
        """Emit a REVIEW_UPDATE event with the given status."""
        await publish_review_status(self._bus, pr, worker_id, status)

    async def _escalate_to_hitl(self, esc: HitlEscalation) -> None:
        """Route escalation through diagnostic loop instead of direct HITL."""
        from models import EscalationContext  # noqa: PLC0415

        # Build escalation context if not already stored by the call site
        existing = self._state.get_escalation_context(esc.issue_number)
        if existing is None:
            context = EscalationContext(
                cause=esc.cause,
                origin_phase="review",
                pr_number=esc.pr_number,
            )
            self._state.set_escalation_context(esc.issue_number, context)

        self._state.set_hitl_origin(esc.issue_number, esc.origin_label)
        self._state.set_hitl_cause(esc.issue_number, esc.cause)
        self._state.record_hitl_escalation()
        if esc.visual_evidence is not None:
            self._state.set_hitl_visual_evidence(esc.issue_number, esc.visual_evidence)

        if esc.task is not None:
            self._store.enqueue_transition(esc.task, "diagnose")
        await self._transitioner.transition(
            esc.issue_number, "diagnose", pr_number=esc.pr_number
        )

        if esc.post_on_pr and esc.pr_number and esc.pr_number > 0:
            await self._prs.post_pr_comment(esc.pr_number, esc.comment)
        else:
            await self._prs.post_comment(esc.issue_number, esc.comment)

        event_data: dict[str, object] = {
            "issue": esc.issue_number,
            "status": "diagnostic",
            "role": "reviewer",
            "cause": esc.event_cause or esc.cause,
        }
        if esc.pr_number and esc.pr_number > 0:
            event_data["pr"] = esc.pr_number
        if esc.visual_evidence is not None:
            event_data["visual_evidence"] = esc.visual_evidence.model_dump()
        if esc.extra_event_data:
            event_data.update(esc.extra_event_data)
        await self._bus.publish(
            HydraFlowEvent(type=EventType.HITL_ESCALATION, data=event_data)
        )

    @staticmethod
    def _count_review_findings(summary: str) -> int:
        """Count the number of findings in a review summary.

        Counts bullet points (``-`` or ``*``) and numbered items (``1.``)
        as individual findings.
        """
        lines = summary.strip().splitlines()
        count = 0
        for line in lines:
            stripped = line.strip()
            # Bullet points ("- text", "* text") or numbered items ("1. text")
            if re.match(r"^[-*]\s+\S", stripped) or re.match(r"^\d+\.\s+\S", stripped):
                count += 1
        return count

    async def _check_adversarial_threshold(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        diff: str,
        result: ReviewResult,
        worker_id: int,
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
    ) -> ReviewResult:
        """Re-review if APPROVE has too few findings and no justification.

        Returns the (possibly updated) review result.
        """
        min_findings = self._config.min_review_findings
        if min_findings <= 0:
            return result

        findings_count = self._count_review_findings(result.summary)
        has_justification = "THOROUGH_REVIEW_COMPLETE" in result.transcript

        if findings_count >= min_findings or has_justification:
            return result

        # Under threshold with no justification — re-review once
        logger.info(
            "PR #%d: APPROVE with only %d findings (min %d) and no "
            "THOROUGH_REVIEW_COMPLETE — re-reviewing",
            pr.number,
            findings_count,
            min_findings,
        )
        await self._publish_review_status(pr, worker_id, "re_reviewing")

        # Thread the pre-flight plan into retries so the executor keeps
        # the same focus rubric across the loop (T24.5 closed I3).
        # Adversarial-threshold re-review is pr_review-track only (it gates
        # PR approval), so we hard-code the surface here. T38 (M7) key:
        # ``(surface, identifier)``.
        # Human-on-the-loop continuous steering (ADR-0099 #4): re-fetch
        # guidance so a `/steer` posted mid-loop reaches this re-review too.
        human_guidance = self._state.get_human_steering(str(issue.id)).guidance or ""
        re_result = await self._reviewers.review(
            pr,
            issue,
            wt_path,
            diff,
            worker_id=worker_id,
            code_scanning_alerts=code_scanning_alerts,
            pre_flight_plan=self._advisor_pre_flight_plan.get(("pr_review", pr.number)),
            human_guidance=human_guidance,
        )

        # If re-review still under threshold without justification, accept
        # but log a warning (don't loop forever)
        re_count = self._count_review_findings(re_result.summary)
        re_justified = "THOROUGH_REVIEW_COMPLETE" in re_result.transcript
        if re_count < min_findings and not re_justified:
            logger.warning(
                "PR #%d: re-review still under threshold (%d/%d) "
                "with no justification — accepting anyway",
                pr.number,
                re_count,
                min_findings,
            )

        # If reviewer made fixes during re-review, push them
        if re_result.fixes_made:
            await self._prs.push_branch(wt_path, pr.branch)

        return re_result
