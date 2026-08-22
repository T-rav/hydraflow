"""Branch-scoped git/GitHub reads for :class:`pr_manager.PRManager`.

Extracted VERBATIM from ``pr_manager.py`` (god-class decomposition, Refs
#11547) as a mixin — the same shape as ``pr_manager_promotion.py`` from
#10840. ``PRManager`` inherits :class:`PRManagerBranchesMixin`, so every
method here is still reached exactly as before
(``PRManager().list_branch_refs``), ``from pr_manager import PRManager`` is
unchanged, and ``patch("pr_manager.PRManager.<method>")`` still lands.

The cluster is "questions about a branch": does it differ from the base, what
refs/commits does it carry, what SHA does the remote hold, and which PR (if
any) that branch opened. The two branch→PR lookups live here rather than with
the PR queries because the branch name — not a PR number — is the key.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from models import PRInfo
from pr_manager_common import _GIT_OID_RE, _parse_branch_pr_row

if TYPE_CHECKING:
    from config import HydraFlowConfig

# Same channel as pr_manager — this slice is still PRManager behavior;
# one logger name keeps existing log filtering working.
logger = logging.getLogger("hydraflow.pr_manager")


class PRManagerBranchesMixin:
    """Branch-scoped queries mixed into :class:`pr_manager.PRManager`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PRManager or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in PRManager's MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _repo: str
    _repo_owner: str

    if TYPE_CHECKING:

        def _assert_repo(self) -> None: ...  # provided by PRManager

        async def _run_gh(
            self, *cmd: str, cwd: Path | None = None
        ) -> str: ...  # provided by PRManager

    async def find_open_pr_for_branch(
        self, branch: str, *, issue_number: int = 0
    ) -> PRInfo | None:
        """Return the open PR for *branch*, or ``None`` when absent/unreadable.

        #8786 Phase 12: routed through the contracts boundary helper in
        lenient mode against ``GhPRDetail`` (only ``number`` is required;
        ``url``/``isDraft`` are optional, matching the narrow ``--jq``
        projection used here).
        """
        if self._config.dry_run:
            return None
        from contracts.boundary import parse_list_with_shape  # noqa: PLC0415
        from contracts.shapes import GhPRDetail  # noqa: PLC0415

        head_filter = f"{self._repo_owner}:{branch}" if self._repo_owner else branch
        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/pulls",
                "--method",
                "GET",
                "--field",
                "state=open",
                "--field",
                f"head={head_filter}",
                "--field",
                "per_page=1",
                "--jq",
                "[.[] | {number, url: .html_url, isDraft: .draft}]",
            )
            from contracts.boundary import field_or  # noqa: PLC0415

            results = parse_list_with_shape(raw, GhPRDetail)
            if not results:
                return None
            r = results[0]
            # ``number`` may be a string from a drifted payload; coerce
            # via int() so the existing except clause catches bad shapes
            # cleanly with the same semantics as before.
            return PRInfo(
                number=int(field_or(r, "number", 0)),
                issue_number=issue_number,
                branch=branch,
                url=str(field_or(r, "url", "")),
                draft=bool(field_or(r, "is_draft", False, dict_key="isDraft")),
            )
        except (RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            logger.debug(
                "Could not resolve open PR for branch %s", branch, exc_info=True
            )
            return None

    async def get_branch_pr_state(
        self, branch: str, head_sha: str, base_branch: str
    ) -> str:
        """Return PR state for the exact branch HEAD (fail-closed, #11502).

        GitHub is authoritative for squash-merge history, but a branch name
        alone is not an identity: deleted branch names can be reused after an
        older PR merged, and the same HEAD can target another base. Query PR
        history for the branch + integration base and accept a result only
        when exactly one validated row carries the worktree's current
        ``head.sha``. A full page is treated as truncated/ambiguous rather
        than silently trusting an incomplete search.
        """
        resolved_state = "UNKNOWN"
        if self._config.dry_run:
            return resolved_state
        normalized_branch = branch.removeprefix("refs/heads/")
        normalized_sha = head_sha.strip().lower()
        normalized_base = base_branch.removeprefix("refs/heads/")
        if (
            not normalized_branch
            or _GIT_OID_RE.fullmatch(normalized_sha) is None
            or not normalized_base
        ):
            return resolved_state
        head_filter = (
            f"{self._repo_owner}:{normalized_branch}"
            if self._repo_owner
            else normalized_branch
        )
        page_size = 100
        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/pulls",
                "--method",
                "GET",
                "--field",
                "state=all",
                "--field",
                f"head={head_filter}",
                "--field",
                f"base={normalized_base}",
                "--field",
                f"per_page={page_size}",
                "--jq",
                (
                    "[.[] | {number, state, merged_at, "
                    "head_sha: .head.sha, head_ref: .head.ref, "
                    "base_ref: .base.ref}]"
                ),
            )
            results = json.loads(raw)
            # ``per_page`` is the only page requested. Hitting the ceiling
            # means an older exact-head row could have been omitted.
            if (
                isinstance(results, list)
                and len(results) < page_size
                and all(isinstance(row, dict) for row in results)
            ):
                parsed_rows = [
                    _parse_branch_pr_row(
                        row,
                        expected_branch=normalized_branch,
                        expected_base=normalized_base,
                    )
                    for row in results
                ]
                matches = [
                    row
                    for row in parsed_rows
                    if row is not None and row.head_sha == normalized_sha
                ]
                if all(row is not None for row in parsed_rows):
                    if not matches:
                        resolved_state = "NONE"
                    elif len(matches) == 1:
                        match = matches[0]
                        resolved_state = "MERGED" if match.merged else match.state
        except (RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            logger.debug(
                "Could not resolve PR state for branch %s at HEAD %s",
                normalized_branch,
                normalized_sha,
                exc_info=True,
            )
        return resolved_state

    async def branch_has_diff_from_main(self, branch: str) -> bool:
        """Return whether *branch* has commits ahead of configured main branch."""
        if self._config.dry_run:
            return True
        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/compare/{self._config.main_branch}...{branch}",
                "--jq",
                "{ahead_by}",
            )
            data = json.loads(raw)
            if isinstance(data, dict):
                ahead_by = int(data.get("ahead_by", 0) or 0)
                return ahead_by > 0
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError):
            logger.warning(
                "Could not determine branch diff for %s; assuming diff exists",
                branch,
                exc_info=True,
            )
        return True

    async def list_branch_refs(self, prefix: str) -> list[tuple[str, str]]:
        """Return ``[(branch_name, sha), ...]`` for ``refs/heads/<prefix>*``.

        Thin translation of ``gh api .../git/matching-refs/heads/<prefix>``
        — propagates read/parse failures rather than swallowing them, so
        each caller applies its own resilience policy: :meth:`list_rc_branches`
        (via ``pr_manager_promotion``) chains a per-sha commit-date lookup
        and swallows failures itself; ``StaleIssueLoop``'s branch-GC skips a
        prefix and moves on.
        """
        self._assert_repo()
        raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/matching-refs/heads/{prefix}",
            "--jq",
            "[.[] | {ref: .ref, sha: .object.sha}]",
        )
        refs = json.loads(raw) if raw.strip() else []
        results: list[tuple[str, str]] = []
        for ref in refs:
            branch = str(ref.get("ref", "")).removeprefix("refs/heads/")
            sha = str(ref.get("sha", ""))
            if branch and sha:
                results.append((branch, sha))
        return results

    async def list_branch_commits(
        self, branch: str, *, limit: int = 30
    ) -> list[dict[str, str]]:
        """Return ``[{"date": iso, "message": msg}, ...]`` newest-first for *branch*.

        Thin translation of ``gh api .../commits`` — propagates read/parse
        failures rather than swallowing them (mirrors
        :meth:`list_branch_refs`). Used by ``StaleIssueLoop``'s branch-GC to
        age a candidate branch and search its history for a ``Fixes #N``
        reference.
        """
        self._assert_repo()
        raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/commits",
            "--method",
            "GET",
            "--field",
            f"sha={branch}",
            "--field",
            f"per_page={limit}",
            "--jq",
            "[.[] | {date: .commit.committer.date, message: .commit.message}]",
        )
        commits = json.loads(raw) if raw.strip() else []
        return [
            {"date": str(c.get("date", "")), "message": str(c.get("message", ""))}
            for c in commits
            if isinstance(c, dict)
        ]

    async def resolve_remote_branch_sha(self, branch: str) -> str | None:
        """Fetch ``origin/<branch>`` and return its current commit SHA.

        The release path (ADR-0011) uses this to pin a tag to the promoted
        ``main`` (ADR-0042) rather than whatever the factory checkout's
        ``HEAD`` happens to be (#11517). The fetch uses an explicit refspec
        so the remote-tracking ref is refreshed even in a single-branch
        clone, and the result is verified to be a full commit OID.

        Returns ``None`` when the fetch or the resolve fails so callers can
        fail closed. In dry-run nothing is fetched and the symbolic
        ``origin/<branch>`` ref is returned so downstream dry-run logs still
        name the intended target.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would fetch and resolve origin/%s", branch)
            return f"origin/{branch}"
        remote_ref = f"refs/remotes/origin/{branch}"
        try:
            await self._run_gh(
                "git", "fetch", "origin", f"+refs/heads/{branch}:{remote_ref}"
            )
            raw = await self._run_gh(
                "git", "rev-parse", "--verify", "--quiet", f"{remote_ref}^{{commit}}"
            )
        except RuntimeError as exc:
            logger.warning("Could not resolve origin/%s: %s", branch, exc)
            return None
        sha = raw.strip()
        if _GIT_OID_RE.fullmatch(sha) is None:
            logger.warning(
                "origin/%s resolved to %r, not a commit OID — refusing to use it",
                branch,
                sha,
            )
            return None
        return sha

    async def pull_main(self) -> bool:
        """Pull latest main into the local repo."""
        if self._config.dry_run:
            logger.info("[dry-run] Would pull main")
            return True
        try:
            await self._run_gh(
                "git",
                "pull",
                "origin",
                self._config.main_branch,
            )
            return True
        except RuntimeError as exc:
            logger.warning("Pull main failed: %s", exc)
            return False
