"""Read-only pull-request queries of :class:`pr_manager.PRManager`.

Extracted VERBATIM from ``pr_manager.py`` (god-class decomposition, Refs
#11547) as a mixin, same shape as ``pr_manager_promotion.py``. ``PRManager``
inherits :class:`PRManagerPRQueriesMixin`, so ``PRManager().get_pr_diff`` and
every ``patch("pr_manager.PRManager.<method>")`` site resolve unchanged.

One cohesive concern: asking GitHub *about an existing PR* — its diff, files,
commits, reviews, approvers, head SHA, mergeability, labels, comments, title
and body — plus the two listings keyed on PR identity (by label, and the
conflicting-PR sweep). Nothing here mutates; the create/merge/close lifecycle
stays in ``pr_manager.py``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from merge_state_watcher import ConflictingPR
from models import PRDiffStats, PRInfo

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.pr_manager")


class PRManagerPRQueriesMixin:
    """Read-only PR queries mixed into :class:`pr_manager.PRManager`."""

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

        async def _gh_json_query(
            self, *args: Any, **kwargs: Any
        ) -> Any: ...  # provided by PRManager

        @staticmethod
        def _issue_number_from_branch(
            branch: str,
        ) -> int: ...  # provided by PRManagerDashboardMixin

    async def list_prs_by_label(self, label: str) -> list[PRInfo]:
        """Return open (non-merged) PRs carrying *label*.

        Delegates to ``gh pr list --label <label> --state open --json ...``.
        Used by SandboxFailureFixerLoop to poll PRs needing auto-fix
        intervention, and by ``/api/sandbox-hitl`` to surface stuck PRs.
        """
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "pr",
            "list",
            "--repo",
            self._repo,
            "--label",
            label,
            "--state",
            "open",
            "--json",
            "number,headRefName,url,isDraft,labels",
            "--limit",
            "100",
        )
        items = json.loads(output)
        return [
            PRInfo(
                number=int(item.get("number", 0)),
                issue_number=self._issue_number_from_branch(
                    item.get("headRefName", "")
                ),
                branch=str(item.get("headRefName", "")),
                url=str(item.get("url", "")),
                draft=bool(item.get("isDraft", False)),
                labels=[
                    str(lbl.get("name", ""))
                    for lbl in (item.get("labels") or [])
                    if lbl.get("name")
                ],
            )
            for item in items
        ]

    async def get_pr_labels(self, pr_number: int) -> list[str]:
        """Return the label names carried by a GitHub pull request.

        Delegates to ``gh pr view <n> --json labels --jq '.labels[].name'``
        (newline-separated names), mirroring :meth:`get_issue_labels`. Read
        failures propagate rather than being swallowed so PR-scoped label
        routing can fail-closed on error instead of silently treating an
        unreadable PR as unlabelled (#10567).
        """
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            self._repo,
            "--json",
            "labels",
            "--jq",
            ".labels[].name",
        )
        return [line.strip() for line in output.splitlines() if line.strip()]

    async def _pr_commit_count(self, pr_number: int) -> int:
        """Return the commit count for a single PR.

        Fetched per-PR (not in the bulk ``pr list``) because requesting the
        ``commits`` field for many PRs expands each commit's authors connection
        and exceeds GitHub's GraphQL 500,000-node ceiling.
        """
        data = await self._gh_json_query(
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            self._repo,
            "--json",
            "commits",
            dry_run_return={"commits": []},
            error_log=f"find_label_drift: pr {pr_number} commits fetch failed",
        )
        if not isinstance(data, dict):
            return 0
        return len(data.get("commits") or [])

    async def get_pr_diff(self, pr_number: int) -> str:
        """Fetch the diff for *pr_number*."""
        try:
            return await self._run_gh(
                "gh",
                "pr",
                "diff",
                str(pr_number),
                "--repo",
                self._repo,
            )
        except RuntimeError as exc:
            logger.warning("Could not get diff for PR #%d: %s", pr_number, exc)
            return ""

    async def get_pr_diff_names(self, pr_number: int) -> list[str]:
        """Fetch the list of files changed in *pr_number*."""
        try:
            output = await self._run_gh(
                "gh",
                "pr",
                "diff",
                str(pr_number),
                "--repo",
                self._repo,
                "--name-only",
            )
            return [f.strip() for f in output.strip().splitlines() if f.strip()]
        except RuntimeError as exc:
            logger.warning(
                "Could not get diff file names for PR #%d: %s", pr_number, exc
            )
            return []

    async def get_pr_commit_messages(self, pr_number: int) -> str:
        """Return every commit message on *pr_number*, joined by blank lines.

        Headline + body per commit via ``gh pr view --json commits`` — the
        in-process analogue of P10.7's ``git log %B`` scan. The
        close-verification controller (#10358) reads it for the
        ``Skip-Regression:`` opt-out trailer and ``Closes #N`` references.
        Returns an empty string when no commits are available or on any
        failure.
        """
        if self._config.dry_run:
            return ""
        try:
            raw = await self._run_gh(
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                self._repo,
                "--json",
                "commits",
            )
            commits = json.loads(raw).get("commits") or []
        except (RuntimeError, json.JSONDecodeError, KeyError) as exc:
            logger.warning(
                "Could not fetch commit messages for PR #%d: %s", pr_number, exc
            )
            return ""

        messages: list[str] = []
        for commit in commits:
            headline = str(commit.get("messageHeadline") or "").strip()
            body = str(commit.get("messageBody") or "").strip()
            full = f"{headline}\n\n{body}".strip() if body else headline
            if full:
                messages.append(full)
        return "\n\n".join(messages)

    async def get_pr_recent_commit_diffs(self, pr_number: int, *, n: int = 3) -> str:
        """Return a concatenated diff block for the last *n* commits on *pr_number*.

        Fetches the commit list via ``gh pr view --json commits``, then retrieves
        the diff for each commit via ``gh api repos/{repo}/commits/{sha}``.
        Each section is headed by ``## <sha> <title>``.  Returns an empty string
        when no commits are available or on any failure.
        """
        if self._config.dry_run:
            return ""
        try:
            raw = await self._run_gh(
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                self._repo,
                "--json",
                "commits",
            )
            data = json.loads(raw)
            commits = data.get("commits") or []
        except (RuntimeError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("Could not fetch commits for PR #%d: %s", pr_number, exc)
            return ""

        recent = commits[-n:] if len(commits) > n else commits
        sections: list[str] = []
        for commit in recent:
            sha = str(commit.get("oid") or commit.get("sha") or "").strip()
            title = str(
                commit.get("messageHeadline") or commit.get("message") or sha
            ).strip()
            if not sha:
                continue
            try:
                diff_raw = await self._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._repo}/commits/{sha}",
                    "--header",
                    "Accept: application/vnd.github.diff",
                )
                sections.append(f"## {sha[:8]} {title}\n{diff_raw.strip()}")
            except RuntimeError as exc:
                logger.warning(
                    "Could not fetch diff for commit %s on PR #%d: %s",
                    sha[:8],
                    pr_number,
                    exc,
                )
        return "\n\n".join(sections)

    async def get_pr_approvers(self, pr_number: int) -> list[str]:
        """Fetch the list of GitHub usernames that approved *pr_number*.

        #8786 Phase 16: routed through the contracts boundary helper in
        lenient mode against ``GhPRReviewsResponse``. Drift in the
        review state enum (e.g. a new ``DRAFT`` state) or author shape
        fires WARN immediately at the call site.
        """
        from contracts.boundary import parse_with_shape  # noqa: PLC0415
        from contracts.shapes import GhPRReviewsResponse  # noqa: PLC0415

        try:
            output = await self._run_gh(
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                self._repo,
                "--json",
                "reviews",
            )
            result = parse_with_shape(output, GhPRReviewsResponse)
            approvers: list[str] = []
            if result.model_instance is not None:
                for review in result.model_instance.reviews:
                    if review.state == "APPROVED" and review.author is not None:
                        login = review.author.login
                        if login and login not in approvers:
                            approvers.append(login)
                return approvers
            # Lenient fallback — drift logged, dict-access keeps working.
            data = result.payload if isinstance(result.payload, dict) else {}
            for review in data.get("reviews", []) or []:
                if not isinstance(review, dict):
                    continue
                if review.get("state") == "APPROVED":
                    author = review.get("author") or {}
                    if isinstance(author, dict):
                        login = author.get("login", "")
                        if login and login not in approvers:
                            approvers.append(login)
            return approvers
        except (RuntimeError, ValueError) as exc:
            logger.debug("Could not get approvers for PR #%d: %s", pr_number, exc)
            return []

    async def get_pr_head_sha(self, pr_number: int) -> str:
        """Fetch the HEAD commit SHA for *pr_number*.

        Returns the SHA string, or empty string on failure or in dry-run mode.
        """
        data = await self._gh_json_query(
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            self._repo,
            "--json",
            "headRefOid",
            dry_run_return={},
            dry_run_log=f"[dry-run] Would fetch HEAD SHA for PR #{pr_number}",
            error_log=f"Could not fetch HEAD SHA for PR #{pr_number}",
        )
        if isinstance(data, dict):
            return data.get("headRefOid", "")
        return ""

    async def get_pr_diff_stats(self, pr_number: int) -> PRDiffStats:
        """Best-effort PR diff stats (commit sha, files-changed, ±lines) for
        the operator timeline (#10788).

        Runs ``gh pr view <n> --json headRefOid,mergeCommit,additions,``
        ``deletions,changedFiles`` and returns only the keys GitHub actually
        reported. On any failure or in dry-run mode it returns an *empty*
        dict — never raises — so the ``pr_created`` / ``merge_update`` emit
        sites can merge only present keys and never fabricate zero-valued
        stats (an absent key is hidden in the UI; ``files_changed: 0`` would
        render a false "0 files").

        ``commit_sha`` prefers ``mergeCommit.oid`` (populated post-merge) and
        falls back to ``headRefOid`` (available at creation time), so both the
        create and merge emit sites get a real sha.
        """
        data = await self._gh_json_query(
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            self._repo,
            "--json",
            "headRefOid,mergeCommit,additions,deletions,changedFiles",
            dry_run_return={},
            dry_run_log=f"[dry-run] Would fetch diff stats for PR #{pr_number}",
            error_log=f"Could not fetch diff stats for PR #{pr_number}",
        )
        stats: PRDiffStats = {}
        if not isinstance(data, dict):
            return stats
        merge_commit = data.get("mergeCommit")
        sha = ""
        if isinstance(merge_commit, dict):
            sha = merge_commit.get("oid") or ""
        if not sha:
            sha = data.get("headRefOid") or ""
        if sha:
            stats["commit_sha"] = sha
        # ``bool`` is an ``int`` subclass but gh never reports these as bools;
        # the isinstance guard just rejects null / malformed shapes.
        changed = data.get("changedFiles")
        if isinstance(changed, int):
            stats["files_changed"] = changed
        additions = data.get("additions")
        if isinstance(additions, int):
            stats["additions"] = additions
        deletions = data.get("deletions")
        if isinstance(deletions, int):
            stats["deletions"] = deletions
        return stats

    async def get_pr_reviews(self, pr_number: int) -> list[dict[str, str]]:
        """Fetch reviews for *pr_number* with author info.

        Returns a list of dicts with ``author``, ``state``, ``submitted_at``,
        and ``commit_id`` keys.  Returns ``[]`` on failure or in dry-run mode.
        """
        return await self._gh_json_query(
            "gh",
            "api",
            f"repos/{self._repo}/pulls/{pr_number}/reviews",
            "--jq",
            "[.[] | {author: .user.login, state: .state, submitted_at: .submitted_at, commit_id: .commit_id}]",
            dry_run_return=[],
            dry_run_log=f"[dry-run] Would fetch reviews for PR #{pr_number}",
            error_log=f"Could not fetch reviews for PR #{pr_number}",
        )

    async def get_pr_mergeable(self, pr_number: int) -> bool | None:
        """Return whether *pr_number* is mergeable (no conflicts).

        Returns ``True`` if mergeable, ``False`` if there are conflicts,
        or ``None`` if the status is unknown or cannot be determined.
        """
        if self._config.dry_run:
            return None

        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/pulls/{pr_number}",
                "--jq",
                ".mergeable",
            )
            value = raw.strip()
            if value == "true":
                return True
            if value == "false":
                return False
            return None
        except RuntimeError:
            logger.debug("Could not fetch mergeable status for PR #%d", pr_number)
            return None

    async def list_conflicting_prs(self) -> list[ConflictingPR]:
        """Return open PRs whose ``mergeable`` field is ``CONFLICTING``.

        #8786 Phase 14: routed through the contracts boundary helper in
        lenient mode against ``GhPRDetail``. The shape (``number``,
        ``headRefName``, ``labels``, ``mergeable``) matches exactly, so
        validation fires for any drift in the ``mergeable`` enum or
        labels-array structure.
        """
        if self._config.dry_run:
            return []

        from contracts.boundary import parse_list_with_shape  # noqa: PLC0415
        from contracts.shapes import GhPRDetail  # noqa: PLC0415

        try:
            raw = await self._run_gh(
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--limit",
                "200",
                "--json",
                "number,headRefName,labels,mergeable",
            )
        except RuntimeError:
            logger.debug("list_conflicting_prs: gh pr list failed", exc_info=True)
            return []

        try:
            results_list = parse_list_with_shape(raw or "[]", GhPRDetail)
        except ValueError:
            logger.warning(
                "list_conflicting_prs: malformed JSON from gh", exc_info=True
            )
            return []

        from contracts.boundary import field_or  # noqa: PLC0415

        results: list[ConflictingPR] = []
        for r in results_list:
            try:
                if field_or(r, "mergeable", "") != "CONFLICTING":
                    continue
                if r.model_instance is not None:
                    label_names = [
                        lbl.name for lbl in r.model_instance.labels if lbl.name
                    ]
                else:
                    entry = r.payload if isinstance(r.payload, dict) else {}
                    label_names = [
                        str(lbl.get("name", ""))
                        for lbl in (entry.get("labels") or [])
                        if lbl.get("name")
                    ]
                results.append(
                    ConflictingPR(
                        number=int(field_or(r, "number", 0)),
                        branch=str(
                            field_or(r, "head_ref_name", "", dict_key="headRefName")
                        ),
                        labels=label_names,
                    )
                )
            except (KeyError, TypeError, ValueError):
                logger.debug(
                    "list_conflicting_prs: skipping malformed entry", exc_info=True
                )
                continue
        return results

    async def get_pr_comments(self, pr_number: int) -> list[dict[str, str]]:
        """Fetch issue-level comments for *pr_number* with author info.

        Returns a list of dicts with ``author`` and ``created_at`` keys.
        Returns ``[]`` on failure or in dry-run mode.
        """
        return await self._gh_json_query(
            "gh",
            "api",
            f"repos/{self._repo}/issues/{pr_number}/comments",
            "--jq",
            "[.[] | {author: .user.login, created_at: .created_at}]",
            dry_run_return=[],
            dry_run_log=f"[dry-run] Would fetch comments for PR #{pr_number}",
            error_log=f"Could not fetch comments for PR #{pr_number}",
        )

    async def get_pr_title_and_body(self, pr_number: int) -> tuple[str, str]:
        """Fetch the title and body of *pr_number*.

        Returns ``("", "")`` on failure or in dry-run mode.
        """
        data = await self._gh_json_query(
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            self._repo,
            "--json",
            "title,body",
            dry_run_return={},
            dry_run_log=f"[dry-run] Would fetch title/body for PR #{pr_number}",
            error_log=f"Could not fetch title/body for PR #{pr_number}",
        )
        if isinstance(data, dict):
            return (data.get("title", ""), data.get("body", ""))
        return ("", "")

    async def get_pr_for_issue(self, issue_number: int) -> int:
        """Find the merged (or open) PR number for *issue_number*.

        Searches for a PR whose branch matches the ``agent/issue-{N}`` pattern.
        Returns the PR number, or ``0`` when not found.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would look up PR for issue #%d", issue_number)
            return 0

        branch = f"agent/issue-{issue_number}"
        head_filter = f"{self._repo_owner}:{branch}" if self._repo_owner else branch

        # Search merged PRs first, then open
        for pr_state in ("closed", "open"):
            prs = await self._gh_json_query(
                "gh",
                "api",
                f"repos/{self._repo}/pulls",
                "--method",
                "GET",
                "--field",
                f"state={pr_state}",
                "--field",
                f"head={head_filter}",
                "--field",
                "per_page=1",
                "--jq",
                "[.[] | {number}]",
                dry_run_return=[],
                error_log=(
                    f"Could not resolve PR for issue #{issue_number} (state={pr_state})"
                ),
                error_level="debug",
                exceptions=(
                    RuntimeError,
                    ValueError,
                    KeyError,
                    TypeError,
                    json.JSONDecodeError,
                ),
                log_exc_info=True,
            )
            if prs:
                return int(prs[0]["number"])

        return 0
