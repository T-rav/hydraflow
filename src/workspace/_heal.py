"""Repair paths for a worktree that is already wrong.

Separate from provisioning on purpose: provisioning runs once on a clean
tree, healing runs against a tree someone else left broken, and the two fail
for different reasons.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from config import Credentials, HydraFlowConfig
from subprocess_util import run_subprocess

logger = logging.getLogger("hydraflow.workspace")


class WorkspaceHealMixin:
    """Repair paths for a worktree that is already wrong."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``WorkspaceManager.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _credentials: Credentials
    _repo_root: Path

    async def _heal_worktree_config(self, wt_path: Path, gh_token: str) -> None:
        """Clear a stale ``core.worktree`` from a worktree's git config (WS-8).

        A docker container that runs git inside the worktree can write
        ``core.worktree=/workspace`` into ``<wt>/.git/config``. On the host that
        path doesn't exist, and git then refuses to run *any* command in the
        worktree — failing with "fatal: Invalid path '/workspace'". Workspaces
        here are full local clones (see ``_create_unlocked``), so the config is
        always ``<wt>/.git/config``. Delegates to the guarded
        :meth:`_heal_stale_core_worktree` predicate.
        """
        await self._heal_stale_core_worktree(
            wt_path / ".git" / "config", wt_path, gh_token
        )

    async def _heal_repo_root_config(self) -> bool:
        """Heal a stale ``core.worktree`` in the MAIN checkout's config (#9723).

        The docker factory can corrupt the primary checkout the same way it
        corrupts worktrees (WS-8): a container writes
        ``core.worktree=/workspace`` into ``<repo>/.git/config`` and every
        host-side git command then fails with "fatal: Invalid path
        '/workspace'" — the manual HITL reset runbook step this automates.
        Runs first in :meth:`sanitize_repo` (orchestrator startup, shutdown,
        and deferred pipeline start). No-op when ``<repo>/.git/config`` is
        missing — e.g. the primary checkout is itself a linked worktree whose
        config lives elsewhere.

        Returns ``True`` when a stale entry was unset.
        """
        return await self._heal_stale_core_worktree(
            self._repo_root / ".git" / "config",
            self._repo_root,
            self._credentials.gh_token,
        )

    async def _heal_stale_core_worktree(
        self, config_path: Path, root: Path, gh_token: str
    ) -> bool:
        """Unset ``core.worktree`` in *config_path* when it points outside *root*.

        Fail-safe predicate (#9723): only a value that resolves OUTSIDE
        *root* — the container-corruption signature, e.g. ``/workspace`` on a
        host where that path is not this checkout — is ever unset. A value
        that resolves to *root* (or inside it) is a legitimately-configured
        worktree checkout and is never touched; git resolves relative values
        against the ``.git`` directory, so ``..`` is legitimate too. When the
        value cannot be read, nothing is unset.

        All git calls use ``--file`` and run from OUTSIDE the checkout
        (``cwd=root.parent``): from inside, git auto-discovers the repo and
        re-validates the bogus ``core.worktree`` before it ever processes
        ``--file``, re-triggering the same fatal error.

        Returns ``True`` when a stale entry was unset.
        """
        if not config_path.is_file():
            return False
        try:
            value = (
                await run_subprocess(
                    "git",
                    "config",
                    "--file",
                    str(config_path),
                    "--get",
                    "core.worktree",
                    cwd=root.parent,
                    gh_token=gh_token,
                )
            ).strip()
        except RuntimeError:
            # Exit 1 = key absent — nothing to heal. Any other read failure:
            # fail safe by leaving the config untouched.
            return False
        if not value:
            return False
        raw = Path(value)
        # git resolves a relative core.worktree against the .git directory.
        resolved = (raw if raw.is_absolute() else config_path.parent / raw).resolve()
        root_resolved = root.resolve()
        if resolved == root_resolved or resolved.is_relative_to(root_resolved):
            logger.debug(
                "core.worktree=%s in %s resolves inside %s — legitimate, keeping",
                value,
                config_path,
                root,
            )
            return False
        with contextlib.suppress(RuntimeError):
            await run_subprocess(
                "git",
                "config",
                "--file",
                str(config_path),
                "--unset",
                "core.worktree",
                cwd=root.parent,
                gh_token=gh_token,
            )
            logger.warning(
                "Healed stale core.worktree=%s in %s (points outside %s)",
                value,
                config_path,
                root,
            )
            return True
        return False

    async def _salvage_uncommitted(self, issue_number: int) -> None:
        """Commit and push any uncommitted changes in the worktree before destroying it.

        Prevents work loss when a worktree is cleaned up after a crash or
        timeout that left uncommitted changes behind.
        """
        wt_path = self._config.workspace_path_for_issue(issue_number)
        if not wt_path.exists():
            return

        gh = self._credentials.gh_token
        branch = self._config.branch_for_issue(issue_number)

        # A container may have written a stale core.worktree into the worktree's
        # git config during the run; heal it before the status check below, or
        # that check fails with "not a work tree" and we silently skip the
        # salvage — losing the uncommitted work this method exists to protect.
        await self._heal_worktree_config(wt_path, gh)

        # Check for uncommitted changes
        try:
            status = await run_subprocess(
                "git",
                "status",
                "--porcelain",
                cwd=wt_path,
                gh_token=gh,
            )
        except RuntimeError:
            return

        if not status.strip():
            return

        logger.info(
            "Salvaging uncommitted changes in worktree for issue #%d",
            issue_number,
        )

        try:
            await run_subprocess(
                "git",
                "add",
                "-A",
                cwd=wt_path,
                gh_token=gh,
            )
            await run_subprocess(
                "git",
                "commit",
                "-m",
                f"chore: salvage uncommitted changes for issue #{issue_number}",
                "--no-verify",
                cwd=wt_path,
                gh_token=gh,
            )
            await run_subprocess(
                "git",
                "push",
                "--no-verify",
                "-u",
                "origin",
                branch,
                cwd=wt_path,
                gh_token=gh,
            )
            logger.info(
                "Salvaged and pushed uncommitted work for issue #%d", issue_number
            )
        except RuntimeError as exc:
            logger.warning(
                "Could not salvage uncommitted changes for issue #%d: %s",
                issue_number,
                exc,
            )
