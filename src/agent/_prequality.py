"""The pre-quality self-review loop of ``AgentRunner``.

Extracted VERBATIM from ``src/agent.py`` (god-class decomposition,
Refs #11547) as a mixin.

One concern: the review pass that runs BEFORE the quality gate — its prompt,
its run-tool variant, the command it spawns, the branch diff it reviews, and the
verdict parsing that decides whether to iterate.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner
from models import (
    LoopResult,
    Task,
    WorkerStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


logger = logging.getLogger("hydraflow.agent")


class AgentPreQualityReviewMixin(BaseRunner):
    """The pre-quality self-review loop of ``AgentRunner``.

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

        @staticmethod
        def _build_spec_match_check(issue: Task) -> str: ...  # provided by _prompts

        async def _count_commits(
            self, worktree_path: Path, branch: str
        ) -> int: ...  # provided by _commit

        async def _emit_status(
            self, issue_number: int, worker_id: int, status: WorkerStatus
        ) -> None: ...  # provided by _runner

        async def _force_commit_uncommitted(
            self, task: Task, worktree_path: Path, *, paths: Sequence[str] | None = None
        ) -> bool: ...  # provided by _commit

        def _get_escalation_data(
            self,
        ) -> list[dict[str, str | int | list[str]]]: ...  # provided by _context

    def _build_pre_quality_review_prompt(self, issue: Task, attempt: int) -> str:
        """Build the pre-quality review/correction skill prompt."""
        escalations = self._get_escalation_data()
        escalation_guidance = ""
        if escalations:
            guidance_parts = [str(e["pre_quality_guidance"]) for e in escalations]
            escalation_guidance = (
                "\n\nEscalated Requirements (from recurring review feedback):\n"
                + "\n".join(f"- {g}" for g in guidance_parts)
            )

        return f"""You are running the Pre-Quality Review Skill for issue #{issue.id}: {issue.title}.

Attempt: {attempt}

Review the current branch changes thoroughly for bugs, gaps, and test coverage.

Bug check:
- look for logic errors, off-by-one mistakes, wrong comparisons, swapped arguments
- check None/null handling: are optional values dereferenced without guards?
- verify error paths: do exceptions propagate correctly? are resources cleaned up?
- check concurrency issues: race conditions, missing awaits, unprotected shared state

Gap check:
- compare implementation against the plan/issue description — is anything missing?
- check edge cases: empty inputs, None values, missing keys, boundary conditions
- verify all new functions have type hints and all imports are correct
- ensure no debug code, print statements, or hardcoded test values remain
{self._build_spec_match_check(issue)}

Test coverage check:
- every new public function/method must have at least one test
- verify tests cover both success and failure/error paths
- check that edge cases (empty, None, boundary) have dedicated tests
- ensure tests actually assert on behavior, not just that code runs without error
- add missing tests directly in this working tree

Apply fixes:
- fix any bugs, gaps, or missing tests found above directly in this working tree
- keep edits scoped to issue intent{escalation_guidance}

Constraints:
- Do not push or open PRs
- Prefer minimal safe changes
- Keep edits scoped to issue intent — do not refactor, migrate, or rename code that is unrelated to the fix

Required output:
PRE_QUALITY_REVIEW_RESULT: OK
or
PRE_QUALITY_REVIEW_RESULT: RETRY
SUMMARY: <one-line summary>
"""

    def _build_pre_quality_run_tool_prompt(self, issue: Task, attempt: int) -> str:
        """Build the run-tool skill prompt for quality/test commands."""
        test_cmd = self._config.test_command
        return f"""You are running the Run-Tool Skill for issue #{issue.id}: {issue.title}.

Attempt: {attempt}

Run these commands in order and fix failures:
1. `make lint`
2. `{test_cmd}`
3. `make quality-lite`

Rules:
- If a command fails, fix root causes and rerun from command 1
- Do not skip tests or reduce quality gates
- Keep changes scoped to this issue

Required output:
RUN_TOOL_RESULT: OK
or
RUN_TOOL_RESULT: RETRY
SUMMARY: <one-line summary>
"""

    def _build_pre_quality_review_command(self) -> list[str]:
        """Build the command used for pre-quality review skill."""
        return build_agent_command(
            tool=self._config.review_tool,
            model=self._config.review_model,
        )

    @staticmethod
    def _parse_skill_result(transcript: str, marker: str) -> LoopResult:
        """Parse a skill result marker line from transcript text.

        Returns a :class:`LoopResult`. Missing marker defaults to OK to preserve
        backward compatibility with older prompts/tools.
        """
        pattern = rf"{re.escape(marker)}:\s*(OK|RETRY)"
        match = re.search(pattern, transcript, re.IGNORECASE)
        if not match:
            return LoopResult(passed=True, summary="No explicit result marker")
        status = match.group(1).upper()
        summary_match = re.search(r"SUMMARY:\s*(.+)", transcript, re.IGNORECASE)
        summary = summary_match.group(1).strip() if summary_match else ""
        return LoopResult(passed=status == "OK", summary=summary)

    async def _run_pre_quality_review_loop(
        self,
        issue: Task,
        worktree_path: Path,
        branch: str,
        worker_id: int,
    ) -> LoopResult:
        """Run mandatory pre-quality review + run-tool skills before verification."""
        commits = await self._count_commits(worktree_path, branch)
        max_attempts = self._config.max_pre_quality_review_attempts
        if commits == 0 or max_attempts <= 0:
            return LoopResult(
                passed=True, summary="Skipped pre-quality review", attempts=0
            )

        for attempt in range(1, max_attempts + 1):
            await self._emit_status(
                issue.id, worker_id, WorkerStatus.PRE_QUALITY_REVIEW
            )

            review_prompt = self._build_pre_quality_review_prompt(issue, attempt)
            review_cmd = self._build_pre_quality_review_command()
            review_transcript = await self._execute(
                review_cmd,
                review_prompt,
                worktree_path,
                {"issue": issue.id, "source": "implementer"},
                issue_labels=issue.tags,
            )
            await self._force_commit_uncommitted(issue, worktree_path)
            review_result = self._parse_skill_result(
                review_transcript, "PRE_QUALITY_REVIEW_RESULT"
            )

            run_tool_prompt = self._build_pre_quality_run_tool_prompt(issue, attempt)
            run_tool_cmd = self._build_command(worktree_path)
            run_tool_transcript = await self._execute(
                run_tool_cmd,
                run_tool_prompt,
                worktree_path,
                {"issue": issue.id, "source": "implementer"},
                issue_labels=issue.tags,
            )
            await self._force_commit_uncommitted(issue, worktree_path)
            run_tool_result = self._parse_skill_result(
                run_tool_transcript, "RUN_TOOL_RESULT"
            )

            if review_result.passed and run_tool_result.passed:
                return LoopResult(passed=True, summary="OK", attempts=attempt)

            last_summary = "; ".join(
                s for s in [review_result.summary, run_tool_result.summary] if s
            ).strip()
            if attempt == max_attempts:
                return LoopResult(
                    passed=False,
                    summary="Pre-quality review loop exhausted"
                    + (f": {last_summary}" if last_summary else ""),
                    attempts=attempt,
                )

        return LoopResult(
            passed=False,
            summary="Pre-quality review loop failed",
            attempts=max_attempts,
        )

    async def _get_branch_diff(self, worktree_path: Path, branch: str) -> str:
        """Return the combined diff of *branch* against the base branch."""
        try:
            result = await self._runner.run_simple(
                [
                    "git",
                    "diff",
                    f"origin/{self._config.base_branch()}...{branch}",
                ],
                cwd=str(worktree_path),
                timeout=self._config.git_command_timeout,
            )
            return result.stdout or ""
        except (TimeoutError, FileNotFoundError):
            return ""
