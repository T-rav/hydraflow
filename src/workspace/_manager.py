"""Git workspace lifecycle management for HydraFlow.

Creates isolated workspaces for each issue using ``git clone --local``.
Local clones use hardlinks for git objects (fast, no extra disk) and give
each workspace its own independent ``.git/`` directory — no shared state
with the primary repo.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
from pathlib import Path

from config import Credentials, HydraFlowConfig
from subprocess_util import run_subprocess

from ._heal import WorkspaceHealMixin
from ._mainline import WorkspaceMainlineMixin
from ._provision import WorkspaceProvisionMixin
from ._remote import WorkspaceRemoteMixin

logger = logging.getLogger("hydraflow.workspace")

_FETCH_LOCKS: dict[str, asyncio.Lock] = {}
_WORKTREE_LOCKS: dict[str, asyncio.Lock] = {}


class WorkspaceManager(
    WorkspaceHealMixin,
    WorkspaceMainlineMixin,
    WorkspaceProvisionMixin,
    WorkspaceRemoteMixin,
):
    """Creates, configures, and destroys isolated workspaces via local clones.

    Each workspace gets:
    - A local clone with its own ``.git/`` directory
    - A fresh branch from ``main`` (or resumed from remote)
    - An independent venv via ``uv sync``
    - ``.env`` and ``node_modules/`` dirs (symlinked in host mode, copied in docker mode)
    - Copied ``.claude/settings.local.json``
    - Pre-commit hooks installed (symlinked path in host mode, copied files in docker mode)
    """

    def __init__(
        self, config: HydraFlowConfig, credentials: Credentials | None = None
    ) -> None:
        self._config = config
        self._credentials = credentials or Credentials()
        self._repo_root = config.repo_root
        self._base = config.workspace_base
        self._ui_dirs = self._detect_ui_dirs()

    def _repo_fetch_lock(self) -> asyncio.Lock:
        """Return a shared lock for git fetch operations in this repo."""
        key = str(self._repo_root.resolve())
        return _FETCH_LOCKS.setdefault(key, asyncio.Lock())

    def _repo_workspace_lock(self) -> asyncio.Lock:
        """Return a per-repo lock for workspace create/destroy operations."""
        key = f"wt:{self._config.repo_slug}"
        return _WORKTREE_LOCKS.setdefault(key, asyncio.Lock())

    # One pattern covers every origin form git emits: scp-style
    # (``git@github.com:o/r.git``), HTTPS, ``ssh://``, and token-in-URL. The
    # ``[/:]`` class matches scp's ``:`` as well as a path ``/``, and this is
    # ``.search``, so any prefix before ``github.com`` is irrelevant — a
    # separate SSH pattern was provably unreachable (#11703).
    #
    # The repo segment is ``[^/]+?`` and NOT ``[^/.]+?``: GitHub allows dots in
    # repo names (``socket.io``, ``next.js``), and excluding them made this
    # pattern miss such origins entirely, which fails the guard OPEN. The
    # non-greedy ``+?`` still lets the anchored ``(?:\.git)?$`` strip the
    # suffix: ``vercel/next.js.git`` -> ``vercel/next.js`` (#11703).
    _ORIGIN_URL_RE = re.compile(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$")

    # ------------------------------------------------------------------
    # Git hygiene — startup, pre-work, and post-work cleanup
    # ------------------------------------------------------------------

    async def sanitize_repo(self) -> None:
        """Fetch latest refs and clean up stale agent branches.

        The primary checkout's branch and working tree belong to the
        developer.  HydraFlow operates exclusively in worktrees and
        never force-switches the primary checkout.
        """
        repo = self._repo_root
        main = self._config.base_branch()
        gh = self._credentials.gh_token

        # Fix J (#9723): heal main-checkout core.worktree corruption BEFORE
        # any other git command — a corrupt entry makes the fetch below fail
        # with "fatal: Invalid path '/workspace'".
        await self._heal_repo_root_config()

        # Fetch latest main for worktree creation
        await self._fetch_origin_with_retry(repo, main)

        # Delete orphan agent/* branches (HydraFlow's own branches)
        try:
            branches_output = await run_subprocess(
                "git",
                "branch",
                "--list",
                "agent/*",
                cwd=repo,
                gh_token=gh,
            )
            for line in branches_output.strip().splitlines():
                branch_name = line.strip().lstrip("* ")
                if branch_name:
                    with contextlib.suppress(RuntimeError):
                        await run_subprocess(
                            "git",
                            "branch",
                            "-D",
                            branch_name,
                            cwd=repo,
                            gh_token=gh,
                        )
                        logger.info("Pruned orphan branch %s", branch_name)
        except RuntimeError:
            logger.debug("Could not list agent branches for cleanup", exc_info=True)

        logger.info("Repo sanitized — fetched %s, orphan branches pruned", main)

    async def pre_work_check(self) -> None:
        """Quick validation before creating a workspace.

        Fetches latest main so branches are created from up-to-date state.
        """
        await self._fetch_origin_with_retry(self._repo_root, self._config.base_branch())

    async def post_work_cleanup(
        self, issue_number: int, *, phase: str = "implement"
    ) -> None:
        """Clean up after an issue is done (PR created/merged/failed).

        Salvages any uncommitted changes, then removes the workspace.
        Trace collection is now in-process (see src/trace_collector.py)
        and writes directly to <data_root>/traces/<issue>/<phase>/run-N/
        during the agent run, so no harvest step is needed here.
        """
        del phase  # retained in signature for API stability; no longer used
        # Salvage any uncommitted work before destroying
        with contextlib.suppress(Exception):
            await self._salvage_uncommitted(issue_number)

        # Destroy workspace
        with contextlib.suppress(RuntimeError):
            await self.destroy(issue_number)

        logger.info("Post-work cleanup complete for issue #%d", issue_number)

    async def create(self, issue_number: int, branch: str) -> Path:
        """Create a workspace for *issue_number* on *branch*.

        Uses ``git clone --local`` to create an independent clone with
        hardlinked objects (fast, no extra disk).  If the branch already
        exists on the remote (previous run), checks it out so work can
        resume.  Otherwise creates a fresh branch from main.

        Returns the absolute path to the new workspace.
        """
        async with self._repo_workspace_lock():
            return await self._create_unlocked(issue_number, branch)

    async def _create_unlocked(self, issue_number: int, branch: str) -> Path:
        """Inner create logic — must be called under ``_repo_workspace_lock``."""
        wt_path = self._config.workspace_path_for_issue(issue_number)
        logger.info(
            "Creating workspace %s on branch %s",
            wt_path,
            branch,
            extra={"issue": issue_number},
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would create workspace at %s", wt_path)
            return wt_path

        # Pre-work hygiene: fetch latest main
        await self.pre_work_check()

        # Validate origin remote matches configured repo before any mutations
        await self._assert_origin_matches_repo()

        # Ensure repo-scoped base directory exists
        wt_path.parent.mkdir(parents=True, exist_ok=True)

        # Clean up any stale directory from a previous run
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)

        try:
            # Get the real origin URL before cloning (clone will point to local path)
            origin_url = await self._get_origin_url()

            # Clone the repo locally — hardlinks objects, fast, own .git/
            await run_subprocess(
                "git",
                "clone",
                "--local",
                "--no-checkout",
                str(self._repo_root),
                str(wt_path),
                cwd=self._repo_root,
                gh_token=self._credentials.gh_token,
            )

            # Point origin at the real remote (GitHub), not the local repo
            await run_subprocess(
                "git",
                "remote",
                "set-url",
                "origin",
                origin_url,
                cwd=wt_path,
                gh_token=self._credentials.gh_token,
            )

            # Fetch latest state from real remote
            await self._fetch_origin_with_retry(wt_path, self._config.base_branch())

            # Check if the branch already exists on the remote (resumable work)
            if await self._remote_branch_exists(branch):
                logger.info(
                    "Remote branch %s exists — resuming from remote",
                    branch,
                    extra={"issue": issue_number},
                )
                await run_subprocess(
                    "git",
                    "fetch",
                    "origin",
                    f"+refs/heads/{branch}:refs/heads/{branch}",
                    cwd=wt_path,
                    gh_token=self._credentials.gh_token,
                )
                await run_subprocess(
                    "git",
                    "checkout",
                    branch,
                    cwd=wt_path,
                    gh_token=self._credentials.gh_token,
                )
            else:
                # Create a fresh branch from main
                await run_subprocess(
                    "git",
                    "checkout",
                    "-b",
                    branch,
                    f"origin/{self._config.base_branch()}",
                    cwd=wt_path,
                    gh_token=self._credentials.gh_token,
                )

            # Set up the environment inside the workspace
            self._setup_env(wt_path)
            await self._configure_git_identity(wt_path)
            await self._create_venv(wt_path)
            await self._install_hooks(wt_path)
            self._install_commands(wt_path)
        except BaseException:
            logger.warning(
                "Workspace creation failed for issue %d; cleaning up",
                issue_number,
            )
            if wt_path.exists():
                shutil.rmtree(wt_path, ignore_errors=True)
            raise

        logger.info(
            "Workspace ready at %s",
            wt_path,
            extra={"issue": issue_number},
        )
        return wt_path

    async def destroy(self, issue_number: int) -> None:
        """Remove the workspace for *issue_number*."""
        async with self._repo_workspace_lock():
            await self._destroy_unlocked(issue_number)

    async def _destroy_unlocked(self, issue_number: int) -> None:
        """Inner destroy logic — must be called under ``_repo_workspace_lock``."""
        wt_path = self._config.workspace_path_for_issue(issue_number)
        if self._config.dry_run:
            logger.info("[dry-run] Would destroy workspace %s", wt_path)
            return

        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)
            logger.info(
                "Destroyed workspace %s",
                wt_path,
                extra={"issue": issue_number},
            )

    async def destroy_all(self) -> None:
        """Remove every workspace under this repo's scoped base directory."""
        if not self._base.exists():
            return
        repo_base = self._base / self._config.repo_slug
        # Also scan the flat (legacy) layout for backward compatibility
        for scan_dir in (repo_base, self._base):
            if not scan_dir.exists():
                continue
            for child in scan_dir.iterdir():
                if child.is_dir() and child.name.startswith("issue-"):
                    try:
                        num = int(child.name.split("-", 1)[1])
                        await self.destroy(num)
                    except (ValueError, RuntimeError) as exc:
                        logger.warning("Could not destroy %s: %s", child, exc)
