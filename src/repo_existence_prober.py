"""Bounded, fail-open repo-existence probe (extracted from HealthMonitorLoop).

Moved out of ``health_monitor_loop`` in #10140 so the raw ``git ls-remote``
subprocess spawn leaves the loop module entirely. The sandbox seam guard
(``tests/architecture/test_sandbox_seam_completeness.py``) only AST-scans
``src/*_loop.py`` + runner modules; with the spawn living here — a plain,
non-``*_loop.py``, non-runner module the guard never scans — the loop
declares no undeclared spawn, and the sandbox/MockWorld can inject a fake
``RepoProber`` so no real ``git`` call fires on the air-gapped network.

The probe's contract is unchanged from its former home: ``True`` (reachable),
``False`` (confirmed 404 via the not-found markers — safe to prune), or
``None`` (ambiguous: timeout, circuit-breaker-open, network/auth hiccup —
never treated as a 404, so a transient failure can never prune a healthy
entry). ``reraise_on_credit_or_bug`` is preserved so a credit-exhausted or
programming-bug signal is never swallowed as "ambiguous".
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from exception_classify import reraise_on_credit_or_bug
from subprocess_util import run_subprocess_result

logger = logging.getLogger("hydraflow.repo_existence_prober")

# Bounded probe timeout for the known-repair `git ls-remote` 404 check
# (PrinciplesAuditLoop's managed_repos entries) — short and fixed, mirrors
# `_STALE_CODE_FETCH_TIMEOUT_SECS`; a probe must degrade to "ambiguous"
# rather than hang the health-monitor cycle.
_REPO_PROBE_TIMEOUT_SECS = 30.0

# Conservative `git ls-remote` failure-output markers that indicate a
# confirmed 404 (repo deleted/renamed/private-without-access). Anything
# else (network blip, auth hiccup, rate limit) is ambiguous and must NOT
# be treated as a 404 — fail open, never prune a healthy repo entry on a
# signal that isn't a clear "this repo does not exist".
_REPO_NOT_FOUND_MARKERS = ("repository not found", "not found")


@runtime_checkable
class RepoProber(Protocol):
    """Bounded, fail-open existence probe for a GitHub repo slug.

    ``probe`` returns ``True`` (reachable), ``False`` (confirmed 404), or
    ``None`` (ambiguous — never treated as a 404). The sandbox and
    in-process MockWorld inject a fake so no real ``git`` spawn fires.
    """

    async def probe(self, slug: str) -> bool | None: ...


class DefaultRepoProber:
    """Production :class:`RepoProber` — a bounded ``git ls-remote`` HEAD probe.

    Takes the ``gh_token`` and ``repo_root`` the former in-loop probe read
    from ``HealthMonitorLoop._credentials`` / ``_config`` so the extracted
    call site keeps the exact same subprocess contract.
    """

    def __init__(self, gh_token: str, repo_root: Path) -> None:
        self._gh_token = gh_token
        self._repo_root = repo_root

    async def probe(self, slug: str) -> bool | None:
        """Bounded, fail-open existence probe for a managed-repo slug.

        Returns ``True`` (reachable), ``False`` (confirmed 404 — safe to
        prune), or ``None`` (ambiguous: timeout, circuit-breaker-open,
        network/auth hiccup — never treated as a 404, so a transient
        failure can never prune a healthy entry).
        """
        try:
            result = await run_subprocess_result(
                "git",
                "ls-remote",
                f"https://github.com/{slug}.git",
                "HEAD",
                cwd=self._repo_root,
                gh_token=self._gh_token,
                timeout=_REPO_PROBE_TIMEOUT_SECS,
            )
        except (OSError, RuntimeError) as exc:
            # run_subprocess_result only raises on spawn failure (OSError) or
            # timeout/credit (both RuntimeError subclasses — SubprocessTimeoutError,
            # CreditExhaustedError); command failures come back as a nonzero result.
            reraise_on_credit_or_bug(exc)
            logger.debug("repo probe failed for %s", slug, exc_info=True)
            return None
        if result.returncode == 0:
            return True
        haystack = f"{result.stdout}\n{result.stderr}".lower()
        if any(marker in haystack for marker in _REPO_NOT_FOUND_MARKERS):
            return False
        return None
