"""Visual-validation + visual merge-gate slice of ``ReviewPhase``.

Extracted VERBATIM from ``_phase.py`` (the review-phase line-count god,
#10840 concentration work) as a mixin — the same decomposition pattern the
``src/state/`` package uses. ``ReviewPhase`` inherits this mixin, so every
existing surface is unchanged: ``ReviewPhase.check_visual_gate`` still
resolves, instance/class-level patching in tests still lands, and bound-method
identity semantics are preserved.

Three sub-concerns, all "visual" checks on a PR:

* review-time visual validation — ``_compute_visual_validation`` /
  ``_run_visual_validation`` / ``_handle_visual_failure``;
* the pre-merge visual gate, incl. the T27 PostVerifyAdvisor second opinion —
  ``check_visual_gate`` and its ``_run_visual_gate_advisor`` /
  ``_build_visual_diff_descriptor`` / ``_emit_visual_gate_telemetry`` /
  ``_handle_visual_gate_pass`` / ``_handle_visual_gate_failure`` /
  ``_invoke_visual_pipeline`` helpers;
* HITL escalation carrying visual evidence — ``escalate_visual_failure``.

Cross-slice collaborators (``_publish_review_status``, ``_escalate_to_hitl``,
``_run_post_verify_for_surface``) are provided by ``ReviewPhase`` in
``_phase.py`` and declared below under ``if TYPE_CHECKING:`` — a *runtime*
stub body would be a real class attribute and would win the MRO over a
sibling mixin's implementation the moment ``ReviewPhase`` inherits more than
one mixin (#11629).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Literal

# Late-binding access for ``review_phase.record_harness_failure`` — tests
# patch it via ``unittest.mock.patch("review_phase.record_harness_failure")``,
# so call sites must look the attribute up at *call time* on the package
# module object rather than caching a local binding at import time. Same
# circular-safe pattern as ``_phase.py``: the package is already in
# ``sys.modules`` (partially initialized) when this submodule loads.
import review_phase
from events import EventType, HydraFlowEvent
from harness_insights import FailureCategory
from models import (
    HitlEscalation,
    PipelineStage,
    ReviewVerdict,
    VisualGatePayload,
    VisualScreenResult,
)

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig
    from events import EventBus
    from harness_insights import HarnessInsightStore
    from models import (
        PRInfo,
        ReviewResult,
        Task,
        VisualEvidence,
        VisualValidationDecision,
        VisualValidationReport,
    )
    from ports import PRPort
    from review_advisor import PostVerifyResult, ReviewPlan
    from visual_validator import VisualValidator

logger = logging.getLogger("hydraflow.review_phase")


class VisualGateMixin:
    """Visual-validation + visual-gate methods mixed into ``ReviewPhase``."""

    # --- attributes provided by ``ReviewPhase.__init__`` (_phase.py) ---
    _config: HydraFlowConfig
    _prs: PRPort
    _bus: EventBus
    _visual_validator: VisualValidator | None
    _harness_insights: HarnessInsightStore | None

    # --- cross-slice methods provided by sibling mixins ---
    #
    # TYPE_CHECKING-only on purpose: a runtime ``...`` body would be a real
    # class attribute and would win the MRO over a sibling mixin's
    # implementation (#11629). That matters concretely here:
    # ``_publish_review_status`` / ``_escalate_to_hitl`` live in ``_insights``
    # and ``_run_post_verify_for_surface`` in ``_advisors`` (Refs #11547), all
    # of which follow this mixin in ``ReviewPhase``'s MRO.
    if TYPE_CHECKING:

        async def _publish_review_status(
            self, pr: PRInfo, worker_id: int, status: str
        ) -> None: ...

        async def _escalate_to_hitl(self, esc: HitlEscalation) -> None: ...

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
        ) -> PostVerifyResult | None: ...

    def _compute_visual_validation(
        self, diff: str, task: Task
    ) -> VisualValidationDecision | None:
        """Compute the visual validation decision for a PR diff."""
        if not self._config.visual_validation_enabled:
            return None
        from visual_validation import compute_visual_validation  # noqa: PLC0415

        return compute_visual_validation(
            self._config,
            diff,
            issue_labels=task.tags,
            issue_comments=task.comments,
        )

    async def _run_visual_validation(
        self, pr: PRInfo, wt_path: Path, worker_id: int
    ) -> VisualValidationReport | None:
        """Run visual validation if enabled. Returns None when disabled or on error."""
        if self._visual_validator is None:
            return None
        try:
            await self._publish_review_status(pr, worker_id, "visual_check")
            # The check_fn is a placeholder — real implementations would inject
            # an actual screenshot capture + diffing callable.  For now the
            # validator infrastructure is wired up but produces an empty report
            # unless a check function is supplied externally.
            report = await self._visual_validator.validate_screens(
                [], self._noop_visual_check
            )
            if report.screens:
                logger.info(
                    "PR #%d: visual validation %s (%d screens, %d retries)",
                    pr.number,
                    report.overall_verdict.value,
                    len(report.screens),
                    report.total_retries,
                )
            return report
        except (RuntimeError, OSError):
            logger.warning(
                "Visual validation failed for PR #%d — skipping",
                pr.number,
                exc_info=True,
            )
            return None

    @staticmethod
    async def _noop_visual_check(screen_name: str) -> VisualScreenResult:
        """Default no-op visual check (placeholder for real implementation)."""
        return VisualScreenResult(screen_name=screen_name, diff_ratio=0.0)

    async def _handle_visual_failure(
        self,
        pr: PRInfo,
        task: Task,
        result: ReviewResult,
        report: VisualValidationReport,
        worker_id: int,
    ) -> ReviewResult:
        """Handle a visual validation failure — escalate to HITL with report details."""
        summary_text = report.format_summary()

        if report.infra_failures > 0 and report.visual_diffs == 0:
            cause = "Visual validation infrastructure failure (not a visual diff)"
        else:
            cause = "Visual validation detected failures"

        await self._publish_review_status(pr, worker_id, "escalating")
        await self._escalate_to_hitl(
            HitlEscalation(
                issue_number=task.id,
                pr_number=pr.number,
                cause=cause,
                origin_label=self._config.review_label[0],
                comment=(
                    f"**Visual validation failed** — escalating to human review.\n\n"
                    f"{summary_text}"
                ),
                event_cause="visual_validation_failed",
                extra_event_data={
                    "visual_verdict": report.overall_verdict.value,
                    "visual_retries": report.total_retries,
                    "infra_failures": report.infra_failures,
                    "visual_diffs": report.visual_diffs,
                },
                task=task,
            )
        )
        result.verdict = ReviewVerdict.REQUEST_CHANGES
        result.summary = f"Visual validation failed: {cause}"
        return result

    async def check_visual_gate(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        worker_id: int,
    ) -> bool:
        """Run visual validation gate before merge finalization.

        Returns True if merge may proceed, False to block.
        When the gate is bypassed an audit event is emitted.

        T27: PostVerifyAdvisor (surface=``visual_gate``) wraps the visual
        pipeline's PASS verdict. The visual_gate surface is post-verify
        only (no pre-flight, no mid-flight) so this is a one-shot binary
        gate — VETO blocks the merge and routes
        through the existing failure/escalation path with the advisor's
        reasoning attached. APPROVE / disabled / degraded all fall through
        to the existing PASS sign-off behaviour.
        """
        start = time.monotonic()

        if not self._config.visual_gate_enabled:
            return True

        # Emergency bypass — allow merge but log an audit event
        if self._config.visual_gate_bypass:
            logger.warning(
                "PR #%d: visual gate BYPASSED (emergency kill-switch)",
                pr.number,
            )
            if self._bus:
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.VISUAL_GATE,
                        data=VisualGatePayload(
                            pr=pr.number,
                            issue=issue.id,
                            worker=worker_id,
                            verdict="bypass",
                            reason="emergency kill-switch active",
                            runtime_seconds=round(time.monotonic() - start, 3),
                        ),
                    )
                )
            result.visual_passed = True
            return True

        verdict, artifacts, reason = await self._invoke_visual_pipeline(
            pr, issue, worker_id
        )

        runtime = round(time.monotonic() - start, 3)

        # Emit gate telemetry
        await self._emit_visual_gate_telemetry(
            pr, issue, worker_id, verdict, reason, runtime, artifacts
        )

        if verdict == "pass":
            # T27: post-verify advisor second-opinions the visual pipeline's
            # PASS verdict. VETO blocks the merge and routes through the
            # existing failure path; APPROVE / kill-switch off / degraded
            # falls through to the sign-off path unchanged.
            advisor_block_reason = await self._run_visual_gate_advisor(
                pr=pr,
                issue=issue,
                executor_verdict_summary=verdict,
                pipeline_reason=reason,
                artifacts=artifacts,
            )
            if advisor_block_reason is not None:
                await self._handle_visual_gate_failure(
                    pr,
                    issue,
                    result,
                    verdict="advisor_veto",
                    reason=advisor_block_reason,
                )
                return False
            await self._handle_visual_gate_pass(pr, result, verdict, runtime, artifacts)
            return True

        await self._handle_visual_gate_failure(pr, issue, result, verdict, reason)
        return False

    async def _run_visual_gate_advisor(
        self,
        *,
        pr: PRInfo,
        issue: Task,
        executor_verdict_summary: str,
        pipeline_reason: str,
        artifacts: dict[str, str],
    ) -> str | None:
        """Run :class:`PostVerifyAdvisor` for the ``visual_gate`` surface (T27).

        Returns the advisor's VETO reasoning string (caller must block the
        merge) when the advisor VETOes; ``None`` when the advisor APPROVEs,
        the surface/role kill-switches are off, or the advisor degrades on
        a non-fatal error (proceed with the visual pipeline's PASS verdict).

        The "diff" passed to the advisor is a textual descriptor of the
        visual diff (verdict, pipeline reason, artifact links/count) — not
        a unified text diff. Visual gate has ``mid_flight_enabled=False``
        and ``pre_flight_enabled=False``, so this is a one-shot binary gate
        — a single advisor call, no retry budget, no plan threading, no
        fix-and-iterate loop. ``reraise_on_credit_or_bug``
        discipline is preserved inside :meth:`_run_post_verify_for_surface`
        per ``docs/wiki/dark-factory.md`` §2.2.

        T29 self-modification guard: visual_gate has no diff to inspect for
        self-modifying paths, so the descriptor is passed for completeness
        but will not normally trigger the guard. The descriptor is non-empty
        — the advisor needs *something* to evaluate.
        """
        diff_descriptor = self._build_visual_diff_descriptor(
            pr=pr,
            issue=issue,
            executor_verdict_summary=executor_verdict_summary,
            pipeline_reason=pipeline_reason,
            artifacts=artifacts,
        )

        pv_result = await self._run_post_verify_for_surface(
            surface="visual_gate",
            diff=diff_descriptor,
            spec=issue.body or None,
            executor_verdict_summary=executor_verdict_summary,
            issue_number=issue.id,
            log_pr_number=pr.number,
        )
        if pv_result is None or pv_result.verdict != "VETO":
            return None

        logger.warning(
            "PR #%d visual_gate VETO from advisor — blocking merge",
            pr.number,
        )
        veto_reason = pv_result.reasoning or "advisor vetoed without reasoning"
        return f"advisor veto: {veto_reason}"

    def _build_visual_diff_descriptor(
        self,
        *,
        pr: PRInfo,
        issue: Task,
        executor_verdict_summary: str,
        pipeline_reason: str,
        artifacts: dict[str, str],
    ) -> str:
        """Render a textual descriptor of the visual gate's evidence.

        The visual gate has no unified text diff — the advisor's input
        is a synthesized summary of the visual pipeline's verdict, the
        pipeline's reason string, and links/keys for any artifacts the
        pipeline produced (baseline, diff image, report URL). Always
        non-empty so the advisor has *something* to evaluate.
        """
        lines = [
            f"PR #{pr.number} — visual gate evidence",
            f"Issue: {issue.id}",
            f"Pipeline verdict: {executor_verdict_summary}",
            f"Pipeline reason: {pipeline_reason or '(none)'}",
        ]
        if artifacts:
            lines.append(f"Artifact count: {len(artifacts)}")
            for name, link in sorted(artifacts.items()):
                lines.append(f"- {name}: {link}")
        else:
            lines.append("Artifacts: (none)")
        return "\n".join(lines)

    async def _emit_visual_gate_telemetry(
        self,
        pr: PRInfo,
        issue: Task,
        worker_id: int,
        verdict: str,
        reason: str,
        runtime: float,
        artifacts: dict[str, str],
    ) -> None:
        """Emit a VISUAL_GATE event with pipeline results."""
        if self._bus:
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.VISUAL_GATE,
                    data=VisualGatePayload(
                        pr=pr.number,
                        issue=issue.id,
                        worker=worker_id,
                        verdict=verdict,
                        reason=reason,
                        runtime_seconds=runtime,
                        retries=0,
                        artifact_count=len(artifacts),
                        artifacts=artifacts,
                    ),
                )
            )

    async def _handle_visual_gate_pass(
        self,
        pr: PRInfo,
        result: ReviewResult,
        verdict: str,
        runtime: float,
        artifacts: dict[str, str],
    ) -> None:
        """Post sign-off comment and mark visual gate as passed."""
        result.visual_passed = True
        sign_off = (
            f"**Visual Gate: PASSED**\n\n"
            f"Visual validation completed successfully.\n"
            f"Verdict: `{verdict}` | Runtime: {runtime}s"
        )
        if artifacts:
            sign_off += "\n\n**Artifacts:**\n"
            for name, link in artifacts.items():
                sign_off += f"- [{name}]({link})\n"
        try:
            await self._prs.post_pr_comment(pr.number, sign_off)
        except (RuntimeError, OSError):
            logger.warning(
                "PR #%d: could not post visual gate sign-off comment",
                pr.number,
                exc_info=True,
            )

    async def _handle_visual_gate_failure(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        verdict: str,
        reason: str,
    ) -> None:
        """Post block comment, escalate to HITL, and mark visual gate as failed."""
        result.visual_passed = False
        logger.warning(
            "PR #%d: visual gate BLOCKED (verdict=%s) — blocking merge",
            pr.number,
            verdict,
        )
        try:
            await self._prs.post_pr_comment(
                pr.number,
                f"**Visual Gate: BLOCKED**\n\n"
                f"Verdict: `{verdict}` — {reason}\n"
                f"Escalating to human review.",
            )
        except (RuntimeError, OSError):
            logger.warning(
                "PR #%d: could not post visual gate block comment",
                pr.number,
                exc_info=True,
            )
        await self._escalate_to_hitl(
            HitlEscalation(
                issue_number=pr.issue_number,
                pr_number=pr.number,
                cause=f"Visual gate {verdict}",
                origin_label=self._config.review_label[0],
                comment=f"Visual gate verdict: {verdict} — {reason}",
                event_cause="visual_gate_failed",
                task=issue,
            )
        )

    async def _invoke_visual_pipeline(
        self,
        pr: PRInfo,
        issue: Task,  # noqa: ARG002
        worker_id: int,  # noqa: ARG002
    ) -> tuple[str, dict[str, str], str]:
        """Invoke a configured visual validation service.

        Returns (verdict, artifacts, reason).
        Override or mock this method in tests to exercise fail paths.

        The default implementation intentionally fails closed. HydraFlow does
        not trust screenshot/pixel-baseline tests as a merge oracle, so enabling
        the visual gate without wiring a real semantic validator must block.
        """
        reason = (
            "visual gate is enabled but no semantic visual validation service "
            "is configured"
        )
        logger.error(
            "PR #%d: %s; blocking merge",
            pr.number,
            reason,
        )
        return "fail", {}, reason

    async def escalate_visual_failure(
        self,
        issue_number: int,
        pr_number: int | None,
        evidence: VisualEvidence,
        *,
        task: Task | None = None,
    ) -> None:
        """Escalate a visual validation failure to HITL with evidence.

        Convenience wrapper around ``_escalate_to_hitl`` that records the
        visual evidence, picks the appropriate failure category, and
        builds a descriptive comment.
        """
        fail_items = [i for i in evidence.items if i.status == "fail"]
        warn_items = [i for i in evidence.items if i.status == "warn"]

        category = (
            FailureCategory.VISUAL_FAIL if fail_items else FailureCategory.VISUAL_WARN
        )
        review_phase.record_harness_failure(
            self._harness_insights,
            issue_number,
            category,
            evidence.summary or f"{len(fail_items)} fail(s), {len(warn_items)} warn(s)",
            pr_number=pr_number or 0,
            stage=PipelineStage.REVIEW,
        )

        screen_lines = []
        for item in evidence.items:
            if item.status in ("fail", "warn"):
                label = "FAIL" if item.status == "fail" else "WARN"
                screen_lines.append(
                    f"- **{item.screen_name}** — {item.diff_percent:.1f}% diff [{label}]"
                )

        comment = (
            "## Visual Validation Failed\n\n"
            + (evidence.summary + "\n\n" if evidence.summary else "")
            + (
                "**Affected screens:**\n" + "\n".join(screen_lines) + "\n\n"
                if screen_lines
                else ""
            )
            + (f"[View run]({evidence.run_url})\n\n" if evidence.run_url else "")
            + "Escalating to human review."
        )

        cause = (
            f"Visual validation failed: {evidence.summary}"
            if evidence.summary
            else "Visual validation failed"
        )

        await self._escalate_to_hitl(
            HitlEscalation(
                issue_number=issue_number,
                pr_number=pr_number,
                cause=cause,
                origin_label=self._config.review_label[0],
                comment=comment,
                event_cause="visual_validation_failed",
                task=task,
                visual_evidence=evidence,
            )
        )
