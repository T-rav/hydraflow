"""Commit handling for ``AgentRunner``.

Extracted VERBATIM from ``src/agent.py`` (god-class decomposition,
Refs #11547) as a mixin.

One concern: making sure the worktree's work is actually committed — the
force-commit of anything the agent left uncommitted, the commit count the
zero-commit screen reads, and the public ``commit_pending`` entry point.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from base_runner import BaseRunner
from models import (
    Task,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


logger = logging.getLogger("hydraflow.agent")


class AgentCommitMixin(BaseRunner):
    """Commit handling for ``AgentRunner``.

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

    async def _force_commit_uncommitted(
        self,
        task: Task,
        worktree_path: Path,
        *,
        paths: Sequence[str] | None = None,
    ) -> bool:
        """Stage and commit any uncommitted changes the agent left behind.

        Always runs on the **host** (not inside Docker) since the workspace
        is bind-mounted — file edits from the container are already on disk.

        Returns ``True`` if a salvage commit was created, ``False`` otherwise.
        """
        from execution import get_default_runner

        host = get_default_runner()
        # ``git status`` / ``git add`` are cheap plumbing — they stay on the
        # short git tier. The salvage ``git commit`` runs the repo's pre-commit
        # hook (quality-lite / security / arch-check; we must NOT --no-verify),
        # which routinely exceeds the 30s git tier, so it gets a make-tier budget
        # of its own (#10598). Without this the hook timed out, TimeoutError was
        # raised, and the agent's real changes were discarded → zero commits.
        git_timeout = self._config.git_command_timeout
        commit_timeout = self._config.salvage_commit_timeout
        cwd = str(worktree_path)

        # Track the in-flight op + its budget so a TimeoutError can name a
        # concrete duration — ``str(TimeoutError())`` is empty, which is what
        # produced the blank "force-commit failed:" log the bug report cites.
        active_op = "git status"
        active_timeout: int = git_timeout
        pathspec = ["--", *paths] if paths else []

        try:
            status = await host.run_simple(
                ["git", "status", "--porcelain", *pathspec],
                cwd=cwd,
                timeout=git_timeout,
            )
            if not status.stdout.strip():
                return False

            logger.warning(
                "Issue #%d: agent left uncommitted changes — force-committing",
                task.id,
            )
            active_op, active_timeout = "git add", git_timeout
            add_result = await host.run_simple(
                ["git", "add", "-A", *pathspec],
                cwd=cwd,
                timeout=git_timeout,
            )
            if add_result.returncode != 0:
                logger.warning(
                    "Issue #%d: git add failed (rc=%d): %s",
                    task.id,
                    add_result.returncode,
                    add_result.stderr,
                )
                return False
            active_op, active_timeout = "git commit", commit_timeout
            commit_result = await host.run_simple(
                [
                    "git",
                    "commit",
                    "-m",
                    f"Fixes #{task.id}: {task.title}\n\n"
                    "Auto-committed by HydraFlow (agent did not commit)",
                    *pathspec,
                ],
                cwd=cwd,
                timeout=commit_timeout,
            )
            if commit_result.returncode != 0:
                logger.warning(
                    "Issue #%d: git commit failed (rc=%d): %s",
                    task.id,
                    commit_result.returncode,
                    commit_result.stderr,
                )
                return False
            logger.info(
                "Issue #%d: salvage commit created for uncommitted work",
                task.id,
            )
            return True
        except TimeoutError:
            logger.warning(
                "Issue #%d: force-commit failed: %s timed out after %ds",
                task.id,
                active_op,
                active_timeout,
            )
            return False
        except (FileNotFoundError, OSError) as exc:
            logger.warning(
                "Issue #%d: force-commit failed: %s",
                task.id,
                exc,
            )
            return False

    async def _count_commits(self, worktree_path: Path, branch: str) -> int:
        """Count delivery commits on *branch* ahead of the base branch.

        The factory creates ``.beads/issues.jsonl`` before the agent starts so
        phase IDs can be included in its prompt.  That runtime task state may
        be committed alongside implementation work, but a commit which changes
        only the task store is not implementation delivery and must not satisfy
        the zero-commit gate.
        """
        try:
            result = await self._runner.run_simple(
                [
                    "git",
                    "rev-list",
                    "--count",
                    f"origin/{self._config.base_branch()}..{branch}",
                    "--",
                    ".",
                    ":(exclude).beads/issues.jsonl",
                    ":(exclude).beads/.issues.jsonl.lock",
                ],
                cwd=str(worktree_path),
                timeout=self._config.git_command_timeout,
            )
            return int(result.stdout)
        except (TimeoutError, ValueError, FileNotFoundError):
            return 0

    async def commit_pending(self, task: Task, worktree_path: Path) -> bool:
        """Commit factory-owned state written after the agent's verified run.

        ImplementPhase uses this after finalizing its worktree-local JSONL task
        lifecycle. Reusing the normal salvage path preserves hook execution,
        host-runner timeouts, and git error handling without a second subprocess
        implementation in the phase layer.
        """

        await self._force_commit_uncommitted(
            task,
            worktree_path,
            paths=[".beads/issues.jsonl"],
        )

        from execution import get_default_runner

        try:
            host = get_default_runner()
            status = await host.run_simple(
                [
                    "git",
                    "status",
                    "--porcelain",
                    "--",
                    ".beads/issues.jsonl",
                ],
                cwd=str(worktree_path),
                timeout=self._config.git_command_timeout,
            )
            tracked = await host.run_simple(
                [
                    "git",
                    "ls-files",
                    "--error-unmatch",
                    "--",
                    ".beads/issues.jsonl",
                ],
                cwd=str(worktree_path),
                timeout=self._config.git_command_timeout,
            )
        except (TimeoutError, FileNotFoundError, OSError):
            return False
        return (
            status.returncode == 0
            and not status.stdout.strip()
            and tracked.returncode == 0
        )
