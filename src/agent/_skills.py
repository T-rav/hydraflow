"""Skill execution and independent verification for ``AgentRunner``.

Extracted VERBATIM from ``src/agent.py`` (god-class decomposition,
Refs #11547) as a mixin.

One concern: running a gated skill to completion — the spawn itself and
the independent verifier (whose model must differ from the runner's).

The seven one-line ``skill_gate`` delegators (``_run_skill_check`` and
friends) deliberately stayed in ``_runner.py``: each passes ``self`` to a
``skill_gate`` function annotated ``runner: AgentRunner``, so they only
type-check where ``self`` IS the host class.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner
from models import (
    LoopResult,
    Task,
    TestAdequacyOutcome,
)
from skill_gate import SkillCheckOutcome
from skill_registry import AgentSkill

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tracing_context import TracingContext


logger = logging.getLogger("hydraflow.agent")


class AgentSkillMixin(BaseRunner):
    """Skill execution and independent verification for ``AgentRunner``.

    Inherits ``BaseRunner``: these slices call ``self._execute`` /
    ``self._build_command`` and one delegates to ``super()._verify_quality``,
    so the base has to sit in the MIXIN's own MRO, not only in
    ``AgentRunner``'s. It also keeps the runner-scoped gates enumerating every
    file that holds a spawn site.
    """

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``AgentRunner.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------

    if TYPE_CHECKING:

        def _append_skill_result(
            self,
            ctx: TracingContext,
            *,
            skill_name: str,
            passed: bool,
            attempts: int,
            duration_seconds: float,
            blocking: bool,
            role: str = "finder",
            outcome: str | None = None,
        ) -> None: ...  # provided by _runner

        async def _count_commits(
            self, worktree_path: Path, branch: str
        ) -> int: ...  # provided by _commit

        async def _run_skill_check(
            self,
            skill: AgentSkill,
            issue: Task,
            worktree_path: Path,
            branch: str,
            max_attempts: int,
            plan_text: str,
            pinned_findings: Sequence[str] = (),
        ) -> SkillCheckOutcome: ...  # provided by _runner

        async def _run_skill_repair_loop(
            self,
            skill: AgentSkill,
            issue: Task,
            worktree_path: Path,
            branch: str,
            max_attempts: int,
            plan_text: str,
            check: SkillCheckOutcome,
        ) -> tuple[SkillCheckOutcome, list[str]]: ...  # provided by _runner

    async def _run_skill(
        self,
        skill: AgentSkill,
        issue: Task,
        worktree_path: Path,
        branch: str,
        worker_id: int,
        plan_text: str = "",
        pinned_findings: Sequence[str] = (),
    ) -> LoopResult:
        """Run a registered post-implementation skill via the skill registry.

        Gets max_attempts from config via ``skill.config_key``. When the
        check fails and the skill declares a repair seam (#11593 — only
        test-adequacy today), up to ``skill.repair_config_key`` bounded
        repair passes hand the concrete findings back to the implementer
        worktree and re-run the FULL check; the run is rejected only when
        the verdict still fails afterwards. Returns a :class:`LoopResult`.

        ``pinned_findings`` (#11644) is the demand the previous attempt
        stated. It applies only to a skill declaring ``pin_config_key``
        (test-adequacy today) and only while that config field is true.
        """
        max_attempts = getattr(self._config, skill.config_key, 0)
        if max_attempts <= 0:
            return LoopResult(passed=True, summary=f"{skill.name} disabled")

        commits = await self._count_commits(worktree_path, branch)
        if commits == 0:
            return LoopResult(passed=True, summary="No commits to check")

        skill_started = time.monotonic()
        check = await self._run_skill_check(
            skill,
            issue,
            worktree_path,
            branch,
            max_attempts,
            plan_text,
            pinned_findings=pinned_findings,
        )
        if check.short_circuit:
            return check.result

        check, repair_outcomes = await self._run_skill_repair_loop(
            skill, issue, worktree_path, branch, max_attempts, plan_text, check
        )
        result = check.result

        # Append the skill result to run-N/skill_results.json alongside
        # the parent run. This is the source of truth for skill-effectiveness
        # scoring in trace_rollup.
        ctx = self._tracing_ctx
        if ctx is not None:
            self._append_skill_result(
                ctx,
                skill_name=skill.name,
                passed=result.passed,
                attempts=result.attempts,
                duration_seconds=time.monotonic() - skill_started,
                blocking=skill.blocking,
            )

        # Rejection telemetry (#11593 seam 3): record every failing verdict
        # and every repair-pass outcome so the verifier can be calibrated
        # later. A clean first-pass OK carries no record.
        if skill.repair_config_key is not None and (
            not result.passed or repair_outcomes or check.demand.advisory
        ):
            result = replace(
                result,
                test_adequacy=TestAdequacyOutcome(
                    passed=result.passed,
                    verdict_source=check.verdict_source,
                    findings=check.findings[:10],
                    repair_passes_used=len(repair_outcomes),
                    repair_outcomes=repair_outcomes,
                    # #11644: what the retry was judged against, what it
                    # raised that the pin never mentioned, and what the pin
                    # absorbed. The moving bar stays measurable.
                    pinned_findings=list(check.pinned[:10]),
                    new_findings=list(check.demand.new[:10]),
                    advisory_findings=list(check.demand.advisory[:10]),
                ),
            )
        return result

    async def _run_skill_verifier(
        self,
        skill: AgentSkill,
        issue: Task,
        worktree_path: Path,
        prompt_diff: str,
        finder_result: LoopResult,
    ) -> tuple[LoopResult, list[str]]:
        """Run the independent second-opinion pass for a skill (#9546).

        Dispatches the verifier prompt with the verifier's own tool/model
        (independent of ``review_model`` — a shared model would defeat the
        second opinion) and never discloses the finder's verdict. CONCUR
        keeps the finder's pass; OVERRIDE flips it to a fail with the
        verifier's own gap list. Fail-soft by default: a degraded run (empty
        transcript) keeps the finder's OK unless the fail-closed knob is set.
        Returns the (possibly overridden) result plus the verifier's gap
        list — empty unless it overrode — for the repair prompt and the
        rejection telemetry (#11593).
        """
        spec = skill.verifier
        if spec is None:  # pragma: no cover — caller-gated
            return finder_result, []

        verifier_started = time.monotonic()
        verifier_cmd = build_agent_command(
            tool=getattr(self._config, spec.tool_config_key),
            model=getattr(self._config, spec.model_config_key),
            isolate_user_settings=True,
        )
        verifier_prompt = spec.prompt_builder(
            issue_number=issue.id, issue_title=issue.title, diff=prompt_diff
        )
        verifier_transcript = await self._execute(
            verifier_cmd,
            verifier_prompt,
            worktree_path,
            {"issue": issue.id, "source": "implementer"},
            issue_labels=issue.tags,
            telemetry_source=f"{skill.name}-verifier",
        )

        result = finder_result
        gaps: list[str] = []
        if not verifier_transcript.strip():
            # Subprocess soft-failure — nothing to judge. Fail-soft keeps the
            # finder's OK; the opt-in fail-closed knob flips it to a retry.
            outcome = "degraded"
            if getattr(self._config, spec.fail_closed_config_key, False):
                result = LoopResult(
                    passed=False,
                    summary=(
                        f"{skill.name} verifier produced no output "
                        "(fail-closed policy treats this as an override)"
                    ),
                    attempts=finder_result.attempts,
                )
        else:
            confirmed, v_summary, v_gaps = spec.result_parser(verifier_transcript)
            if confirmed:
                outcome = "concur"
            else:
                outcome = "override"
                logger.warning(
                    "%s verifier overrode OK for #%d: %s",
                    skill.name,
                    issue.id,
                    "; ".join(v_gaps[:5]) or v_summary,
                )
                result = LoopResult(
                    passed=False,
                    summary=(
                        f"Independent verifier overrode OK: {v_summary}"
                        if v_summary
                        else "Independent verifier found gaps"
                    ),
                    attempts=finder_result.attempts,
                )
                gaps = v_gaps

        ctx = self._tracing_ctx
        if ctx is not None:
            self._append_skill_result(
                ctx,
                skill_name=f"{skill.name}-verifier",
                passed=result.passed,
                attempts=1,
                duration_seconds=time.monotonic() - verifier_started,
                blocking=skill.blocking,
                role="verifier",
                outcome=outcome,
            )
        return result, gaps
