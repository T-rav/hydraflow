"""Implementation agent runner — launches Claude Code to solve issues."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import skill_gate
from base_runner import BaseRunner
from events import EventBus, EventType, HydraFlowEvent
from exception_classify import exc_detail, reraise_on_credit_or_bug
from models import (
    LoopResult,
    Task,
    WorkerResult,
    WorkerStatus,
    WorkerUpdatePayload,
)
from review_insights import (
    ReviewInsightStore,
)
from skill_gate import SkillCheckOutcome
from skill_registry import AgentSkill, get_skills

from ._claude_md import AgentClaudeMdGuardMixin
from ._commit import AgentCommitMixin
from ._context import AgentPromptContextMixin
from ._plan import AgentPlanMixin
from ._prequality import AgentPreQualityReviewMixin
from ._prompts import AgentPromptMixin
from ._quality import AgentQualityMixin
from ._skills import AgentSkillMixin

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from config import Credentials, HydraFlowConfig
    from execution import SubprocessRunner
    from models import TranscriptEventData
    from repo_wiki import RepoWikiStore
    from tracing_context import TracingContext
    from tribal_wiki import TribalWikiStore


logger = logging.getLogger("hydraflow.agent")


class AgentRunner(
    AgentClaudeMdGuardMixin,
    AgentCommitMixin,
    AgentPlanMixin,
    AgentPreQualityReviewMixin,
    AgentPromptContextMixin,
    AgentPromptMixin,
    AgentQualityMixin,
    AgentSkillMixin,
    BaseRunner,
):
    """Launches a ``claude -p`` process to implement a GitHub issue.

    The agent works inside an isolated git worktree and commits its
    changes but does **not** push or create PRs.
    """

    _log = logger
    _phase_name: ClassVar[str] = "implement"
    PROVIDER_FIELD: ClassVar[str | None] = "implementation_provider"

    _SELF_CHECK_CHECKLIST = """
## Self-Check Before Committing

These six patterns pass locally but go red in CI. Check each trigger and apply the one-line fix BEFORE your final commit:

