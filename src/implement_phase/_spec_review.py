"""The ADR-0063 W5 spec-compliance review of ``ImplementPhase``.

Extracted VERBATIM from ``src/implement_phase.py`` (god-class
decomposition, Refs #11547) as a mixin — the shape ``review_phase/`` already
uses. ``ImplementPhase`` inherits it, so every method here still resolves as
an attribute of ``ImplementPhase`` and instance/class-level patching in tests
still lands.

One concern: what runs *after* a failed attempt so the next one sees concrete
gaps — computing the branch diff, dispatching ``SpecComplianceReviewer``,
persisting the gaps into ``WorkerResultMeta`` for the retry prompt, posting the
verdict, and flagging requirements gaps the agent surfaced in its transcript.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from implement_spec_reviewer import (
    SpecReviewInput,
    compute_branch_diff,
    format_gaps_for_prior_failure,
)
from phase_utils import log_exception_with_bug_classification

if TYPE_CHECKING:
    from agent import AgentRunner
    from config import HydraFlowConfig
    from implement_spec_reviewer import SpecComplianceReviewer
    from models import Task, WorkerResult
    from ports import PRPort
    from state import StateTracker
    from task_source import TaskTransitioner

logger = logging.getLogger("hydraflow.implement_phase")


class ImplementSpecReviewMixin:
    """The ADR-0063 W5 spec-compliance review of ``ImplementPhase``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ImplementPhase.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``ImplementPhase``'s MRO.
    # ------------------------------------------------------------------
    _agents: AgentRunner
    _config: HydraFlowConfig
    _prs: PRPort
    _spec_reviewer: SpecComplianceReviewer | None
    _state: StateTracker
    _transitioner: TaskTransitioner

    if TYPE_CHECKING:

        def _read_plan_for_recording(
            self, issue_number: int
        ) -> str: ...  # provided by _build

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
