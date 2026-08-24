"""Integration with the mainline: merge, reset, and the questions asked about a divergence."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from subprocess_util import run_subprocess

logger = logging.getLogger("hydraflow.workspace")


class WorkspaceMainlineMixin:
    """Integration with the mainline: merge, reset, and the questions asked about a divergence."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``WorkspaceManager.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _credentials: Credentials
    _repo_root: Path

    if TYPE_CHECKING:

        async def _fetch_origin_with_retry(
            self, cwd: Path, *refs: str
        ) -> None: ...  # provided by _remote

    async def _fetch_and_merge_main(self, worktree_path: Path, branch: str) -> bool:
        """Fetch and merge the configured base branch into *branch*.

        Performs the shared three-step sequence: fetch origin, fast-forward
        local branch to match remote, then merge ``origin/<base>`` — where
        ``<base>`` is ``config.base_branch()`` (``staging`` when staging is
        enabled, else ``main``). Raises ``RuntimeError`` on any failure so
        callers can decide how to handle it.

        Returns *True* on success.
        """
        await self._fetch_origin_with_retry(
            worktree_path, self._config.base_branch(), branch
        )
        await run_subprocess(
            "git",
            "merge",
            "--ff-only",
            f"origin/{branch}",
            cwd=worktree_path,
            gh_token=self._credentials.gh_token,
        )
        await run_subprocess(
            "git",
            "merge",
            f"origin/{self._config.base_branch()}",
            "--no-edit",
            cwd=worktree_path,
            gh_token=self._credentials.gh_token,
        )
        return True

    async def reset_to_main(self, worktree_path: Path) -> None:
        """Hard-reset worktree to ``origin/<base>`` and clean untracked files.

        ``<base>`` is ``config.base_branch()`` — ``staging`` when staging is
        enabled, else ``main``. The method name is historical.

        Used between implementation retry attempts to discard stale state
        from a prior failed attempt, ensuring a clean slate.
        """
        await self._fetch_origin_with_retry(worktree_path, self._config.base_branch())
        await run_subprocess(
            "git",
            "reset",
            "--hard",
            f"origin/{self._config.base_branch()}",
            cwd=worktree_path,
            gh_token=self._credentials.gh_token,
        )
        await run_subprocess(
            "git",
            "clean",
            "-fd",
            cwd=worktree_path,
            gh_token=self._credentials.gh_token,
        )
        logger.info(
            "Reset worktree %s to origin/%s", worktree_path, self._config.base_branch()
        )

    async def merge_main(self, worktree_path: Path, branch: str) -> bool:
        """Merge latest main into *branch* inside *worktree_path*.

        First pulls the branch itself so the local copy is in sync with
        the remote, then merges ``origin/main``.  Because this uses merge
        the subsequent push is always fast-forward.

        Returns *True* on success, *False* if conflicts arise.
        """
        try:
            return await self._fetch_and_merge_main(worktree_path, branch)
        except RuntimeError:
            with contextlib.suppress(RuntimeError):
                await run_subprocess(
                    "git",
                    "merge",
                    "--abort",
                    cwd=worktree_path,
                    gh_token=self._credentials.gh_token,
                )
            return False

    async def start_merge_main(self, worktree_path: Path, branch: str) -> bool:
        """Begin merging main into *branch*, leaving conflicts for manual resolution.

        Like :meth:`merge_main` but does **not** abort on conflict.
        The caller is expected to resolve the conflict markers and
        complete the merge with ``git add . && git commit --no-edit``.

        Returns *True* if the merge completed cleanly (no conflicts),
        *False* if conflicts remain in the working tree.
        """
        try:
            return await self._fetch_and_merge_main(worktree_path, branch)
        except RuntimeError:
            return False

    async def abort_merge(self, worktree_path: Path) -> None:
        """Abort an in-progress merge in *worktree_path*."""
        with contextlib.suppress(RuntimeError):
            await run_subprocess(
                "git",
                "merge",
                "--abort",
                cwd=worktree_path,
                gh_token=self._credentials.gh_token,
            )

    async def get_conflicting_files(self, worktree_path: Path) -> list[str]:
        """Return the list of files with unresolved merge conflicts.

        Runs ``git diff --name-only --diff-filter=U`` in *worktree_path*.
        Returns an empty list on failure.
        """
        try:
            output = await run_subprocess(
                "git",
                "diff",
                "--name-only",
                "--diff-filter=U",
                cwd=worktree_path,
                gh_token=self._credentials.gh_token,
            )
            return [f.strip() for f in output.strip().splitlines() if f.strip()]
        except RuntimeError:
            logger.warning("Could not get conflicting files in %s", worktree_path)
            return []

    async def get_main_diff_for_files(
        self,
        worktree_path: Path,
        files: list[str],
        max_chars: int = 30_000,
    ) -> str:
        """Return the diff of what changed on the base branch for *files*.

        Runs ``git merge-base HEAD origin/<base>`` then
        ``git diff <mbase>..origin/<base> -- <files>``, where ``<base>`` is
        ``config.base_branch()``. Truncates at *max_chars*. Returns an empty
        string on failure or when *files* is empty.
        """
        if not files:
            return ""
        try:
            merge_base = await run_subprocess(
                "git",
                "merge-base",
                "HEAD",
                f"origin/{self._config.base_branch()}",
                cwd=worktree_path,
                gh_token=self._credentials.gh_token,
            )
            base_sha = merge_base.strip()
            if not base_sha:
                return ""

            diff_output = await run_subprocess(
                "git",
                "diff",
                f"{base_sha}..origin/{self._config.base_branch()}",
                "--",
                *files,
                cwd=worktree_path,
                gh_token=self._credentials.gh_token,
            )
            result = diff_output.strip()
            if len(result) > max_chars:
                return result[:max_chars] + "\n\n[Diff truncated]"
            return result
        except RuntimeError:
            logger.warning("Could not get main diff for files in %s", worktree_path)
            return ""

    async def get_main_commits_since_diverge(self, worktree_path: Path) -> str:
        """Return recent commits on the base branch since the branch diverged.

        Runs ``git log --oneline HEAD..origin/<base>`` in *worktree_path*
        (after fetching) and returns up to 30 commit summaries as a
        newline-separated string, where ``<base>`` is ``config.base_branch()``.
        Returns an empty string on failure.
        """
        try:
            await self._fetch_origin_with_retry(
                worktree_path, self._config.base_branch()
            )
            output = await run_subprocess(
                "git",
                "log",
                "--oneline",
                f"HEAD..origin/{self._config.base_branch()}",
                "-30",
                cwd=worktree_path,
                gh_token=self._credentials.gh_token,
            )
            return output.strip()
        except RuntimeError:
            logger.warning(
                "Could not get main commits since diverge in %s",
                worktree_path,
            )
            return ""

    async def enable_rerere(self) -> None:
        """Enable git rerere so resolved conflicts are remembered for next time."""
        try:
            await run_subprocess(
                "git",
                "config",
                "rerere.enabled",
                "true",
                cwd=self._repo_root,
                gh_token=self._credentials.gh_token,
            )
            logger.info("git rerere enabled")
        except (RuntimeError, FileNotFoundError):
            logger.debug("Could not enable git rerere", exc_info=True)


if TYPE_CHECKING:
    from pathlib import Path

    from credentials import Credentials
