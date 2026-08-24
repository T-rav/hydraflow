"""Everything a fresh worktree needs before work can start.

Clustered by what breaks together: when a new worktree comes up wrong, the
cause is almost always one of these, and none of them is reached again for
the life of the worktree.
"""

from __future__ import annotations

import logging
import shutil
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from subprocess_util import run_subprocess

logger = logging.getLogger("hydraflow.workspace")


class WorkspaceProvisionMixin:
    """Everything a fresh worktree needs before work can start."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``WorkspaceManager.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _credentials: Credentials
    _repo_root: Path
    _ui_dirs: list[str]

    def _setup_env(self, wt_path: Path) -> None:
        """Set up .env, settings, and node_modules in the worktree."""
        docker = self._config.execution_mode == "docker"
        self._setup_dotenv(wt_path, docker)
        self._setup_claude_settings(wt_path)
        self._setup_node_modules(wt_path, docker)

    def _setup_dotenv(self, wt_path: Path, docker: bool) -> None:
        """Set up .env in the worktree.

        In host mode, .env is symlinked for performance.
        In docker mode, .env is copied and added to .gitignore to prevent
        accidental commits of secrets.
        """
        env_src = self._repo_root / ".env"
        env_dst = wt_path / ".env"
        if self._config.gateway_fleet_ratchet_enabled:
            # Terminal gateway workers must never receive the source repo's
            # provider credentials through their filesystem. Workspaces are
            # disposable clones, so remove a pre-existing copied/symlinked
            # dotenv as well as declining to create a new one.
            try:
                if env_dst.is_symlink() or env_dst.is_file():
                    env_dst.unlink()
            except OSError:
                logger.warning(
                    "Could not remove .env from terminal gateway workspace %s",
                    wt_path,
                    exc_info=True,
                )
                raise
            return
        if env_src.exists() and not env_dst.exists():
            try:
                if docker:
                    shutil.copy2(env_src, env_dst)
                else:
                    env_dst.symlink_to(env_src)
            except OSError:
                logger.debug(
                    "Could not %s %s → %s",
                    "copy" if docker else "symlink",
                    env_src,
                    env_dst,
                    exc_info=True,
                )

        if docker and env_dst.exists():
            gitignore_path = wt_path / ".gitignore"
            try:
                existing = gitignore_path.read_text() if gitignore_path.exists() else ""
                if ".env" not in [ln.strip() for ln in existing.splitlines()]:
                    with gitignore_path.open("a") as f:
                        if existing and not existing.endswith("\n"):
                            f.write("\n")
                        f.write(
                            "# Docker mode: .env is copied — exclude from commits\n"
                            ".env\n"
                        )
            except OSError:
                logger.debug(
                    "Could not update .gitignore at %s",
                    gitignore_path,
                    exc_info=True,
                )

    def _setup_claude_settings(self, wt_path: Path) -> None:
        """Copy .claude/settings.local.json into the worktree (not symlink — agents may modify)."""
        local_settings_src = self._repo_root / ".claude" / "settings.local.json"
        local_settings_dst = wt_path / ".claude" / "settings.local.json"
        if self._config.gateway_fleet_ratchet_enabled:
            try:
                if local_settings_dst.is_symlink() or local_settings_dst.is_file():
                    local_settings_dst.unlink()
            except OSError:
                logger.warning(
                    "Could not remove local Claude settings from terminal "
                    "gateway workspace %s",
                    wt_path,
                    exc_info=True,
                )
                raise
            return
        if local_settings_src.exists() and not local_settings_dst.exists():
            try:
                local_settings_dst.parent.mkdir(parents=True, exist_ok=True)
                local_settings_dst.write_text(local_settings_src.read_text())
            except OSError:
                logger.debug(
                    "Could not copy settings to %s",
                    local_settings_dst,
                    exc_info=True,
                )

    def _setup_node_modules(self, wt_path: Path, docker: bool) -> None:
        """Set up node_modules for each UI directory in the worktree.

        In host mode, node_modules is symlinked for performance.
        In docker mode, node_modules is copied so the worktree is self-contained.
        """
        for ui_dir in self._ui_dirs:
            nm_src = self._repo_root / ui_dir / "node_modules"
            nm_dst = wt_path / ui_dir / "node_modules"
            if nm_src.exists() and not nm_dst.exists():
                try:
                    nm_dst.parent.mkdir(parents=True, exist_ok=True)
                    if docker:
                        shutil.copytree(nm_src, nm_dst, symlinks=True)
                    else:
                        nm_dst.symlink_to(nm_src)
                except OSError:
                    logger.debug(
                        "Could not %s %s → %s",
                        "copy" if docker else "symlink",
                        nm_src,
                        nm_dst,
                        exc_info=True,
                    )

    async def _configure_git_identity(self, wt_path: Path) -> None:
        """Set git user.name and user.email in the worktree (local scope)."""
        try:
            if self._config.git_user_name:
                await run_subprocess(
                    "git",
                    "config",
                    "user.name",
                    self._config.git_user_name,
                    cwd=wt_path,
                    gh_token=self._credentials.gh_token,
                )
            if self._config.git_user_email:
                await run_subprocess(
                    "git",
                    "config",
                    "user.email",
                    self._config.git_user_email,
                    cwd=wt_path,
                    gh_token=self._credentials.gh_token,
                )
        except RuntimeError as exc:
            logger.warning("git identity config failed in %s: %s", wt_path, exc)

    async def _create_venv(self, wt_path: Path) -> None:
        """Create an independent venv in the worktree via ``uv sync --all-extras``.

        ``--all-extras`` ensures test and dev extras (pytest, hypothesis, ulid, etc.)
        are installed, matching the ``make deps`` behaviour in the main repo. Without
        it, fresh worktree venvs miss test-only deps and route/scenario tests fail to
        import.
        """
        try:
            await run_subprocess(
                "uv",
                "sync",
                "--all-extras",
                cwd=wt_path,
                gh_token=self._credentials.gh_token,
            )
            logger.info("uv sync --all-extras complete in %s", wt_path)
        except (RuntimeError, FileNotFoundError) as exc:
            logger.warning("uv sync failed in %s: %s", wt_path, exc)

    async def _install_hooks(self, wt_path: Path) -> None:
        """Install git hooks in the worktree.

        In host mode, sets ``core.hooksPath`` to the shared ``.githooks`` dir.
        In docker mode, copies individual hook files into the worktree's git
        hooks directory so the worktree is self-contained.

        Either way, registers the ``arch-meta`` merge driver so the worktree
        gets the same conflict-free ``docs/arch/.meta.json`` handling that
        ``make ensure-hooks`` gives a developer checkout.
        """
        if self._config.execution_mode == "docker":
            await self._install_hooks_docker(wt_path)
        else:
            try:
                await run_subprocess(
                    "git",
                    "config",
                    "core.hooksPath",
                    ".githooks",
                    cwd=wt_path,
                    gh_token=self._credentials.gh_token,
                )
            except RuntimeError as exc:
                logger.warning("git hooks setup failed: %s", exc)
        await self._register_arch_meta_merge_driver(wt_path)

    async def _install_hooks_docker(self, wt_path: Path) -> None:
        """Copy hook files from .githooks/ into the worktree's git hooks dir."""
        githooks_src = self._repo_root / ".githooks"
        if not githooks_src.is_dir():
            logger.debug("No .githooks directory found at %s — skipping", githooks_src)
            return

        # Resolve the actual git hooks directory (worktree .git is a file)
        try:
            hooks_dir_str = await run_subprocess(
                "git",
                "rev-parse",
                "--git-path",
                "hooks",
                cwd=wt_path,
                gh_token=self._credentials.gh_token,
            )
            hooks_dir = Path(hooks_dir_str.strip())
            if not hooks_dir.is_absolute():
                hooks_dir = wt_path / hooks_dir
        except RuntimeError as exc:
            logger.warning("Could not resolve git hooks path: %s", exc)
            return

        try:
            hooks_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "Could not create git hooks directory %s: %s", hooks_dir, exc
            )
            return

        for hook_file in githooks_src.iterdir():
            if hook_file.is_file():
                dst = hooks_dir / hook_file.name
                try:
                    shutil.copy2(hook_file, dst)
                    dst.chmod(
                        dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                    )
                except OSError:
                    logger.debug(
                        "Could not copy hook %s → %s", hook_file, dst, exc_info=True
                    )

    def _install_commands(self, wt_path: Path) -> None:
        """Copy ``hf.*.md`` command files into the worktree if missing.

        Only runs in Docker mode — on the host the commands already exist
        in the HydraFlow repo and worktrees share them via the git checkout.
        In Docker containers the target repo may not have HydraFlow's
        commands, so we copy them from the HydraFlow source.
        """
        if self._config.execution_mode != "docker":
            return

        src_commands = self._repo_root / ".claude" / "commands"
        if not src_commands.is_dir():
            return

        dst_commands = wt_path / ".claude" / "commands"
        dst_commands.mkdir(parents=True, exist_ok=True)

        installed = 0
        for src_file in sorted(src_commands.glob("hf.*.md")):
            dst_file = dst_commands / src_file.name
            if dst_file.exists():
                continue
            try:
                shutil.copy2(src_file, dst_file)
                installed += 1
            except OSError:
                logger.debug(
                    "Could not copy command %s → %s",
                    src_file,
                    dst_file,
                    exc_info=True,
                )

        if installed:
            logger.info("Installed %d hf.* commands into %s", installed, dst_commands)

    async def _register_arch_meta_merge_driver(self, wt_path: Path) -> None:
        """Register the ``arch-meta`` git merge driver in the worktree.

        ``.gitattributes`` maps ``docs/arch/.meta.json`` to ``merge=arch-meta``
        so a staging advance auto-resolves the regenerated stamp instead of
        conflicting on it (#10099). That mapping is INERT unless the driver is
        registered in git config — and ``make ensure-hooks`` (which registers
        it for a developer checkout) never runs during factory worktree setup.
        Without this, every agent worktree still hits the ``.meta.json``
        conflict on each rebase onto staging, forcing the arch-heal loop to
        regen it. Values mirror ``make ensure-hooks`` exactly; the sibling
        ``changelog.md merge=union`` needs no driver (``union`` is built in).

        Best-effort: on failure the branch simply falls back to the old
        conflict-then-heal path, so we warn and continue rather than fail
        worktree setup.
        """
        for key, value in (
            (
                "merge.arch-meta.name",
                "keep incoming arch .meta.json (regenerated on mainline)",
            ),
            ("merge.arch-meta.driver", "cp -- %B %A"),
        ):
            try:
                await run_subprocess(
                    "git",
                    "config",
                    key,
                    value,
                    cwd=wt_path,
                    gh_token=self._credentials.gh_token,
                )
            except RuntimeError as exc:
                logger.warning("arch-meta merge driver setup failed (%s): %s", key, exc)
                return

    def _detect_ui_dirs(self) -> list[str]:
        """Auto-detect UI directories by scanning for ``package.json`` files.

        Falls back to ``config.ui_dirs`` if no ``package.json`` files are found.
        """
        detected: list[str] = []
        try:
            for pkg_json in self._repo_root.rglob("package.json"):
                # Skip node_modules and hidden directories
                parts = pkg_json.relative_to(self._repo_root).parts
                if "node_modules" in parts or any(p.startswith(".") for p in parts):
                    continue
                parent = str(pkg_json.parent.relative_to(self._repo_root))
                if parent == ".":
                    continue  # Skip root-level package.json
                detected.append(parent)
        except OSError:
            logger.debug("Could not scan for package.json files", exc_info=True)
        if detected:
            logger.info("Auto-detected UI dirs: %s", detected)
            return sorted(detected)
        return list(self._config.ui_dirs)


if TYPE_CHECKING:
    from pathlib import Path

    from credentials import Credentials
