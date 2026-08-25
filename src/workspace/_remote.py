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
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from config import Credentials, HydraFlowConfig
from subprocess_util import run_subprocess

logger = logging.getLogger("hydraflow.workspace")


@lru_cache(maxsize=8)
def origin_url_pattern(host: str) -> re.Pattern[str]:
    r"""Compile the origin-URL matcher for *host*.

    One pattern covers every form ``git remote get-url origin`` emits:
    scp-style (``git@host:o/r.git``), HTTPS, ``ssh://``, and token-in-URL. The
    ``[/:]`` class matches scp's ``:`` as well as a path ``/``, and the call is
    ``.search``, so a separate SSH pattern is unreachable (#11703).

    ``(?:^|@|://)`` is the **host boundary**, and it is load-bearing. Without any
    boundary the unanchored search matches the host inside a longer one, so
    ``https://evilgithub.com/owner/repo`` parsed as ``owner/repo`` and was
    *accepted* by the guard whose entire job is to reject the wrong repository
    (#11720).

    The alternation is deliberately ``@|://`` and NOT ``[@/]`` or ``@|//``, and
    each widening was tried and rejected against a real bypass:

    - ``[@/]`` — a single ``/`` matches the host as a **path segment** of a
      foreign origin: ``https://evil.com/github.com/owner/repo`` and
      ``/srv/mirror/github.com/owner/repo`` both parsed as ``owner/repo``.
    - ``//`` — still matches a **doubled slash** anywhere in a path:
      ``https://evil.com//github.com/owner/repo`` parsed as ``owner/repo``.

    Requiring the full scheme separator ``://``, a userinfo ``@``, or
    start-of-string matches the host only where a host can actually appear, and
    admits every real origin form: scp ``git@host:o/r``, ``https://host/o/r``,
    ``ssh://git@host/o/r``, ``git://host/o/r``, token-in-URL ``…@host/o/r``, and
    bare ``host/o/r``.

    The repo segment is ``[^/]+?`` and NOT ``[^/.]+?``: GitHub allows dots in
    repo names (``socket.io``, ``next.js``), and excluding them made the pattern
    miss such origins entirely, failing the guard open (#11703). The non-greedy
    ``+?`` still lets the anchored ``(?:\.git)?$`` strip the suffix:
    ``vercel/next.js.git`` -> ``vercel/next.js``.

    *host* is interpolated with :func:`re.escape`, so a configured
    ``github.mycorp.com`` cannot inject pattern syntax and its dots stay literal.
    """
    return re.compile(rf"(?:^|@|://){re.escape(host)}[/:]([^/]+/[^/]+?)(?:\.git)?$")


class WorkspaceRemoteMixin:
    """Git primitives about origin: identity, fetch, branch existence."""

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

        def _repo_fetch_lock(self) -> asyncio.Lock: ...  # provided by _manager

    async def _assert_origin_matches_repo(self) -> None:
        """Raise ``RuntimeError`` if origin remote doesn't match the configured repo.

        **Fails closed** (#11720): an origin URL the pattern cannot parse cannot
        be verified, and "could not verify" is not a pass for the guard whose
        job is to stop HydraFlow mutating the wrong repository. The pattern is
        built for ``config.github_host`` (default ``github.com``), so a GitHub
        Enterprise Server deployment sets that rather than losing the guard.

        This runs on **every** workspace creation, from five loops, so a hard
        raise on a misconfigured origin stalls the factory rather than failing
        once. Two things contain that: the raised message names the origin, the
        expected repo, and the exact setting to change; and
        ``config.origin_guard_fail_closed=False`` restores the pre-#11720
        warn-and-continue behaviour for checkouts whose origin is a filesystem
        path or another non-``github_host`` remote.
        """
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
            host = self._config.github_host
            match = origin_url_pattern(host).search(url)
            if match:
                actual = match.group(1)
                if actual.lower() != expected.lower():
                    msg = f"Origin remote {url!r} resolves to {actual!r}, expected {expected!r}"
                    raise RuntimeError(msg)
            elif self._config.origin_guard_fail_closed:
                # The whole point of the guard: an origin it cannot parse is an
                # origin it cannot verify, so refuse rather than proceed
                # unverified (#11720). This fires per issue, so the message has
                # to be self-sufficient — someone reading a stalled factory's
                # logs must be able to fix it without opening this file.
                msg = (
                    f"Origin remote {url!r} is not a recognised {host!r} URL, so "
                    f"the repo-identity guard cannot verify this checkout is "
                    f"{expected!r}; refusing to operate on an unverified checkout. "
                    f"If this repo is hosted elsewhere (e.g. GitHub Enterprise "
                    f"Server), set HYDRAFLOW_GITHUB_HOST to that host. To restore "
                    f"the pre-#11720 warn-and-continue behaviour instead, set "
                    f"HYDRAFLOW_ORIGIN_GUARD_FAIL_CLOSED=false."
                )
                raise RuntimeError(msg)
            else:
                # Kill-switch path. Say plainly that the check did not run —
                # the pre-#11703 wording ('could not parse') read like a
                # cosmetic parse miss rather than a skipped safety check.
                logger.warning(
                    "Origin validation SKIPPED for %r: not a recognised %r URL and "
                    "origin_guard_fail_closed is off, so the repo-identity guard "
                    "did NOT run for this checkout",
                    url,
                    host,
                )
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
