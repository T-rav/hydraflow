"""Dashboard listings and GitHub-metric rollups of :class:`pr_manager.PRManager`.

Extracted VERBATIM from ``pr_manager.py`` (god-class decomposition, Refs
#11547) as a mixin, same shape as ``pr_manager_promotion.py``. ``PRManager``
inherits :class:`PRManagerDashboardMixin`, so ``PRManager().list_open_prs``,
``list_hitl_items``, and their ``patch("pr_manager.PRManager.<method>")``
sites resolve unchanged.

One cohesive concern: the aggregate reads nothing in the pipeline acts on —
the operator console's PR/HITL listings and the cached label-count rollup
(open/closed/merged counts by label). They are shaped for a UI payload rather
than for a decision, which is why they cluster apart from the per-PR and
per-issue queries.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any

from models import HITLItem, LabelCounts, PRListItem
from pr_manager_common import _LABEL_CACHE_TTL

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import Literal

    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.pr_manager")


class PRManagerDashboardMixin:
    """Dashboard listings and metric rollups mixed into :class:`pr_manager.PRManager`."""

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
    _label_counts_cache: LabelCounts | None
    _label_counts_ts: float

    if TYPE_CHECKING:

        def _assert_repo(self) -> None: ...  # provided by PRManager

        async def _run_gh(
            self, *cmd: str, cwd: Path | None = None
        ) -> str: ...  # provided by PRManager

    async def _query_issues_by_labels(
        self,
        labels: list[str],
        jq_filter: str,
        *,
        error_context: str = "query_issues_by_labels",
        error_level: Literal["debug", "info", "warning", "error"] = "debug",
    ) -> list[dict[str, Any]]:
        """Fetch open issues/PRs for *labels*, deduplicated by ``number``.

        Iterates each label, queries the GitHub REST API with *jq_filter*,
        and deduplicates results by ``number``.  Individual label failures
        are logged at *error_level* and skipped.
        """
        seen: set[int] = set()
        results: list[dict[str, Any]] = []

        for label in labels:
            try:
                raw = await self._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._repo}/issues",
                    "--method",
                    "GET",
                    "--field",
                    "state=open",
                    "--field",
                    f"labels={label}",
                    "--field",
                    "per_page=50",
                    "--jq",
                    jq_filter,
                )
                for item in json.loads(raw):
                    num = item.get("number")
                    if num is None:
                        continue
                    if num not in seen:
                        seen.add(num)
                        results.append(item)
            except (
                RuntimeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                AttributeError,
            ):
                getattr(logger, error_level, logger.warning)(
                    "Failed in %s for label %s",
                    error_context,
                    label,
                    exc_info=True,
                )

        return results

    async def list_open_prs(self, labels: list[str]) -> list[PRListItem]:
        """Fetch open PRs for the given *labels*, deduplicated by PR number.

        Returns ``[]`` in dry-run mode or when any individual label query
        fails (the failure is silently skipped so other labels still succeed).
        """
        if self._config.dry_run:
            return []

        raw_items = await self._query_issues_by_labels(
            labels,
            "[.[] | select(.pull_request) | {number, url: .html_url, title}]",
            error_context="list_open_prs",
        )

        prs: list[PRListItem] = []
        for p in raw_items:
            try:
                pr_num = p["number"]
                branch, draft, author = await self._get_pr_metadata(pr_num)
                issue_number = self._issue_number_from_branch(branch)
                prs.append(
                    PRListItem(
                        pr=pr_num,
                        issue=issue_number,
                        branch=branch,
                        url=p.get("url", ""),
                        draft=draft,
                        title=p.get("title", ""),
                        author=author,
                    )
                )
            except (RuntimeError, json.JSONDecodeError, KeyError, TypeError):
                logger.debug("Skipping PR in list_open_prs", exc_info=True)
                continue

        return prs

    async def list_all_open_prs(self) -> list[PRListItem]:
        """Fetch ALL open PRs regardless of label, including author login.

        Unlike :meth:`list_open_prs` (label-filtered for the dashboard/cache),
        this returns the complete open-PR set so consumers that key on author
        — notably :class:`DependabotMergeLoop` — can see bot PRs that carry
        only GitHub-native labels (e.g. ``dependencies``) and would otherwise
        be invisible to the label-filtered cache.

        Returns ``[]`` in dry-run mode or when the ``gh`` query fails.
        """
        if self._config.dry_run:
            return []
        self._assert_repo()
        try:
            output = await self._run_gh(
                "gh",
                "pr",
                "list",
                "--repo",
                self._repo,
                "--state",
                "open",
                "--json",
                "number,headRefName,url,isDraft,title,author",
                "--limit",
                "200",
            )
            raw_items = json.loads(output)
        except (RuntimeError, json.JSONDecodeError):
            logger.warning("list_all_open_prs failed", exc_info=True)
            return []

        prs: list[PRListItem] = []
        for item in raw_items:
            branch = str(item.get("headRefName", ""))
            prs.append(
                PRListItem(
                    pr=int(item.get("number", 0)),
                    issue=self._issue_number_from_branch(branch),
                    branch=branch,
                    url=str(item.get("url", "")),
                    draft=bool(item.get("isDraft", False)),
                    title=str(item.get("title", "")),
                    author=str((item.get("author") or {}).get("login", "")),
                    is_bot=bool((item.get("author") or {}).get("is_bot", False)),
                )
            )
        return prs

    async def list_all_prs(
        self, *, state: str = "all", limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Return PRs in *state* as raw gh-wire dicts.

        Fields: ``number``, ``state``, ``labels``, ``createdAt``,
        ``closedAt``, ``mergedAt``. Used by the fitness issue fetcher
        (``service_registry``, state="all"). Propagates read/parse
        failures rather than swallowing them.
        """
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "pr",
            "list",
            "--repo",
            self._repo,
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            "number,state,labels,createdAt,closedAt,mergedAt",
        )
        return json.loads(output) if output else []

    async def _fetch_hitl_raw_issues(
        self, hitl_labels: list[str]
    ) -> list[dict[str, Any]]:
        """Fetch and deduplicate open issues matching any of the given HITL labels."""
        return await self._query_issues_by_labels(
            hitl_labels,
            "[.[] | select(.pull_request | not) | {number, title, url: .html_url}]",
            error_context="fetch_hitl_raw_issues",
            error_level="warning",
        )

    async def _build_hitl_item(self, raw_issue: dict[str, Any]) -> HITLItem:
        """Look up the associated PR for one raw issue and assemble a HITLItem."""
        branch = self._config.branch_for_issue(raw_issue["number"])
        pr_number = 0
        pr_url = ""
        try:
            head_filter = f"{self._repo_owner}:{branch}" if self._repo_owner else branch
            pr_raw = await self._run_gh(
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
                "[.[] | {number, url: .html_url}]",
            )
            pr_data = json.loads(pr_raw)
            if pr_data:
                pr_number = pr_data[0]["number"]
                pr_url = pr_data[0].get("url", "")
        except (RuntimeError, json.JSONDecodeError, KeyError, TypeError):
            logger.debug(
                "PR lookup failed for branch %s",
                branch,
                exc_info=True,
            )
        return HITLItem(
            issue=raw_issue["number"],
            title=raw_issue.get("title", ""),
            issue_url=raw_issue.get("url", ""),
            pr=pr_number,
            pr_url=pr_url,
            branch=branch,
            repo=self._config.repo_slug,
        )

    @staticmethod
    def _issue_number_from_branch(branch: str) -> int:
        issue_number = 0
        if branch.startswith("agent/issue-"):
            with contextlib.suppress(ValueError):
                issue_number = int(branch.rsplit("-", maxsplit=1)[-1])
        return issue_number

    async def find_pr_for_issue(self, issue_number: int) -> int:
        """Find the open PR number for the given *issue_number* by branch convention.

        Returns the PR number, or 0 if not found.
        """
        branch = f"agent/issue-{issue_number}"
        try:
            raw = await self._run_gh(
                "gh",
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "number",
                "--jq",
                ".[0].number // 0",
            )
            return int(raw.strip()) if raw.strip() else 0
        except (RuntimeError, ValueError):
            logger.debug("Could not find PR for issue #%d", issue_number, exc_info=True)
            return 0

    async def _get_pr_metadata(self, pr_number: int) -> tuple[str, bool, str]:
        """Resolve branch, draft status, and author for a PR via REST API."""
        raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/pulls/{pr_number}",
            "--jq",
            "{headRefName: .head.ref, isDraft: .draft, author: .user.login}",
        )
        data = json.loads(raw)
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            return "", False, ""
        return (
            str(data.get("headRefName", "")),
            bool(data.get("isDraft", False)),
            str(data.get("author", "")),
        )

    async def list_hitl_items(
        self,
        hitl_labels: list[str],
        *,
        concurrency: int = 10,
    ) -> list[HITLItem]:
        """Fetch HITL issues and look up their associated PRs.

        For each HITL label, fetches open issues, deduplicates by issue
        number, then looks up the associated PR via the ``agent/issue-N``
        branch convention.  Returns ``[]`` in dry-run mode or on failure.

        PR lookups run in parallel, capped at *concurrency* simultaneous
        ``gh api`` calls (default 10) to avoid hammering the GitHub API
        when there are many open HITL issues.
        """
        if self._config.dry_run:
            return []

        try:
            raw_issues = await self._fetch_hitl_raw_issues(hitl_labels)
            sem = asyncio.Semaphore(concurrency)

            async def _guarded(issue: dict[str, Any]) -> HITLItem:
                async with sem:
                    return await self._build_hitl_item(issue)

            results = await asyncio.gather(
                *[_guarded(issue) for issue in raw_issues],
                return_exceptions=True,
            )
            items: list[HITLItem] = []
            for r in results:
                if isinstance(r, BaseException):
                    logger.debug("Failed to build HITL item", exc_info=r)
                else:
                    items.append(r)
            return items
        except (RuntimeError, json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Failed to fetch HITL items", exc_info=True)
            return []

    async def _search_github_count(self, query: str) -> int:
        """Run a GitHub search query and return the total_count.

        Issues a ``gh api search/issues`` request with the given *query*
        string and returns the ``total_count`` integer.  Returns 0 on
        any error so callers can safely sum results.
        """
        raw = await self._run_gh(
            "gh",
            "api",
            "search/issues",
            "-f",
            f"q={query}",
            "--jq",
            ".total_count",
        )
        return int(raw.strip() or "0")

    async def _sum_label_counts(
        self,
        labels: list[str],
        query_builder: Callable[[str], str],
        *,
        log_context: str,
    ) -> int:
        """Helper to sum ``search/issues`` counts for each *label*."""
        total = 0
        for label in labels:
            try:
                total += await self._search_github_count(query_builder(label))
            except (RuntimeError, ValueError):
                logger.debug(
                    "Could not %s for label %r",
                    log_context,
                    label,
                    exc_info=True,
                )
        return total

    async def _count_open_issues_by_label(
        self, label_map: dict[str, list[str]]
    ) -> dict[str, int]:
        """Count open issues for each display key in *label_map*.

        Uses the GitHub Search API (``search/issues``) which returns
        ``total_count`` directly — no pagination, scales to 10k+ issues.
        """
        open_by_label: dict[str, int] = {}
        for display_key, label_names in label_map.items():
            open_by_label[display_key] = await self._sum_label_counts(
                label_names,
                lambda label: f'repo:{self._repo} is:issue is:open label:"{label}"',
                log_context="count open issues",
            )
        return open_by_label

    async def _count_closed_issues(self, labels: list[str]) -> int:
        """Count closed issues with any of the given *labels*.

        Uses the GitHub Search API (``search/issues``) which returns
        ``total_count`` directly — no pagination, scales to 10k+ issues.
        """
        return await self._sum_label_counts(
            labels,
            lambda label: f'repo:{self._repo} is:issue is:closed label:"{label}"',
            log_context="count closed issues",
        )

    async def _count_merged_prs(self, label: str) -> int:
        """Count merged PRs with the given *label*.

        Uses the GitHub Search API (``search/issues``) which returns
        ``total_count`` directly — no pagination, scales to 10k+ issues.
        """
        try:
            return await self._search_github_count(
                f'repo:{self._repo} is:pr is:merged label:"{label}"'
            )
        except (RuntimeError, ValueError):
            logger.debug(
                "Could not count merged PRs for label %r",
                label,
                exc_info=True,
            )
            return 0

    async def get_label_counts(self, config: HydraFlowConfig) -> LabelCounts:
        """Query GitHub for issue/PR counts by HydraFlow label.

        Returns a dict with ``open_by_label``, ``total_closed``, and
        ``total_merged`` keys.  Results are cached for 30 seconds.
        """
        import time

        now = time.monotonic()
        if (
            self._label_counts_cache is not None
            and now - self._label_counts_ts < _LABEL_CACHE_TTL
        ):
            return self._label_counts_cache

        label_map = {
            "hydraflow-plan": config.planner_label,
            "hydraflow-ready": config.ready_label,
            "hydraflow-review": config.review_label,
            "hydraflow-hitl": config.hitl_label,
            "hydraflow-fixed": config.fixed_label,
        }

        open_by_label = await self._count_open_issues_by_label(label_map)
        total_closed = await self._count_closed_issues(config.fixed_label)
        fixed_label = config.fixed_label[0] if config.fixed_label else "hydraflow-fixed"
        total_merged = await self._count_merged_prs(fixed_label)

        result: LabelCounts = {
            "open_by_label": open_by_label,
            "total_closed": total_closed,
            "total_merged": total_merged,
        }
        self._label_counts_cache = result
        self._label_counts_ts = now
        return result
