"""Git primitives about origin: identity, fetch, branch existence.

The operations that talk to the remote, and the retry discipline around the
ones that intermittently fail.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import re
from pathlib import Path
from typing import TYPE_CHECKING

from config import Credentials, HydraFlowConfig
from subprocess_util import run_subprocess

logger = logging.getLogger("hydraflow.workspace")


class WorkspaceRemoteMixin:
    """Git primitives about origin: identity, fetch, branch existence."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``WorkspaceManager.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _ORIGIN_HTTPS_RE: re.Pattern[str]
    _ORIGIN_SSH_RE: re.Pattern[str]
    _config: HydraFlowConfig
    _credentials: Credentials
    _repo_root: Path

    if TYPE_CHECKING:

        def _repo_fetch_lock(self) -> asyncio.Lock: ...  # provided by _manager

    async def _assert_origin_matches_repo(self) -> None:
        """Raise ``RuntimeError`` if origin remote doesn't match the configured repo."""
        expected = self._config.repo
        if not expected:
            return
        try:
            output = await run_subprocess(
                "git",
                "remote",
                "get-url",
                "origin",
                cwd=self._repo_root,
                gh_token=self._credentials.gh_token,
            )
            url = output.strip()
            match = self._ORIGIN_HTTPS_RE.search(url) or self._ORIGIN_SSH_RE.search(url)
            if match:
                actual = match.group(1)
                if actual.lower() != expected.lower():
                    msg = f"Origin remote {url!r} resolves to {actual!r}, expected {expected!r}"
                    raise RuntimeError(msg)
            else:
                logger.warning("Could not parse origin URL %r for repo validation", url)
        except RuntimeError:
            raise
        except Exception:
            logger.warning("Could not validate origin remote", exc_info=True)

    def _is_main_ref_lock_error(self, message: str) -> bool:
        """Return True when *message* matches git remote-ref lock races."""
        main_ref = f"refs/remotes/origin/{self._config.base_branch()}"
        return (
            f"cannot lock ref '{main_ref}'" in message
            and "unable to update local ref" in message
        )

    async def _fetch_origin_with_retry(self, cwd: Path, *refs: str) -> None:
        """Run ``git fetch origin <refs...>`` with lock + targeted race retry."""
        attempts = 3
        async with self._repo_fetch_lock():
            for attempt in range(1, attempts + 1):
                try:
                    await run_subprocess(
                        "git",
                        "fetch",
                        "origin",
                        *refs,
                        cwd=cwd,
                        gh_token=self._credentials.gh_token,
                    )
                    return
                except RuntimeError as exc:
                    msg = str(exc)
                    if attempt < attempts and self._is_main_ref_lock_error(msg):
                        delay = 0.2 * (2 ** (attempt - 1)) + random.uniform(0, 0.15)  # noqa: S311
                        logger.warning(
                            "git fetch race on origin/%s (attempt %d/%d) — retrying in %.2fs",
                            self._config.base_branch(),
                            attempt,
                            attempts,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise

    async def _delete_local_branch(self, branch: str) -> None:
        """Delete a local branch if it exists, ignoring errors."""
        with contextlib.suppress(RuntimeError):
            await run_subprocess(
                "git",
                "branch",
                "-D",
                branch,
                cwd=self._repo_root,
                gh_token=self._credentials.gh_token,
            )

    async def _remote_branch_exists(self, branch: str) -> bool:
        """Check whether *branch* exists on the remote."""
        try:
            output = await run_subprocess(
                "git",
                "ls-remote",
                "--heads",
                "origin",
                branch,
                cwd=self._repo_root,
                gh_token=self._credentials.gh_token,
            )
            return bool(output.strip())
        except RuntimeError:
            return False

    async def _get_origin_url(self) -> str:
        """Return the real origin remote URL from the primary repo."""
        output = await run_subprocess(
            "git",
            "remote",
            "get-url",
            "origin",
            cwd=self._repo_root,
            gh_token=self._credentials.gh_token,
        )
        return output.strip()