- [ ] **`fix(` commit → `tests/regressions/` delta (P10.6)** — if your commit subject starts with `fix(`, add a test under `tests/regressions/`. For a pure refactor with no behavior change, add a `Skip-Regression:` trailer to the commit. No delta and no trailer → P10.6 WARNs → CI red.
- [ ] **New subprocess call site → sandbox seam** — if you add a NEW `run_subprocess*` / `stream_claude_process` call site in a `src/*_loop.py` or a runner, declare it in `mockworld.sandbox_main.SANDBOX_SEAMS` (or route it through an injected-fake seam). Otherwise the seam-completeness ratchet goes red.
- [ ] **ADR `Enforced by:` with multiple checks → bullet lines** — multiple checks MUST be bullet lines (`**Enforced by:**` then `- pytest:a` / `- pytest:b` on their own lines), never inline `pytest:a, pytest:b`. A single inline check is fine; the resolver only parses bullets for multiples.
- [ ] **Extracting code → do NOT relocate a `# noqa`** — moving code to a new file moves its suppression to a new file-signature, which the disturbance ratchet reads as a NEW violation (it only ever shrinks). Instead narrow the `except` to concrete types, or hoist the import to module top, so no suppression is needed. Never bump the baseline.
- [ ] **Moving a cited file → update its ADR `Enforced by:` citation** — if you relocate a file named in an ADR `Enforced by:` citation (grep the ADRs for the old path), update that citation in the same commit, or ADR-conformance goes red.
- [ ] **Relocating a symbol → fix its patchers** — before moving a module-level symbol out of its module, grep tests/scenarios for `patch("oldmodule.symbol")` and repoint them, or the patched test errors at collection.
- [ ] **Date in a test fixture → make it now-relative** — a hardcoded date (or a frozen `_NOW = datetime(...)` anchor) that must sit on one side of a `now()`-relative threshold silently detonates when real time crosses it (two RC-blocking cases in 48h: #11045, #11053). Use `datetime.now(UTC) - timedelta(...)`. A frozen anchor is safe ONLY when the code under test takes `now=` as an explicit parameter. Sweep: `make time-travel`.
"""

    @staticmethod
    def _build_self_check_checklist(
        escalations: list[dict[str, str | int | list[str]]],
    ) -> str:
        """Build the self-check checklist, dynamically extending with escalation items."""
        base = AgentRunner._SELF_CHECK_CHECKLIST
        if not escalations:
            return base

        extra_items: list[str] = []
        for esc in escalations:
            items = esc.get("checklist_items", [])
            if isinstance(items, list):
                extra_items.extend(str(item) for item in items)

        if not extra_items:
            return base

        escalated = "\n### Escalated Checks (from recurring review feedback)\n"
        escalated += "\n".join(extra_items) + "\n"
        return base.rstrip() + "\n" + escalated

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
        *,
        credentials: Credentials | None = None,
        wiki_store: RepoWikiStore | None = None,
        tribal_wiki_store: TribalWikiStore | None = None,
    ) -> None:
        super().__init__(
            config,
            event_bus,
            runner,
            credentials=credentials,
            wiki_store=wiki_store,
            tribal_wiki_store=tribal_wiki_store,
        )
        self._insights = ReviewInsightStore(config.repo_memory_dir)
        from context_cache import ContextSectionCache

        self._context_cache = ContextSectionCache(config)

    async def run(
        self,
        task: Task,
        worktree_path: Path,
        branch: str,
        worker_id: int = 0,
        review_feedback: str = "",
        prior_failure: str = "",
        bead_mapping: dict[str, str] | None = None,
        human_guidance: str = "",
        attempt_number: int = 0,
        known_traps: str = "",
        timeout_s: int | None = None,
        pinned_adequacy_findings: Sequence[str] | None = None,
    ) -> WorkerResult:
        """Run the implementation agent for *task*.

        ``known_traps`` (#9858) is a pre-rendered "Known CI Traps" section
        from harness-insights — recurring repo failure classes injected so
        the agent stops re-hitting documented walls (ratchet, arch-regen,
        …). Empty string leaves the prompt unchanged.

        ``attempt_number`` is the 1-based issue attempt this run represents
        (0 = unknown); on cycling retries it feeds the diverse-retry
        directive in the prior-failure prompt section.

        ``timeout_s`` (#11568) is the complexity-tiered wall-clock budget
        for the main build spawn, resolved by the implement phase from
        triage's complexity score. ``None`` means ``agent_timeout`` — which
        stays the ceiling either way (``BaseRunner._execute`` clamps).

        ``pinned_adequacy_findings`` (#11644) is the test-adequacy demand the
        previous attempt stated. On a retry the gate is judged against it, so
        satisfying the stated bar is not defeated by a freshly-sampled one.

        Returns a :class:`WorkerResult` with success/failure info.
        """
        start = time.monotonic()
        result = WorkerResult(
            issue_number=task.id,
            branch=branch,
            workspace_path=str(worktree_path),
        )

        await self._emit_status(task.id, worker_id, WorkerStatus.RUNNING)

        if self._config.dry_run:
            logger.info("[dry-run] Would run agent for issue #%d", task.id)
            result.success = True
            result.duration_seconds = time.monotonic() - start
            await self._emit_status(task.id, worker_id, WorkerStatus.DONE)
            return result

        try:
            # Snapshot CLAUDE.md before agent runs for integrity check
            claude_md_snapshot = self._snapshot_claude_md(worktree_path)

            # Build and run the configured agent command
            cmd = self._build_command(worktree_path)
            prompt, prompt_stats = await self._build_prompt_with_stats(
                task,
                review_feedback=review_feedback,
                prior_failure=prior_failure,
                bead_mapping=bead_mapping,
                human_guidance=human_guidance,
                attempt_number=attempt_number,
            )
            if known_traps:
                prompt += "\n\n" + known_traps
            transcript = await self._execute(
                cmd,
                prompt,
                worktree_path,
                {"issue": task.id, "source": "implementer"},
                telemetry_stats=prompt_stats,
                issue_labels=task.tags,
                timeout_s=timeout_s,
            )
            result.transcript = transcript

            # Guard: restore CLAUDE.md if the agent removed content
            self._guard_claude_md(worktree_path, claude_md_snapshot, task.id)

            # Force-commit any uncommitted work the agent left behind
            await self._force_commit_uncommitted(task, worktree_path)

            # Load plan text for skills that need it (e.g. plan-compliance)
            skill_plan_text, _ = self._extract_plan_comment(task.comments)
            if not skill_plan_text:
                skill_plan_text = self._load_plan_fallback(task.id)

            # Run registered post-implementation skills (diff-sanity, test-adequacy, etc.)
            for skill in get_skills():
                skill_result = await self._run_skill(
                    skill,
                    task,
                    worktree_path,
                    branch,
                    worker_id,
                    plan_text=skill_plan_text,
                    pinned_findings=pinned_adequacy_findings or (),
                )
                if skill_result.test_adequacy is not None:
                    # Rejection/repair telemetry (#11593 seam 3) — rides the
                    # WorkerResult into the run manifest and failure counters.
                    result.test_adequacy = skill_result.test_adequacy
                if not skill_result.passed and skill.blocking:
                    logger.warning(
                        "%s flagged issues for #%d: %s",
                        skill.name,
                        task.id,
                        skill_result.summary,
                    )
                    result.success = False
                    result.error = f"{skill.name} failed: {skill_result.summary}"
                    result.commits = await self._count_commits(worktree_path, branch)
                    await self._emit_status(task.id, worker_id, WorkerStatus.FAILED)
                    result.duration_seconds = time.monotonic() - start
                    return result
                if not skill_result.passed:
                    logger.warning(
                        "%s flagged gaps for #%d: %s (non-blocking)",
                        skill.name,
                        task.id,
                        skill_result.summary,
                    )

            # Mandatory pre-quality self-review/correction loop
            pre_quality = await self._run_pre_quality_review_loop(
                task, worktree_path, branch, worker_id
            )
            result.pre_quality_review_attempts = pre_quality.attempts
            if not pre_quality.passed:
                result.success = False
                result.error = pre_quality.summary
                result.commits = await self._count_commits(worktree_path, branch)
                await self._emit_status(task.id, worker_id, WorkerStatus.FAILED)
                result.duration_seconds = time.monotonic() - start
                return result

            # Verify the agent produced valid work
            await self._emit_status(task.id, worker_id, WorkerStatus.TESTING)
            verify = await self._verify_result(worktree_path, branch)

            # If quality failed but commits exist, try the fix loop
            success = verify.passed
            last_msg = verify.summary
            if (
                not success
                and last_msg != "No commits found on branch"
                and self._config.max_quality_fix_attempts > 0
            ):
                fix = await self._run_quality_fix_loop(
                    task, worktree_path, branch, last_msg, worker_id
                )
                success = fix.passed
                last_msg = fix.summary
                result.quality_fix_attempts = fix.attempts

            result.success = success
            if not success:
                result.error = last_msg

            # Count commits
            result.commits = await self._count_commits(worktree_path, branch)

            status = WorkerStatus.DONE if success else WorkerStatus.FAILED
            await self._emit_status(task.id, worker_id, status)

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            result.success = False
            result.error = repr(exc)
            logger.exception(
                "Agent failed for issue #%d: %s",
                task.id,
                exc_detail(exc),
                extra={"issue": task.id},
            )
            await self._emit_status(task.id, worker_id, WorkerStatus.FAILED)

        result.duration_seconds = time.monotonic() - start

        # Persist transcript to disk
        try:
            self._save_transcript("issue", result.issue_number, result.transcript)
        except OSError:
            logger.warning(
                "Failed to save transcript for issue #%d",
                result.issue_number,
                exc_info=True,
                extra={"issue": result.issue_number},
            )

        return result

    @staticmethod
    def _extract_plan_comment(comments: list[str]) -> tuple[str, list[str]]:
        """Separate the planner's implementation plan from other comments.

        Returns ``(plan_text, remaining_comments)``.  *plan_text* is the
        cleaned body of the first comment that contains
        ``## Implementation Plan``, or an empty string if none is found.
        """
        plan = ""
        remaining: list[str] = []
        for c in comments:
            if not plan and "## Implementation Plan" in c:
                plan = AgentRunner._strip_plan_noise(c)
            else:
                remaining.append(c)
        return plan, remaining

    # ------------------------------------------------------------------
    # CLAUDE.md integrity guard
    # ------------------------------------------------------------------

    async def _run_skill_check(
        self,
        skill: AgentSkill,
        issue: Task,
        worktree_path: Path,
        branch: str,
        max_attempts: int,
        plan_text: str,
        pinned_findings: Sequence[str] = (),
    ) -> SkillCheckOutcome:
        """Delegate to :func:`skill_gate.run_skill_check` (patch seam)."""
        return await skill_gate.run_skill_check(
            self,
            skill,
            issue,
            worktree_path,
            branch,
            max_attempts,
            plan_text,
            pinned_findings=pinned_findings,
        )

    async def _run_skill_repair_loop(
        self,
        skill: AgentSkill,
        issue: Task,
        worktree_path: Path,
        branch: str,
        max_attempts: int,
        plan_text: str,
        check: SkillCheckOutcome,
    ) -> tuple[SkillCheckOutcome, list[str]]:
        """Delegate to :func:`skill_gate.run_skill_repair_loop` (patch seam)."""
        return await skill_gate.run_skill_repair_loop(
            self, skill, issue, worktree_path, branch, max_attempts, plan_text, check
        )

    def _skill_repair_budget(self, skill: AgentSkill) -> int:
        """Delegate to :func:`skill_gate.skill_repair_budget` (patch seam)."""
        return skill_gate.skill_repair_budget(self, skill)

    async def _run_skill_repair_pass(
        self,
        skill: AgentSkill,
        issue: Task,
        worktree_path: Path,
        check: SkillCheckOutcome,
        pass_number: int,
        max_passes: int,
    ) -> bool:
        """Delegate to :func:`skill_gate.run_skill_repair_pass` (patch seam)."""
        return await skill_gate.run_skill_repair_pass(
            self, skill, issue, worktree_path, check, pass_number, max_passes
        )

    async def _git_head(self, worktree_path: Path) -> str:
        """Delegate to :func:`skill_gate.git_head` (patch seam)."""
        return await skill_gate.git_head(self, worktree_path)

    async def _run_coverage_delta_check(
        self,
        worktree_path: Path,
        diff: str,
        issue_id: int,
    ) -> list[str]:
        """Delegate to :func:`skill_gate.run_coverage_delta_check` (patch seam)."""
        return await skill_gate.run_coverage_delta_check(
            self, worktree_path, diff, issue_id
        )

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
    ) -> None:
        """Delegate to :func:`skill_gate.append_skill_result` (patch seam)."""
        skill_gate.append_skill_result(
            self,
            ctx,
            skill_name=skill_name,
            passed=passed,
            attempts=attempts,
            duration_seconds=duration_seconds,
            blocking=blocking,
            role=role,
            outcome=outcome,
        )

    # AgentPort public interface (hexagonal contract).
    # The underscore implementations remain for internal BaseRunner use; these
    # thin forwarders expose the port boundary names used by infrastructure
    # modules (merge_conflict_resolver, pr_unsticker).

    def build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Public AgentPort entry point — delegates to ``_build_command``."""
        return self._build_command(_worktree_path)

    async def execute(
        self,
        cmd: list[str],
        prompt: str,
        cwd: Path,
        event_data: TranscriptEventData,
        *,
        on_output: Callable[[str], bool] | None = None,
        telemetry_stats: Mapping[str, object] | None = None,
        issue_labels: Sequence[str] | None = None,
    ) -> str:
        """Public AgentPort entry point — delegates to ``_execute``.

        Infrastructure callers with issue/PR label context MUST pass
        *issue_labels* so the CH-6 gate's data-class label elevation applies.
        """
        return await self._execute(
            cmd,
            prompt,
            cwd,
            event_data,
            on_output=on_output,
            telemetry_stats=telemetry_stats,
            issue_labels=issue_labels,
        )

    async def verify_result(self, worktree_path: Path, branch: str) -> LoopResult:
        """Public AgentPort entry point — delegates to ``_verify_result``."""
        return await self._verify_result(worktree_path, branch)

    async def _emit_status(
        self, issue_number: int, worker_id: int, status: WorkerStatus
    ) -> None:
        """Publish a worker status event."""
        payload: WorkerUpdatePayload = {
            "issue": issue_number,
            "worker": worker_id,
            "status": status.value,
            "role": "implementer",
        }
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                data=payload,
            )
        )
