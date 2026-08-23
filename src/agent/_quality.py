"""The post-build quality gate of ``AgentRunner``.

Extracted VERBATIM from ``src/agent.py`` (god-class decomposition,
Refs #11547) as a mixin.

One concern: verifying what the build produced and repairing it in place — the
result check, the lock-free ``quality-lite`` + impacted-test run, and the
bounded fix loop that re-spawns the agent against the failure output.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from base_runner import BaseRunner
from implement_quality_gate import run_implement_quality_gate
from models import (
    LoopResult,
    Task,
    WorkerStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


logger = logging.getLogger("hydraflow.agent")


class AgentQualityMixin(BaseRunner):
    """The post-build quality gate of ``AgentRunner``.

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

        async def _count_commits(
            self, worktree_path: Path, branch: str
        ) -> int: ...  # provided by _commit

        async def _emit_status(
            self, issue_number: int, worker_id: int, status: WorkerStatus
        ) -> None: ...  # provided by _runner

        async def _force_commit_uncommitted(
            self, task: Task, worktree_path: Path, *, paths: Sequence[str] | None = None
        ) -> bool: ...  # provided by _commit

    async def _verify_result(self, worktree_path: Path, branch: str) -> LoopResult:
        """Check that the agent produced commits and the quality gate passes.

        Returns a :class:`LoopResult`.  On failure the summary contains
        the last ``error_output_max_chars`` characters of combined
        stdout/stderr of the step that failed.
        """
        # Check for commits on the branch
        commit_count = await self._count_commits(worktree_path, branch)
        if commit_count == 0:
            return LoopResult(passed=False, summary="No commits found on branch")

        # Run the implement-path quality gate (lock-free; see _verify_quality)
        return await self._verify_quality(worktree_path)

    async def _verify_quality(self, worktree_path: Path) -> LoopResult:
        """Implement-path gate (#11568): lock-free quality-lite + impacted tests.

        ``BaseRunner._verify_quality`` (HITL / diagnostic runners) runs the
        full ``make quality`` under the host-wide lock; the implementer must
        not — see ``implement_quality_gate`` for the rationale. The
        ``implement_full_quality_gate`` kill-switch restores the locked run.
        """
        if self._config.implement_full_quality_gate:
            return await super()._verify_quality(worktree_path)
        return await run_implement_quality_gate(
            self._runner, self._config, worktree_path
        )

    def _build_quality_fix_prompt(
        self,
        issue: Task,
        error_output: str,
        attempt: int,
    ) -> str:
        """Build a focused prompt for fixing quality gate failures."""
        return f"""You are fixing quality gate failures for issue #{issue.id}: {issue.title}

## Quality Gate Failure Output

```
{error_output[-self._config.error_output_max_chars :]}
```

## Fix Attempt {attempt}

1. Read the failing output above carefully.
2. Fix ALL lint, type-check, security, and test issues.
3. Do NOT skip or disable tests, type checks, or lint rules.
4. Run `make quality-lite` to verify your fixes pass lint, typecheck, and security.
5. Commit your fixes with message: "quality-fix: <description> (#{issue.id})"

Focus on fixing the root causes, not suppressing warnings.
"""

    async def _run_quality_fix_loop(
        self,
        issue: Task,
        worktree_path: Path,
        branch: str,
        error_output: str,
        worker_id: int,
    ) -> LoopResult:
        """Retry loop: invoke Claude to fix quality failures.

        Returns a :class:`LoopResult` with ``attempts`` set to the number
        of fix iterations performed.
        """
        max_attempts = self._config.max_quality_fix_attempts
        last_error = error_output

        for attempt in range(1, max_attempts + 1):
            logger.info(
                "Quality fix attempt %d/%d for issue #%d",
                attempt,
                max_attempts,
                issue.id,
            )
            await self._emit_status(issue.id, worker_id, WorkerStatus.QUALITY_FIX)

            prompt = self._build_quality_fix_prompt(issue, last_error, attempt)
            cmd = self._build_command(worktree_path)
            await self._execute(
                cmd,
                prompt,
                worktree_path,
                {"issue": issue.id, "source": "implementer"},
                issue_labels=issue.tags,
            )
            await self._force_commit_uncommitted(issue, worktree_path)

            verify = await self._verify_result(worktree_path, branch)
            if verify.passed:
                return LoopResult(passed=True, summary="OK", attempts=attempt)

            last_error = verify.summary

        return LoopResult(passed=False, summary=last_error, attempts=max_attempts)
