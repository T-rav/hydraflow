"""Git reads about the branch under review.

The snapshot questions: what is HEAD, what changed, is there anything to
review at all.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from base_runner import BaseRunner

if TYPE_CHECKING:
    pass


logger = logging.getLogger("hydraflow.reviewer")


class ReviewRepoMixin(BaseRunner):
    """Git reads about the branch under review."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewRunner.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------

    async def _get_head_sha(self, worktree_path: Path) -> str | None:
        """Return the current HEAD commit SHA in the worktree."""
        try:
            result = await self._runner.run_simple(
                ["git", "rev-parse", "HEAD"],
                cwd=str(worktree_path),
                timeout=self._config.git_command_timeout,
            )
        except (TimeoutError, FileNotFoundError):
            return None
        if result.returncode == 0:
            return result.stdout
        return None

    async def _get_commit_stat(
        self, worktree_path: Path, before_sha: str | None = None
    ) -> str:
        """Return ``git diff --stat`` covering all reviewer commits for audit trail.

        When *before_sha* is supplied the range ``<before_sha>..HEAD`` is used so
        that multi-commit sessions are fully captured.  Falls back to ``HEAD~1``
        when *before_sha* is unavailable (e.g. the repo had no commits before the
        agent ran).
        """
        ref = f"{before_sha}..HEAD" if before_sha else "HEAD~1"
        try:
            result = await self._runner.run_simple(
                ["git", "diff", "--stat", ref],
                cwd=str(worktree_path),
                timeout=self._config.git_command_timeout,
            )
        except (TimeoutError, FileNotFoundError):
            return ""
        if result.returncode == 0 and result.stdout:
            stat = result.stdout.strip()
            logger.info("Commit stat for %s:\n%s", worktree_path.name, stat)
            return stat
        return ""

    async def _get_changed_files(
        self, worktree_path: Path, before_sha: str | None
    ) -> list[str]:
        """Return list of files changed between *before_sha* and current HEAD.

        Returns an empty list when HEAD hasn't moved, *before_sha* is ``None``,
        or the git command fails.
        """
        if before_sha is None:
            return []
        try:
            current_sha = await self._get_head_sha(worktree_path)
            if not current_sha or current_sha == before_sha:
                return []
            result = await self._runner.run_simple(
                ["git", "diff", "--name-only", before_sha, current_sha],
                cwd=str(worktree_path),
                timeout=self._config.git_command_timeout,
            )
            if result.returncode != 0:
                return []
            return [f for f in result.stdout.splitlines() if f.strip()]
        except (TimeoutError, FileNotFoundError):
            return []

    async def _has_changes(self, worktree_path: Path, before_sha: str | None) -> bool:
        """Check if the agent made commits or left uncommitted changes."""
        try:
            # Check 1: new commits (HEAD moved)
            current_sha = await self._get_head_sha(worktree_path)
            if current_sha and before_sha and current_sha != before_sha:
                return True

            # Check 2: uncommitted changes (staged or unstaged)
            result = await self._runner.run_simple(
                ["git", "status", "--porcelain"],
                cwd=str(worktree_path),
                timeout=self._config.git_command_timeout,
            )
            return result.returncode == 0 and bool(result.stdout)
        except (TimeoutError, FileNotFoundError):
            return False
