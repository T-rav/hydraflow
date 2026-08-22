"""Ultra deep-review tier of ``ReviewPhase`` (#10555).

Extracted VERBATIM from ``_phase.py`` (god-class decomposition, Refs #11547)
as a mixin — the same shape ``_visual_gate.py`` took in the #10840 pass.
``ReviewPhase`` inherits it, so every method here still resolves as an
attribute of ``ReviewPhase`` and instance/class-level patching in tests still
lands.

One concern: the opt-in second-pass "ultra" review — building its runner,
deciding whether the gate opens for a given PR, running it, and folding its
findings back into the primary review result.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from models import ReviewVerdict
from ultra_review import (
    ULTRA_MOCKWORLD_ROLE,
    UltraReviewResult,
    build_ultra_review_prompt,
    parse_ultra_findings,
    run_ultra_review,
    should_ultra_review,
    summarize_ultra_findings,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from models import PRInfo, ReviewResult
    from ports import PRPort
    from reviewer import ReviewRunner

logger = logging.getLogger("hydraflow.review_phase")


class UltraReviewMixin:
    """Ultra deep-review tier of ``ReviewPhase`` (#10555)."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewPhase.__init__`` or by a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would win over the real
    # implementation whenever this mixin precedes the implementing one
    # in ``ReviewPhase``'s MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _prs: PRPort
    _reviewers: ReviewRunner
    _ultra_runner: Any

    def _build_ultra_runner(self) -> Any:
        """Build the runner the ultra deep-review tier dispatches into (#10555).

        Mirrors ``_build_post_verify_runner``'s dual dispatch:

        * Production: routes through ``ultra_review.run_ultra_review`` which
          builds the headless ``code-review`` plugin command (keeping the
          ``--plugin-dir`` flags) and threads it through ``ReviewRunner._execute``.
        * MockWorld: scenarios attach a ``FakeLLM`` via the ``_mockworld_fake_llm``
          sentinel; the ultra payload is scripted through the existing
          ``FakeLLM.script_advisor`` / ``pop_advisor_result`` machinery under the
          ``ULTRA_MOCKWORLD_ROLE`` key, so no new fake method is needed.
        """
        parent = self

        class _UltraRunner:
            async def run(
                self,
                *,
                prompt: str,
                issue_number: int,
            ) -> UltraReviewResult:
                reviewers = parent._reviewers

                # MockWorld dispatch: mirror _build_post_verify_runner's
                # __dict__ presence check (AsyncMock auto-vivifies attributes,
                # so getattr would false-route production reviewers).
                instance_dict = getattr(reviewers, "__dict__", None) or {}
                fake_llm = instance_dict.get("_mockworld_fake_llm")
                if fake_llm is not None and getattr(
                    fake_llm, "_is_fake_adapter", False
                ):
                    if not hasattr(fake_llm, "pop_advisor_result"):
                        return UltraReviewResult(degraded=True)
                    payload = fake_llm.pop_advisor_result(
                        issue_number, ULTRA_MOCKWORLD_ROLE
                    )
                    text = payload if isinstance(payload, str) else (payload or "")
                    return parse_ultra_findings(str(text))

                return await run_ultra_review(
                    execute=reviewers._execute,
                    config=parent._config,
                    prompt=prompt,
                    cwd=parent._config.repo_root,
                )

        return _UltraRunner()

    async def _maybe_fold_ultra_review(
        self,
        pr: PRInfo,
        result: ReviewResult,
        diff: str,
    ) -> ReviewResult:
        """Run the opt-in ultra tier and fold its findings into ``result``.

        No-op (returns ``result`` unchanged) when the dial is off — the fast
        ``review_ultra_enabled`` check runs BEFORE any label read or dispatch,
        so a default review pass issues zero ultra work. When the gate opens,
        material (>= threshold) findings flip the verdict to REQUEST_CHANGES so
        the existing fix hand-back runs; sub-threshold findings post as a PR
        comment. A degraded run leaves the standard verdict intact.
        """
        if not self._config.review_ultra_enabled:
            return result
        try:
            # Label reads go through PRPort.get_issue_labels (the ISSUE labels;
            # PRPort has no PR-label read method). It lives on PRPort, not
            # IssueStorePort.
            labels = await self._prs.get_issue_labels(pr.issue_number)
        except Exception:
            logger.warning(
                "ultra-review: label read failed for issue #%d; skipping tier",
                pr.issue_number,
                exc_info=True,
            )
            return result
        if not should_ultra_review(config=self._config, issue_labels=labels, diff=diff):
            return result

        prompt = build_ultra_review_prompt(pr_number=pr.number, diff=diff)
        try:
            ultra = await self._ultra_runner.run(
                prompt=prompt, issue_number=pr.issue_number
            )
        except Exception as exc:
            from exception_classify import (  # noqa: PLC0415
                reraise_on_credit_or_bug,
            )

            reraise_on_credit_or_bug(exc)
            logger.warning(
                "ultra-review: run failed for PR #%d; verdict unchanged: %r",
                pr.number,
                exc,
            )
            return result
        return await self._fold_ultra_findings(pr, result, ultra)

    async def _fold_ultra_findings(
        self,
        pr: PRInfo,
        result: ReviewResult,
        ultra: UltraReviewResult,
    ) -> ReviewResult:
        """Fold an ultra result into the review verdict (#10555).

        * Degraded or no findings → verdict untouched.
        * Material findings → verdict flipped to REQUEST_CHANGES, findings
          appended to the summary (so the fix hand-back and re-review run).
        * Sub-threshold findings only → posted as a PR comment, verdict kept.
        """
        if ultra.degraded:
            logger.warning(
                "ultra-review: degraded for PR #%d; verdict unchanged", pr.number
            )
            return result
        if not ultra.findings:
            return result

        summary_block = summarize_ultra_findings(ultra)
        if ultra.has_material_findings:
            new_summary = (
                f"{result.summary}\n\n{summary_block}"
                if result.summary
                else summary_block
            )
            return result.model_copy(
                update={
                    "verdict": ReviewVerdict.REQUEST_CHANGES,
                    "summary": new_summary,
                }
            )

        if pr.number > 0:
            await self._prs.post_pr_comment(pr.number, summary_block)
        return result
