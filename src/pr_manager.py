"""Pull request lifecycle management via the ``gh`` CLI."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeVar
from urllib.parse import quote

import ci_sentinels
from comment_formatter import CommentFormatter, SelfReviewError
from config import Credentials, HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from merge_state_watcher import ConflictingPR
from models import (
    CICheckPayload,
    ClosedStageLabelDrift,
    CodeScanningAlert,
    GitHubIssue,
    GitHubIssueSummary,
    HITLItem,
    IssueCreatedPayload,
    LabelCounts,
    LabelDrift,
    MergeUpdatePayload,
    PRCreatedPayload,
    PRInfo,
    PRListItem,
    ReviewVerdict,
)
from prep import HYDRAFLOW_LABELS, HYDRAFLOW_LITERAL_LABELS
from repro_manifest import append_manifest
from subprocess_util import run_subprocess, run_subprocess_with_retry
from telemetry.spans import port_span  # noqa: E402
from traceability import append_req_trailer, extract_req_id

if TYPE_CHECKING:
    from contracts.boundary import BoundaryParseResult
    from contracts.shapes import GhIssueListItem

logger = logging.getLogger("hydraflow.pr_manager")

# Cache TTL for label-count queries (seconds).
_LABEL_CACHE_TTL: int = 30


def _gh_wire_labels(r: BoundaryParseResult[GhIssueListItem]) -> list[dict[str, str]]:
    """Project one lenient-parsed gh issue row's labels into gh wire shape.

    Shared by ``_project_issue_summaries`` (open listing, #9943) and
    ``list_closed_issues_by_label`` (#8996 — the closed listing needs labels
    too, since ``escalation_reconcile.is_bot_close`` reads them to distinguish
    a programmatic close from a human one).
    """
    if r.model_instance is not None:
        return [{"name": lbl.name} for lbl in r.model_instance.labels if lbl.name]
    entry = r.payload if isinstance(r.payload, dict) else {}
    return [
        {"name": str(lbl.get("name", ""))}
        for lbl in (entry.get("labels") or [])
        if isinstance(lbl, dict) and lbl.get("name")
    ]


def _project_issue_summaries(
    results: list[BoundaryParseResult[GhIssueListItem]],
) -> list[GitHubIssueSummary]:
    """Project lenient-parsed gh issue rows into ``GitHubIssueSummary`` dicts.

    Shared by ``list_issues_by_label`` / ``list_open_issues`` — previously two
    byte-identical copies (#10025). ``labels`` ride along in gh wire shape
    (``{"name": ...}``, #9943) so consumers like the preflight human-required
    filter see real data whether the row validated or fell back to the raw
    payload.
    """
    # Local import keeps the module-load contract identical when the
    # contracts subsystem isn't imported elsewhere yet.
    from contracts.boundary import field_or  # noqa: PLC0415

    summaries: list[GitHubIssueSummary] = []
    for r in results:
        summaries.append(
            {
                "number": field_or(r, "number", 0),
                "title": field_or(r, "title", ""),
                "body": field_or(r, "body", ""),
                "updated_at": field_or(r, "updated_at", "", dict_key="updatedAt"),
                "labels": _gh_wire_labels(r),
            }
        )
    return summaries


_JSONValue = TypeVar("_JSONValue")


def _is_missing_label_404(exc: RuntimeError) -> bool:
    """Return True when gh reports a missing label during label removal."""
    msg = str(exc).lower()
    return "label does not exist" in msg and "http 404" in msg


# Lazy-bound wrappers for the per-issue cost-alert hook (spec §4.11 Task 10).
# Importing ``dashboard_routes._cost_rollups`` at module load time triggers
# the ``dashboard_routes`` package ``__init__`` → ``_routes`` → ``pr_manager``
# cycle. Deferring until first call breaks the cycle. These names live at
# module level so tests can monkeypatch them without reaching into imports.
def check_issue_cost(*args: Any, **kwargs: Any) -> Any:
    """Forward to :func:`cost_budget_alerts.check_issue_cost` (lazy)."""
    from cost_budget_alerts import check_issue_cost as _impl  # noqa: PLC0415

    return _impl(*args, **kwargs)


def iter_priced_inferences_for_issue(*args: Any, **kwargs: Any) -> Any:
    """Forward to :func:`dashboard_routes._cost_rollups.iter_priced_inferences_for_issue` (lazy)."""
    from dashboard_routes._cost_rollups import (  # noqa: PLC0415
        iter_priced_inferences_for_issue as _impl,
    )

    return _impl(*args, **kwargs)


def load_pricing(*args: Any, **kwargs: Any) -> Any:
    """Forward to :func:`model_pricing.load_pricing` (lazy, keeps hook imports cheap)."""
    from model_pricing import load_pricing as _impl  # noqa: PLC0415

    return _impl(*args, **kwargs)


# Re-export for backward compatibility
__all__ = ["CommentFormatter", "SelfReviewError", "PRManager"]


def _normalise_issue_comment(comment: dict[str, Any]) -> dict[str, Any]:
    """Map a ``gh issue view --json comments`` object to the stable port shape.

    gh emits GraphQL-shaped ``author.login`` / ``createdAt``; the port contract
    (and the fake) expose REST-shaped ``user.login`` / ``created_at``. Accept
    either input so the contract holds across gh versions.
    """
    author = comment.get("author") or comment.get("user") or {}
    login = author.get("login", "") if isinstance(author, dict) else ""
    return {
        "user": {"login": login},
        "body": comment.get("body", ""),
        "created_at": comment.get("createdAt") or comment.get("created_at") or "",
    }


class PRManager:
    """Pushes branches, creates PRs, merges, and manages labels."""

    _GITHUB_COMMENT_LIMIT = CommentFormatter.GITHUB_COMMENT_LIMIT
    _TRUNCATION_MARKER = CommentFormatter.TRUNCATION_MARKER
    _HEADER_RESERVE = 50  # room for "*Part X/Y*\n\n" prefix

    # Re-export from prep module for backward compatibility
    _HYDRAFLOW_LABELS = HYDRAFLOW_LABELS
    _HYDRAFLOW_LITERAL_LABELS = HYDRAFLOW_LITERAL_LABELS

    _REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        credentials: Credentials | None = None,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._credentials = credentials or Credentials()
        self._repo = config.repo
        self._repo_owner = config.repo.split("/", 1)[0] if "/" in config.repo else ""
        self._max_retries = config.gh_max_retries
        self._label_counts_cache: LabelCounts | None = None
        self._label_counts_ts: float = 0.0
        # #9842: notified on every successful ``swap_pipeline_labels`` so the
        # dashboard's in-memory pipeline moves in seconds, not at the 300s
        # label poll. Wired by service_registry to
        # ``IssueStore.apply_label_transition``; None outside full wiring.
        self._pipeline_label_listener: Callable[[int, str], object] | None = None

    def set_pipeline_label_listener(
        self, listener: Callable[[int, str], object]
    ) -> None:
        """Register a ``(issue_number, new_label)`` callback fired after each
        successful :meth:`swap_pipeline_labels` add (#9842).

        Internal wiring plumbing deliberately NOT on :class:`ports.PRPort`;
        service_registry gates the call on attribute presence so port fakes
        stay untouched.
        """
        self._pipeline_label_listener = listener

    def _notify_pipeline_label_listener(
        self, issue_number: int, new_label: str
    ) -> None:
        """Best-effort listener dispatch — a board-push failure must never
        fail the GitHub label swap itself."""
        if self._pipeline_label_listener is None:
            return
        try:
            self._pipeline_label_listener(issue_number, new_label)
        except Exception:
            logger.warning(
                "pipeline label listener failed for issue #%d → %s",
                issue_number,
                new_label,
                exc_info=True,
            )

    def _assert_repo(self) -> None:
        """Raise ``RuntimeError`` if ``self._repo`` is empty or malformed."""
        if not self._repo or not self._REPO_SLUG_RE.fullmatch(self._repo):
            msg = f"PRManager: repo is not configured or invalid ({self._repo!r}) — refusing to mutate GitHub"
            raise RuntimeError(msg)

    async def _run_gh(self, *cmd: str, cwd: Path | None = None) -> str:
        """Run a gh/git command with retry logic."""
        return await run_subprocess_with_retry(
            *cmd,
            cwd=cwd or self._config.repo_root,
            gh_token=self._credentials.gh_token,
            max_retries=self._max_retries,
        )

    async def _gh_json_query(
        self,
        *cmd: str,
        dry_run_return: _JSONValue,
        dry_run_log: str | None = None,
        error_log: str | None = None,
        error_level: Literal["debug", "info", "warning", "error"] = "warning",
        loader: Callable[[str], _JSONValue] = json.loads,
        exceptions: tuple[type[BaseException], ...] | None = None,
        log_exc_info: bool = False,
    ) -> _JSONValue:
        """Run a ``gh`` command that returns JSON with shared dry-run/error handling."""
        if self._config.dry_run:
            if dry_run_log:
                logger.info(dry_run_log)
            return dry_run_return
        exc_types = (
            exceptions
            if exceptions is not None
            else (RuntimeError, json.JSONDecodeError)
        )
        try:
            raw = await self._run_gh(*cmd)
            return loader(raw)
        except exc_types as exc:
            log_fn = getattr(logger, error_level, logger.warning)
            message = error_log or "GitHub JSON query failed"
            if log_exc_info:
                log_fn(message, exc_info=True)
            else:
                log_fn("%s: %s", message, exc)
            return dry_run_return

    async def ensure_labels_exist(self) -> None:
        """Create all HydraFlow lifecycle labels in the repo if they don't exist.

        Delegates to :func:`prep.ensure_labels` which handles creation,
        reporting, and dry-run behaviour.
        """
        self._assert_repo()
        from prep import ensure_labels  # noqa: PLC0415

        result = await ensure_labels(self._config)
        logger.info(result.summary())

    @port_span("hf.port.pr.push_branch")
    async def push_branch(
        self, worktree_path: Path, branch: str, *, force: bool = False
    ) -> bool:
        """Push *branch* to origin from *worktree_path*.

        When ``force`` is True the push uses ``--force-with-lease`` for
        safe history rewrites (fresh-branch rebuilds, etc.).
        Returns *True* on success.
        """
        self._assert_repo()
        if self._config.dry_run:
            action = "force-push" if force else "push"
            logger.info("[dry-run] Would %s branch %s", action, branch)
            return True

        cmd = [
            "git",
            "push",
            "--no-verify",
        ]
        if force:
            cmd.append("--force-with-lease")
        cmd += ["-u", "origin", branch]

        try:
            await run_subprocess(
                *cmd,
                cwd=worktree_path,
                gh_token=self._credentials.gh_token,
            )
            action = "Force-pushed" if force else "Pushed"
            logger.info("%s branch %s to origin", action, branch)
            return True
        except RuntimeError as exc:
            action = "Force-push" if force else "Push"
            logger.warning("%s failed for %s: %s", action, branch, exc)
            return False

    @staticmethod
    def expected_pr_title(issue_number: int, issue_title: str) -> str:
        """Return the canonical PR title for an issue: ``Fixes #N: <title>``."""
        title = f"Fixes #{issue_number}: {issue_title}"
        if len(title) > 70:
            title = title[:67] + "..."
        return title

    async def update_pr_title(self, pr_number: int, title: str) -> bool:
        """Update the title of an existing PR.  Returns True on success."""
        if self._config.dry_run or pr_number <= 0:
            return False
        try:
            self._assert_repo()
            await self._run_gh(
                "gh",
                "pr",
                "edit",
                str(pr_number),
                "--repo",
                self._repo,
                "--title",
                title,
            )
            logger.info("Updated PR #%d title to: %s", pr_number, title)
            return True
        except RuntimeError:
            logger.warning(
                "Failed to update title for PR #%d", pr_number, exc_info=True
            )
            return False

    @port_span("hf.port.pr.create_pr")
    async def create_pr(
        self,
        issue: GitHubIssue,
        branch: str,
        *,
        draft: bool = False,
    ) -> PRInfo:
        """Create a PR for *branch* linked to *issue*.

        Returns a :class:`PRInfo` with the PR number and URL.
        """
        self._assert_repo()
        title = self.expected_pr_title(issue.number, issue.title)

        body = (
            f"## Summary\n\n"
            f"Closes #{issue.number}.\n\n"
            f"## Issue\n\n{issue.title}\n\n"
            f"## Test plan\n\n"
            f"- [ ] Unit tests pass (`make test`)\n"
            f"- [ ] Linting passes (`make lint`)\n"
            f"- [ ] Manual review of changes\n\n"
            f"---\n"
            f"Generated by HydraFlow"
        )
        # CH-7 (#9735): attach the reproducibility manifest — evidence of the
        # models/prompts/config in effect at authoring time. Fail-open.
        body = append_manifest(body, config=self._config)
        # CH-5 traceability: the requirement ID is re-derived from the issue
        # (req:<id> label or Req-ID: body line) so it survives every label
        # state-machine round trip, and lands as a PR-body trailer — applied
        # after the manifest so the trailer stays terminal.
        body = append_req_trailer(
            body, extract_req_id(labels=issue.labels, body=issue.body)
        )

        if self._config.dry_run:
            logger.info(
                "[dry-run] Would create %sPR for issue #%d",
                "draft " if draft else "",
                issue.number,
            )
            return PRInfo(
                number=0,
                issue_number=issue.number,
                branch=branch,
                url="",
                draft=draft,
            )

        cmd = [
            "gh",
            "pr",
            "create",
            "--repo",
            self._repo,
            "--head",
            branch,
            "--base",
            self._config.base_branch(),
            "--title",
            title,
        ]
        if draft:
            cmd.append("--draft")

        try:
            output = await self._run_with_body_file(
                *cmd, body=body, cwd=self._config.repo_root
            )
            # gh pr create --json would be better, but the URL is in stdout
            pr_url = output.strip()

            # Validate output looks like a PR URL before parsing
            if "/pull/" not in pr_url:
                raise RuntimeError(
                    f"Unexpected gh pr create output (expected PR URL): {pr_url[:200]}"
                )

            # Get PR number from URL (e.g., https://github.com/org/repo/pull/123)
            pr_number = int(pr_url.rstrip("/").split("/")[-1])

            pr_info = PRInfo(
                number=pr_number,
                issue_number=issue.number,
                branch=branch,
                url=pr_url,
                draft=draft,
            )

            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.PR_CREATED,
                    data=PRCreatedPayload(
                        pr=pr_number,
                        issue=issue.number,
                        branch=branch,
                        draft=draft,
                        url=pr_url,
                        title=title,
                    ),
                )
            )

            return pr_info

        except (RuntimeError, ValueError) as exc:
            logger.warning("PR creation failed for issue #%d: %s", issue.number, exc)
            existing = await self.find_open_pr_for_branch(
                branch, issue_number=issue.number
            )
            if existing is not None:
                logger.info(
                    "Using existing PR #%d for issue #%d on branch %s after create failure",
                    existing.number,
                    issue.number,
                    branch,
                )
                await self.update_pr_title(existing.number, title)
                return existing
            return PRInfo(
                number=0,
                issue_number=issue.number,
                branch=branch,
                draft=draft,
            )

    async def create_promotion_pr(
        self,
        *,
        rc_branch: str,
        title: str,
        body: str,
    ) -> int:
        """Open a promotion PR from *rc_branch* into ``main_branch``.

        Used exclusively by :class:`StagingPromotionLoop`. Always targets
        ``main_branch`` regardless of ``staging_enabled`` — this is the path
        that promotes release candidates into the known-good branch.

        Publishes a :data:`EventType.PR_CREATED` event with ``issue=0`` since
        promotion PRs are not tied to a specific issue.
        """
        self._assert_repo()

        if self._config.dry_run:
            logger.info(
                "[dry-run] Would create promotion PR from %s to %s",
                rc_branch,
                self._config.main_branch,
            )
            return 0

        cmd = [
            "gh",
            "pr",
            "create",
            "--repo",
            self._repo,
            "--head",
            rc_branch,
            "--base",
            self._config.main_branch,
            "--title",
            title,
        ]
        output = await self._run_with_body_file(
            *cmd, body=body, cwd=self._config.repo_root
        )
        url = output.strip()
        if "/pull/" not in url:
            raise RuntimeError(
                f"Unexpected gh pr create output (expected PR URL): {url[:200]}"
            )
        pr_number = int(url.rstrip("/").split("/")[-1])

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data=PRCreatedPayload(
                    pr=pr_number,
                    issue=0,
                    branch=rc_branch,
                    draft=False,
                    url=url,
                    title=title,
                ),
            )
        )

        return pr_number

    async def create_rc_branch(self, rc_branch: str) -> str:
        """Create *rc_branch* at the current tip of ``staging_branch``.

        Used exclusively by :class:`StagingPromotionLoop`. Returns the SHA
        the new ref points at. Raises ``RuntimeError`` when the GitHub API
        rejects the create (e.g., the ref already exists).
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would create %s from %s",
                rc_branch,
                self._config.staging_branch,
            )
            return "dry-run-sha"

        staging_raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs/heads/{self._config.staging_branch}",
            "--jq",
            ".object.sha",
        )
        sha = staging_raw.strip().strip('"')
        if not sha:
            raise RuntimeError(
                f"Could not resolve {self._config.staging_branch} HEAD sha"
            )

        await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs",
            "--method",
            "POST",
            "--field",
            f"ref=refs/heads/{rc_branch}",
            "--field",
            f"sha={sha}",
        )
        return sha

    async def push_synthetic_commit(self, branch: str, message: str) -> str:
        """Append a tree-identical synthetic commit on top of *branch*.

        Workaround for issue #8705: rc/* branches created via the git/refs
        REST API and turned into PRs by ``gh pr create`` don't fire
        ``pull_request: opened`` workflows reliably (CodeQL, Browser
        Scenarios, etc. never run on the PR head SHA). Pushing a
        synthetic commit fires ``pull_request: synchronize`` which DOES
        trigger workflows. The commit's tree is identical to its parent
        so no real changes are introduced.

        Returns the new HEAD SHA.
        """
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would push synthetic commit on %s: %s", branch, message
            )
            return "dry-run-sha"
        self._assert_repo()

        head_raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs/heads/{branch}",
            "--jq",
            ".object.sha",
        )
        head_sha = head_raw.strip().strip('"')
        if not head_sha:
            raise RuntimeError(f"Could not resolve {branch} HEAD sha")

        tree_raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/commits/{head_sha}",
            "--jq",
            ".tree.sha",
        )
        tree_sha = tree_raw.strip().strip('"')
        if not tree_sha:
            raise RuntimeError(f"Could not resolve tree sha for {head_sha}")

        new_raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/commits",
            "--method",
            "POST",
            "--field",
            f"message={message}",
            "--field",
            f"tree={tree_sha}",
            "--raw-field",
            f"parents[]={head_sha}",
        )
        try:
            new_commit = json.loads(new_raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Unexpected synthetic-commit POST response: {new_raw[:200]}"
            ) from exc
        new_sha = str(new_commit.get("sha", "")).strip()
        if not new_sha:
            raise RuntimeError(
                f"Synthetic commit POST returned no sha: {new_raw[:200]}"
            )

        await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs/heads/{branch}",
            "--method",
            "PATCH",
            "--field",
            f"sha={new_sha}",
        )
        return new_sha

    async def find_open_promotion_pr(self) -> PRInfo | None:
        """Return the open ``rc/*`` promotion PR targeting ``main_branch``, or None.

        Used exclusively by :class:`StagingPromotionLoop`. Only one promotion
        PR is expected at a time; if multiple exist, the first listed wins.
        """
        if self._config.dry_run:
            return None
        prefix = self._config.rc_branch_prefix
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
                f"base={self._config.main_branch}",
                "--field",
                "per_page=100",
                "--jq",
                f'[.[] | select(.head.ref | startswith("{prefix}")) | '
                "{number, url: .html_url, isDraft: .draft, "
                "branch: .head.ref}] | .[0] // empty",
            )
            text = raw.strip()
            if not text:
                return None
            pr_data = json.loads(text)
        except (RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            logger.debug("Could not resolve open promotion PR", exc_info=True)
            return None
        return PRInfo(
            number=int(pr_data["number"]),
            issue_number=0,
            branch=str(pr_data.get("branch", "")),
            url=str(pr_data.get("url", "")),
            draft=bool(pr_data.get("isDraft", False)),
        )

    async def ensure_branch_exists(self, branch: str, *, base: str) -> bool:
        """Create *branch* from *base* HEAD if it doesn't already exist.

        Returns ``True`` when the branch was created this call, ``False`` when
        it already existed. Raises :class:`RuntimeError` on API failure.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would ensure branch %s from %s", branch, base)
            return False
        try:
            await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/git/refs/heads/{branch}",
                "--jq",
                ".ref",
            )
            return False
        except RuntimeError:
            pass

        base_raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs/heads/{base}",
            "--jq",
            ".object.sha",
        )
        sha = base_raw.strip().strip('"')
        if not sha:
            raise RuntimeError(f"Could not resolve {base} HEAD sha")
        await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/git/refs",
            "--method",
            "POST",
            "--field",
            f"ref=refs/heads/{branch}",
            "--field",
            f"sha={sha}",
        )
        return True

    async def apply_staging_branch_protection(self, branch: str) -> dict[str, Any]:
        """Apply HydraFlow's default protection rules to *branch*.

        Rules: no force-push, no deletion, require CI + Quality status checks
        pass before merge, linear history not required (merge commits allowed).
        Admin enforcement is OFF so the factory can still push via its bot.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would protect branch %s", branch)
            return {"status": "dry-run"}

        payload = {
            "required_status_checks": {
                "strict": False,
                "contexts": ["CI", "Quality"],
            },
            "enforce_admins": False,
            "required_pull_request_reviews": None,
            "restrictions": None,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "required_linear_history": False,
            "required_conversation_resolution": False,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(json.dumps(payload))
            tmp_path = fh.name
        try:
            await self._run_gh(
                "gh",
                "api",
                "--method",
                "PUT",
                "-H",
                "Accept: application/vnd.github+json",
                f"repos/{self._repo}/branches/{branch}/protection",
                "--input",
                tmp_path,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        return {"status": "protected", "branch": branch}

    async def list_recent_promotion_prs(self, days: int = 7) -> list[dict[str, Any]]:
        """Return recently closed ``rc/*`` promotion PRs.

        Each entry: ``{number, branch, merged, closed_at, url}``. Used for
        RC lifecycle dashboard metrics (throughput + failure rate). Only
        PRs whose ``updated_at`` is within *days* of now are returned.

        #8786 Phase 11: routed through the contracts boundary helper in
        lenient mode against ``GhPromotionPR``. The HydraFlow-defined
        projection (a custom ``--jq``) is part of our public contract
        with downstream callers and benefits from the same drift signal
        as direct ``--json`` invocations.
        """
        if self._config.dry_run:
            return []
        from contracts.boundary import parse_list_with_shape  # noqa: PLC0415
        from contracts.shapes import GhPromotionPR  # noqa: PLC0415

        prefix = self._config.rc_branch_prefix
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/pulls",
                "--method",
                "GET",
                "--field",
                "state=closed",
                "--field",
                f"base={self._config.main_branch}",
                "--field",
                "per_page=100",
                "--field",
                "sort=updated",
                "--field",
                "direction=desc",
                "--jq",
                (
                    f'[.[] | select(.head.ref | startswith("{prefix}")) '
                    f'| select(.updated_at > "{cutoff}") '
                    "| {number, branch: .head.ref, merged: (.merged_at != null), "
                    "closed_at: .closed_at, url: .html_url}]"
                ),
            )
            text = raw.strip()
            if not text:
                return []
            results = parse_list_with_shape(text, GhPromotionPR)
            return [
                (
                    r.model_instance.model_dump(by_alias=False)
                    if r.model_instance is not None
                    else (r.payload if isinstance(r.payload, dict) else {})
                )
                for r in results
            ]
        except (RuntimeError, ValueError, json.JSONDecodeError):
            logger.debug("Could not list recent promotion PRs", exc_info=True)
            return []

    async def list_rc_branches(self) -> list[tuple[str, str]]:
        """Return ``[(branch_name, committer_date_iso), ...]`` for all ``rc/*`` refs.

        Used exclusively by :class:`StagingPromotionLoop` for retention cleanup.
        ``committer_date`` is the ref tip's committer date (ISO 8601), which
        matches the time the RC was cut since RC branches are frozen snapshots.
        """
        if self._config.dry_run:
            return []
        prefix = self._config.rc_branch_prefix
        try:
            raw = await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/git/matching-refs/heads/{prefix}",
                "--jq",
                "[.[] | {ref: .ref, sha: .object.sha}]",
            )
            refs = json.loads(raw) if raw.strip() else []
        except (RuntimeError, ValueError, json.JSONDecodeError):
            logger.debug("Could not list rc/* refs", exc_info=True)
            return []

        results: list[tuple[str, str]] = []
        for ref in refs:
            branch = str(ref.get("ref", "")).removeprefix("refs/heads/")
            sha = str(ref.get("sha", ""))
            if not branch or not sha:
                continue
            try:
                commit_raw = await self._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._repo}/git/commits/{sha}",
                    "--jq",
                    ".committer.date",
                )
            except RuntimeError:
                logger.debug(
                    "Could not fetch committer date for %s", sha, exc_info=True
                )
                continue
            committer_date = commit_raw.strip().strip('"')
            if committer_date:
                results.append((branch, committer_date))
        return results

    async def delete_branch(self, branch: str) -> bool:
        """Delete *branch* from the remote. Returns True on success."""
        if self._config.dry_run:
            logger.info("[dry-run] Would delete branch %s", branch)
            return True
        try:
            await self._run_gh(
                "gh",
                "api",
                "--method",
                "DELETE",
                f"repos/{self._repo}/git/refs/heads/{branch}",
            )
            return True
        except RuntimeError:
            logger.warning("Failed to delete branch %s", branch, exc_info=True)
            return False

    async def update_pr_branch(self, pr_number: int, *, method: str = "rebase") -> bool:
        """Update the PR head onto its target branch via GitHub's API.

        Wraps ``PUT /repos/{owner}/{repo}/pulls/{n}/update-branch`` with
        ``update_method=<method>``. *method* is ``"rebase"`` (rewrites the head
        SHAs onto target) or ``"merge"`` (SHA-preserving — merges target into the
        head; GitHub's own default). :meth:`merge_promotion_pr` recovery uses
        ``"merge"`` so RC SHAs survive and ``main`` stays an ancestor of
        ``staging`` (#10552); the squash-based :meth:`merge_pr` recovery uses the
        ``"rebase"`` default. Returns True when GitHub successfully updates the
        head ref (HTTP 202), False on conflict (HTTP 422) or any other failure.
        The factory's "process-driven merge" pattern uses this to recover when
        ``merge_pr`` / ``merge_promotion_pr`` fail because the head fell behind
        target.

        Real conflicts (overlap that GitHub can't auto-resolve) surface as
        False; callers fall through to their existing failure paths (find-issue,
        HITL release) — we never auto-resolve conflict markers locally.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would update branch on PR #%d via %s", pr_number, method
            )
            return True
        try:
            await self._run_gh(
                "gh",
                "api",
                "--method",
                "PUT",
                f"repos/{self._repo}/pulls/{pr_number}/update-branch",
                "--field",
                f"update_method={method}",
            )
            return True
        except RuntimeError as exc:
            logger.warning(
                "update_pr_branch(#%d, method=%s) failed: %s", pr_number, method, exc
            )
            return False

    @port_span("hf.port.pr.update_pr_base")
    async def update_pr_base(self, pr_number: int, *, base: str) -> bool:
        """Retarget a PR's base branch via `gh pr edit --base`.

        Used by ``BaseBranchAutoRetargeter`` to retarget PRs opened against
        the wrong base after the two-tier branch model is activated. Idempotent
        from GitHub's side (re-targeting to the same base is a no-op).

        Returns True on success, False on failure.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would update PR #%d base to %s", pr_number, base)
            return True
        try:
            await run_subprocess(
                "gh",
                "pr",
                "edit",
                str(pr_number),
                "--repo",
                self._repo,
                "--base",
                base,
                cwd=self._config.repo_root,
                gh_token=self._credentials.gh_token,
            )
            return True
        except RuntimeError as exc:
            logger.warning(
                "update_pr_base(#%d, base=%s) failed: %s", pr_number, base, exc
            )
            return False

    async def _rebase_and_recheck_ci(
        self,
        pr_number: int,
        *,
        method: str = "rebase",
        ci_timeout: int = 300,
        ci_poll_interval: int = 30,
    ) -> bool:
        """Update the PR head onto its target via *method* and re-poll CI.

        *method* selects GitHub's ``update_method``: ``"rebase"`` (default, used
        by the squash-based :meth:`merge_pr` recovery — squash discards pre-merge
        SHAs anyway) or ``"merge"`` (used by :meth:`merge_promotion_pr` recovery,
        which MUST preserve the RC commit SHAs so ``main`` stays an ancestor of
        ``staging`` — see #10552).

        Returns True only when both the update and post-update CI succeed (caller
        should retry merge). False = give up: the update hit a real conflict, or
        post-update CI failed."""
        if not await self.update_pr_branch(pr_number, method=method):
            return False
        # Fresh stop_event: this is a one-shot recovery, not bound to the
        # caller's loop lifecycle.
        passed, _summary = await self.wait_for_ci(
            pr_number, ci_timeout, ci_poll_interval, asyncio.Event()
        )
        return passed

    async def merge_promotion_pr(
        self, pr_number: int, *, auto_rebase: bool = False
    ) -> bool:
        """Merge *pr_number* via ``--merge`` (merge commit), not squash.

        Used exclusively by :class:`StagingPromotionLoop`. Merge commit
        preserves the staging integration history on ``main`` and avoids
        the growing-diff problem a squash-merged promotion PR would create
        on the next RC cycle. See ADR-0042.

        When ``auto_rebase=True`` and the merge fails (the RC head is behind
        ``main`` by the main-only synthetic ``chore(rc)`` + merge commits),
        attempts one recovery cycle before giving up: update the RC branch onto
        ``main`` via ``update_method=merge`` — SHA-preserving, so ``main`` stays
        an ancestor of ``staging`` — then re-poll CI and retry the merge. A
        rebase-update here would rewrite every RC SHA and permanently diverge
        ``main`` from ``staging`` (see #10552).
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would promotion-merge PR #%d", pr_number)
            return True
        for attempt in range(2):
            try:
                await run_subprocess(
                    "gh",
                    "pr",
                    "merge",
                    str(pr_number),
                    "--repo",
                    self._repo,
                    "--merge",
                    "--delete-branch",
                    cwd=self._config.repo_root,
                    gh_token=self._credentials.gh_token,
                )
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.MERGE_UPDATE,
                        data=MergeUpdatePayload(pr=pr_number, status="merged"),
                    )
                )
                return True
            except RuntimeError as exc:
                logger.warning(
                    "Promotion merge failed for PR #%d (attempt %d): %s",
                    pr_number,
                    attempt + 1,
                    exc,
                )
                if (
                    attempt == 0
                    and auto_rebase
                    and await self._rebase_and_recheck_ci(pr_number, method="merge")
                ):
                    continue
                return False
        return False

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

    @port_span("hf.port.pr.merge_pr")
    async def merge_pr(self, pr_number: int, *, auto_rebase: bool = False) -> bool:
        """Merge PR immediately via squash merge with branch deletion.

        Returns *True* on success.

        When ``auto_rebase=True`` and the merge fails (e.g. head behind
        target), attempts one rebase-via-GitHub + re-poll-CI + retry-merge
        cycle before giving up. Real conflicts that GitHub can't auto-rebase
        return False to the caller's existing failure path (HITL release,
        find-issue, etc.) — we never auto-resolve conflict markers locally.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would merge PR #%d", pr_number)
            return True

        # Fetch title before merging so we can include it in the event.
        # Isolated from the merge try/except so a title-fetch failure
        # cannot prevent the merge itself.
        pr_title = ""
        try:
            pr_title, _ = await self.get_pr_title_and_body(pr_number)
        except Exception:
            logger.debug(
                "Could not fetch title for PR #%d before merge",
                pr_number,
                exc_info=True,
            )

        for attempt in range(2):
            try:
                await run_subprocess(
                    "gh",
                    "pr",
                    "merge",
                    str(pr_number),
                    "--repo",
                    self._repo,
                    "--squash",
                    "--delete-branch",
                    cwd=self._config.repo_root,
                    gh_token=self._credentials.gh_token,
                )
            except RuntimeError as exc:
                logger.warning(
                    "Merge failed for PR #%d (attempt %d): %s",
                    pr_number,
                    attempt + 1,
                    exc,
                )
                if (
                    attempt == 0
                    and auto_rebase
                    and await self._rebase_and_recheck_ci(pr_number)
                ):
                    continue
                return False

            # Resolve the issue number from the PR title once, here, so it can
            # both (a) ride the MERGE_UPDATE event — the dashboard needs it to
            # move the card review -> merged in real time — and (b) feed the
            # per-issue cost check below. Prefer a Fixes/Closes/Resolves-anchored
            # match so an embedded reference like "Fixes #12: address #34" picks
            # the issue the PR actually fixes (not the first bare "#N"); fall
            # back to the first "#N" for keyword-less titles (e.g.
            # "feat(x): do thing (#123)") so cost is still attributed.
            issue_match = re.search(
                r"(?:Fixes|Closes|Resolves)\s+#(\d+)", pr_title or "", re.IGNORECASE
            ) or re.search(r"#(\d+)", pr_title or "")
            issue_no = int(issue_match.group(1)) if issue_match else None

            payload = MergeUpdatePayload(pr=pr_number, status="merged")
            if pr_title:
                payload["title"] = pr_title
            if issue_no is not None:
                payload["issue"] = issue_no
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.MERGE_UPDATE,
                    data=payload,
                )
            )
            # Per-issue cost-budget check (spec §4.11 Task 10). Runs only
            # when the merge actually succeeded. Errors here must not
            # affect the return value — a broken rollup read cannot turn
            # a real merge success into a failure. Inlined (rather than a
            # helper method) so the hook site is self-contained and
            # easy to reason about from merge_pr alone.
            try:
                if issue_no is not None:
                    from dedup_store import DedupStore  # noqa: PLC0415

                    pricing = load_pricing()
                    total = 0.0
                    for rec in iter_priced_inferences_for_issue(
                        self._config, issue=issue_no, pricing=pricing
                    ):
                        total += float(rec.get("cost_usd") or 0.0)
                    dedup = DedupStore(
                        "cost_issue_alerts",
                        self._config.data_root / "dedup" / "cost_issue_alerts.json",
                    )
                    await check_issue_cost(
                        self._config,
                        pr_manager=self,
                        dedup=dedup,
                        event_bus=self._bus,
                        issue_number=issue_no,
                        cost_usd=total,
                    )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Per-issue cost-alert hook failed for PR #%d",
                    pr_number,
                    exc_info=True,
                )
            return True
        return False

    async def _comment(
        self, target: Literal["issue", "pr"], number: int, body: str
    ) -> None:
        """Post a comment on a GitHub issue or PR."""
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would post comment on %s #%d", target, number)
            return
        chunk_limit = CommentFormatter.GITHUB_COMMENT_LIMIT - self._HEADER_RESERVE
        chunks = CommentFormatter.chunk(body, chunk_limit)
        for idx, chunk in enumerate(chunks):
            part = chunk
            if len(chunks) > 1:
                part = f"*Part {idx + 1}/{len(chunks)}*\n\n{chunk}"
            part = CommentFormatter.cap(part, CommentFormatter.GITHUB_COMMENT_LIMIT)
            try:
                await self._run_with_body_file(
                    "gh",
                    target,
                    "comment",
                    str(number),
                    "--repo",
                    self._repo,
                    body=part,
                    cwd=self._config.repo_root,
                )
            except RuntimeError as exc:
                logger.warning(
                    "Could not post comment on %s #%d: %s",
                    target,
                    number,
                    exc,
                )

    async def post_comment(self, issue_number: int, body: str) -> None:
        """Post a comment on a GitHub issue."""
        await self._comment("issue", issue_number, body)

    async def post_pr_comment(self, pr_number: int, body: str) -> None:
        """Post a comment on a GitHub pull request."""
        await self._comment("pr", pr_number, body)

    async def list_issue_comments(self, issue_number: int) -> list[dict[str, Any]]:
        """List comments on a GitHub issue (oldest first; max 100).

        Normalises ``gh issue view --json comments`` (which yields GraphQL-shaped
        ``author.login`` / ``createdAt``) into the stable port contract: dicts
        with ``user.login``, ``body`` and ``created_at`` keys.
        """
        self._assert_repo()
        try:
            output = await self._run_gh(
                "gh",
                "issue",
                "view",
                str(issue_number),
                "--json",
                "comments",
            )
        except Exception as exc:
            logger.warning(
                "Failed to list comments for issue #%d: %s", issue_number, exc
            )
            return []
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            logger.warning("Bad comments JSON for issue #%d: %s", issue_number, exc)
            return []
        comments = payload.get("comments") or []
        return [_normalise_issue_comment(c) for c in comments if isinstance(c, dict)]

    async def submit_review(
        self, pr_number: int, verdict: ReviewVerdict, body: str
    ) -> bool:
        """Submit a formal GitHub PR review.

        *verdict* is a :class:`ReviewVerdict` enum member.
        Returns *True* on success.
        """
        flag_map = {
            ReviewVerdict.APPROVE: "--approve",
            ReviewVerdict.REQUEST_CHANGES: "--request-changes",
            ReviewVerdict.COMMENT: "--comment",
        }
        flag = flag_map[verdict]
        self._assert_repo()

        if self._config.dry_run:
            logger.info(
                "[dry-run] Would submit %s review on PR #%d",
                verdict.value,
                pr_number,
            )
            return True

        body = CommentFormatter.cap(body, CommentFormatter.GITHUB_COMMENT_LIMIT)
        try:
            await self._run_with_body_file(
                "gh",
                "pr",
                "review",
                str(pr_number),
                "--repo",
                self._repo,
                flag,
                body=body,
                cwd=self._config.repo_root,
            )
            return True
        except RuntimeError as exc:
            err_msg = str(exc)
            err_lower = err_msg.lower()
            # GitHub rejects a bot approving/requesting-changes on its own PR.
            # Match the STABLE core phrase only — the prefix flips between
            # "cannot" and "can not" across API surfaces (the live GraphQL error
            # is "Review Can not approve your own pull request"), and matching
            # the exact spacing leaked a scary WARNING + return False instead of
            # the intended graceful self-review fallback (merge still proceeds on
            # green; no approval is required on staging).
            if (
                "request changes on your own pull request" in err_lower
                or "approve your own pull request" in err_lower
            ):
                logger.info(
                    "Cannot submit %s review on own PR #%d — falling back to comment",
                    verdict.value,
                    pr_number,
                )
                raise SelfReviewError(err_msg) from exc
            logger.warning(
                "Could not submit %s review on PR #%d: %s",
                verdict.value,
                pr_number,
                exc,
            )
            return False

    async def _add_labels(
        self, target: Literal["issue", "pr"], number: int, labels: list[str]
    ) -> None:
        """Add *labels* to a GitHub issue or PR."""
        self._assert_repo()
        if self._config.dry_run or not labels:
            return
        for label in labels:
            try:
                await self._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._repo}/issues/{number}/labels",
                    "-X",
                    "POST",
                    "--raw-field",
                    f"labels[]={label}",
                )
            except RuntimeError as exc:
                logger.warning(
                    "Could not add label %r to %s #%d: %s",
                    label,
                    target,
                    number,
                    exc,
                )

    async def _add_labels_strict(
        self, target: Literal["issue", "pr"], number: int, labels: list[str]
    ) -> None:
        """Add *labels* to a GitHub issue or PR — raises on failure.

        Unlike :meth:`_add_labels` this does **not** swallow errors, so
        callers (e.g. :meth:`swap_pipeline_labels`) can abort before
        removing old labels.
        """
        self._assert_repo()
        if self._config.dry_run or not labels:
            return
        for label in labels:
            try:
                await self._run_gh(
                    "gh",
                    "api",
                    f"repos/{self._repo}/issues/{number}/labels",
                    "-X",
                    "POST",
                    "--raw-field",
                    f"labels[]={label}",
                )
            except RuntimeError:
                logger.warning(
                    "Failed to add label %r to %s #%d during swap — "
                    "aborting to prevent orphan",
                    label,
                    target,
                    number,
                )
                raise

    async def add_labels(self, issue_number: int, labels: list[str]) -> None:
        """Add *labels* to a GitHub issue."""
        await self._add_labels("issue", issue_number, labels)

    async def _remove_label(
        self, target: Literal["issue", "pr"], number: int, label: str
    ) -> None:
        """Remove *label* from a GitHub issue or PR."""
        self._assert_repo()
        if self._config.dry_run:
            return
        try:
            encoded_label = quote(label, safe="")
            await self._run_gh(
                "gh",
                "api",
                f"repos/{self._repo}/issues/{number}/labels/{encoded_label}",
                "-X",
                "DELETE",
            )
        except RuntimeError as exc:
            if _is_missing_label_404(exc):
                logger.debug(
                    "Label %r not present on %s #%d; skipping remove",
                    label,
                    target,
                    number,
                )
                return
            logger.warning(
                "Could not remove label %r from %s #%d: %s",
                label,
                target,
                number,
                exc,
            )

    async def remove_label(self, issue_number: int, label: str) -> None:
        """Remove *label* from a GitHub issue."""
        await self._remove_label("issue", issue_number, label)

    async def get_issue_state(self, issue_number: int) -> str:
        """Return the resolved state of a GitHub issue.

        Returns ``'COMPLETED'`` when the issue was closed as resolved,
        ``'OPEN'`` when still open, ``'NOT_PLANNED'`` when closed as
        won't-fix/duplicate/invalid, or ``''`` on error.
        """
        self._assert_repo()
        try:
            output = await self._run_gh(
                "gh",
                "issue",
                "view",
                str(issue_number),
                "--repo",
                self._repo,
                "--json",
                "state,stateReason",
            )
            data = json.loads(output)
            state = str(data.get("state", "")).upper()
            if state == "CLOSED":
                # stateReason: "COMPLETED" | "NOT_PLANNED" | null
                # Fall back to "" (not "COMPLETED") when stateReason is null so
                # that issues closed before GitHub added stateReason tracking are
                # not incorrectly treated as resolved.
                reason = str(data.get("stateReason") or "").upper()
                return reason
            return state
        except Exception:
            logger.warning(
                "Could not fetch state of issue #%d",
                issue_number,
                exc_info=True,
            )
            return "UNKNOWN"

    async def list_issues_by_label(self, label: str) -> list[GitHubIssueSummary]:
        """Return open issues with the given label as a list of dicts.

        #8786 Phase 8: parses through ``contracts.boundary.parse_list_with_shape``
        in *lenient* mode — validation failures log WARN but the method's
        return type and behaviour are unchanged. Existing callers that
        access ``item["number"]`` etc keep working; shape drift is
        observable in ``server.log`` and via ``LiveCorpusReplayLoop``.
        """
        # Local import keeps the module-load contract identical when
        # the contracts subsystem isn't imported elsewhere yet.
        from contracts.boundary import parse_list_with_shape  # noqa: PLC0415
        from contracts.shapes import GhIssueListItem  # noqa: PLC0415

        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "list",
            "--repo",
            self._repo,
            "--label",
            label,
            "--state",
            "open",
            "--json",
            "number,title,body,updatedAt,labels",
            "--limit",
            "100",
        )
        results = parse_list_with_shape(output or "[]", GhIssueListItem)
        return _project_issue_summaries(results)

    async def list_open_issues(self) -> list[GitHubIssueSummary]:
        """Return ALL open issues (no label filter) as a list of dicts.

        Used by the backlog refinement loop (``IssueRefinementLoop``, #9957) for a
        full-repo sweep. Same contracts-boundary lenient-parse pattern as
        ``list_issues_by_label`` — labels ride along in gh wire shape
        (#9943) since refinement needs to reason about existing labels.
        """
        from contracts.boundary import parse_list_with_shape
        from contracts.shapes import GhIssueListItem

        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "list",
            "--repo",
            self._repo,
            "--state",
            "open",
            "--json",
            "number,title,body,labels,updatedAt",
            "--limit",
            "500",
        )
        results = parse_list_with_shape(output or "[]", GhIssueListItem)
        summaries = _project_issue_summaries(results)
        if len(summaries) == 500:
            logger.warning(
                "list_open_issues returned exactly 500 rows — backlog may be"
                " truncated; raise the limit"
            )
        return summaries

    async def list_open_issue_numbers(self, limit: int = 500) -> list[int]:
        """Return the numbers of ALL open issues (no label filter). #9905.

        Narrow ``--json number`` projection: number is the only field the
        state-prune keep-set needs, and narrow projections skip the
        required-fields shape gate by design.
        """
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "list",
            "--repo",
            self._repo,
            "--state",
            "open",
            "--json",
            "number",
            "--limit",
            str(limit),
        )
        try:
            rows = json.loads(output or "[]")
        except ValueError:
            logger.warning("list_open_issue_numbers: unparseable gh output")
            return []
        numbers: list[int] = []
        for row in rows if isinstance(rows, list) else []:
            number = row.get("number") if isinstance(row, dict) else None
            if isinstance(number, int) and number > 0:
                numbers.append(number)
        return numbers

    async def list_workflow_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent workflow runs, newest first (#9974, read-only).

        Uses the REST runs endpoint (not ``gh run list``) because the run
        object carries ``pull_requests`` — the PR association that
        blame-correlation needs.
        """
        self._assert_repo()
        per_page = max(1, min(int(limit), 100))
        output = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/actions/runs?per_page={per_page}",
            "--jq",
            (
                "[.workflow_runs[] | {id: .id, workflow: .name, "
                'conclusion: (.conclusion // ""), created_at: .created_at, '
                "pr_number: (.pull_requests[0].number // 0)}]"
            ),
        )
        try:
            rows = json.loads(output or "[]")
        except ValueError:
            logger.warning("list_workflow_runs: unparseable gh output")
            return []
        return (
            [row for row in rows if isinstance(row, dict)]
            if isinstance(rows, list)
            else []
        )

    async def list_runs_for_workflow(
        self, workflow: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return recent runs of ONE workflow file, newest first (#9814).

        Uses the workflow-scoped REST runs endpoint so a single fetch
        covers the RC-history consumers' windows without pulling every
        workflow's runs. ``run_started_at`` falls back to ``created_at``
        for runs that never started (rc_budget's duration math needs a
        timestamp either way).
        """
        self._assert_repo()
        per_page = max(1, min(int(limit), 100))
        output = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/actions/workflows/{workflow}/runs?per_page={per_page}",
            "--jq",
            (
                '[.workflow_runs[] | {id: .id, url: (.html_url // ""), '
                'status: (.status // ""), conclusion: (.conclusion // ""), '
                'created_at: (.created_at // ""), '
                'run_started_at: (.run_started_at // .created_at // ""), '
                'updated_at: (.updated_at // "")}]'
            ),
        )
        try:
            rows = json.loads(output or "[]")
        except ValueError:
            logger.warning("list_runs_for_workflow: unparseable gh output")
            return []
        return (
            [row for row in rows if isinstance(row, dict)]
            if isinstance(rows, list)
            else []
        )

    async def get_workflow_run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        """Return jobs for one workflow run (#9974, enriched #10010, #10027).

        Each dict: ``{"name", "status", "conclusion", "started_at",
        "completed_at", "steps"}``. ``started_at``/``completed_at``/``steps``
        feed GateHealthLoop's suspected-hang classifier (duration vs. the
        workflow's configured timeout-minutes, plus whether a test step
        ever reached a terminal conclusion) — the jobs API is the only
        source for a job's *actual* timing and step-level outcomes.

        ``status`` (queued / in_progress / completed, #10027) lets
        PrRedRepairLoop's settled-red predicate tell a genuinely finished
        job apart from one mid-rerun whose ``conclusion`` still reads its
        OLD (pre-rerun) value while ``status`` has already flipped back to
        pending — additive field, existing consumers ignore it.
        """
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/actions/runs/{int(run_id)}/jobs?per_page=100",
            "--jq",
            (
                '[.jobs[] | {name: .name, status: (.status // ""), '
                'conclusion: (.conclusion // ""), '
                'started_at: (.started_at // ""), '
                'completed_at: (.completed_at // ""), '
                "steps: [.steps[]? | {name: .name, "
                'conclusion: (.conclusion // "")}]}]'
            ),
        )
        try:
            rows = json.loads(output or "[]")
        except ValueError:
            logger.warning("get_workflow_run_jobs: unparseable gh output")
            return []
        return (
            [row for row in rows if isinstance(row, dict)]
            if isinstance(rows, list)
            else []
        )

    async def count_workflow_run_artifacts(self, run_id: int) -> int:
        """Return how many artifacts a workflow run uploaded (#9974)."""
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/actions/runs/{int(run_id)}/artifacts",
            "--jq",
            ".total_count",
        )
        try:
            return int((output or "0").strip())
        except ValueError:
            return 0

    async def rerun_workflow_failed(self, run_id: int) -> bool:
        """Trigger ``gh run rerun <id> --failed`` (#10027 bounded infra-flake retry).

        Reruns only the FAILED jobs within *run_id* — the same run id
        persists, which is why the caller's attempt cap is keyed by PR
        number rather than expecting a fresh run id per retry. Returns
        ``True`` on success, ``False`` on any ``gh`` failure (never
        raises) so the caller's attempt-cap bookkeeping stays authoritative
        regardless of transient gh/API errors.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would rerun failed jobs for run %d", run_id)
            return False
        self._assert_repo()
        try:
            await self._run_gh(
                "gh",
                "run",
                "rerun",
                str(run_id),
                "--repo",
                self._repo,
                "--failed",
            )
        except RuntimeError:
            logger.warning(
                "rerun_workflow_failed: gh run rerun failed for run %d",
                run_id,
                exc_info=True,
            )
            return False
        return True

    async def list_closed_issues_by_label(
        self, label: str, limit: int = 100
    ) -> list[GitHubIssueSummary]:
        """Return closed issues with the given label as a list of dicts.

        #8786 Phase 10: routed through the contracts boundary helper in
        lenient mode — same pattern as ``list_issues_by_label``.

        #9727: projects ``closedAt`` → ``closed_at`` so the
        detector-calibration churn window can key on close time
        (``updated_at`` moves on ANY issue activity).

        #8996: also projects ``labels`` in gh wire shape — the closed
        listing used to be label-free by default (#9943), which meant
        ``escalation_reconcile.is_bot_close`` could never see the bot-close
        marker on a closed row from this method and fell open to "treat as
        human" every time. Threading labels through here is what makes that
        predicate load-bearing rather than dead code.
        """
        from contracts.boundary import parse_list_with_shape  # noqa: PLC0415
        from contracts.shapes import GhIssueListItem  # noqa: PLC0415

        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "list",
            "--repo",
            self._repo,
            "--label",
            label,
            "--state",
            "closed",
            "--json",
            "number,title,body,updatedAt,closedAt,labels",
            "--limit",
            str(limit),
        )
        from contracts.boundary import field_or  # noqa: PLC0415

        results = parse_list_with_shape(output or "[]", GhIssueListItem)
        return [
            {
                "number": field_or(r, "number", 0),
                "title": field_or(r, "title", ""),
                "body": field_or(r, "body", ""),
                "updated_at": field_or(r, "updated_at", "", dict_key="updatedAt"),
                "closed_at": field_or(r, "closed_at", "", dict_key="closedAt"),
                "labels": _gh_wire_labels(r),
            }
            for r in results
        ]

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

    async def get_issue_updated_at(self, issue_number: int) -> str:
        """Return the updated_at timestamp for an issue as ISO string."""
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            self._repo,
            "--json",
            "updatedAt",
            "--jq",
            ".updatedAt",
        )
        return output.strip()

    async def get_issue_labels(self, issue_number: int) -> list[str]:
        """Return the label names carried by a GitHub issue.

        Delegates to ``gh issue view <n> --json labels --jq
        '.labels[].name'`` (newline-separated names). Read failures
        propagate rather than being swallowed so that
        ``WorkspaceGCLoop._issue_has_pipeline_label`` can fail-closed on
        error instead of GC'ing an issue whose labels were merely
        unreadable (#9575).
        """
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            self._repo,
            "--json",
            "labels",
            "--jq",
            ".labels[].name",
        )
        return [line.strip() for line in output.splitlines() if line.strip()]

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

    async def get_latest_ci_status(self) -> tuple[str, str]:
        """Return (conclusion, url) for the latest CI run on the main branch."""
        self._assert_repo()
        output = await self._run_gh(
            "gh",
            "run",
            "list",
            "--repo",
            self._repo,
            "--branch",
            self._config.main_branch,
            "--limit",
            "1",
            "--json",
            "conclusion,url",
            "--jq",
            ".[0] | [.conclusion, .url] | @tsv",
        )
        parts = output.strip().split("\t")
        conclusion = parts[0] if parts else ""
        url = parts[1] if len(parts) > 1 else ""
        return (conclusion, url)

    async def close_issue(
        self, issue_number: int, *, reason: str | None = None
    ) -> bool:
        """Close a GitHub issue. Returns False when the gh call failed (#9812).

        *reason* maps to ``gh issue close --reason`` (``"completed"`` |
        ``"not planned"``); ``None`` omits the flag, so gh records its
        default ``stateReason=COMPLETED`` (#10025).
        """
        self._assert_repo()
        if self._config.dry_run:
            return True
        reason_args = ("--reason", reason) if reason else ()
        try:
            await self._run_gh(
                "gh",
                "issue",
                "close",
                str(issue_number),
                "--repo",
                self._repo,
                *reason_args,
            )
        except RuntimeError as exc:
            logger.warning(
                "Could not close issue #%d: %s",
                issue_number,
                exc,
            )
            return False
        # Choke point (#10394): a closed issue must never keep an active
        # pipeline-stage label, or a label-scan dispatcher will re-queue
        # already-shipped work. Strip them here so every HydraFlow-initiated
        # close is clean. (GitHub-native ``Closes #N`` auto-closes bypass this
        # method entirely — the LabelDriftWatcherLoop, ADR-0088, is the
        # backstop for those.)
        await self._strip_dispatch_labels(issue_number)
        return True

    async def _strip_dispatch_labels(self, issue_number: int) -> None:
        """Remove any active pipeline-stage labels from *issue_number* (#10394).

        Best-effort: reads the issue's current labels once and removes only
        the intersection with ``dispatchable_stage_labels`` — terminal
        markers (``fixed`` / ``verify``) are preserved so the merge path's
        ``hydraflow-fixed`` end-state is unchanged. A label read/remove
        failure is logged, never raised, so it can never turn a successful
        close into a reported failure (the drift watcher will catch anything
        missed on a later tick).
        """
        dispatch_labels = set(self._config.dispatchable_stage_labels)
        if not dispatch_labels:
            return
        try:
            current = set(await self.get_issue_labels(issue_number))
        except RuntimeError as exc:
            logger.debug(
                "close_issue: could not read labels for #%d to strip stage labels: %s",
                issue_number,
                exc,
            )
            return
        for lbl in sorted(current & dispatch_labels):
            await self._remove_label("issue", issue_number, lbl)

    async def reopen_issue(self, issue_number: int) -> bool:
        """Reopen a closed GitHub issue. Returns False when the gh call failed.

        ``gh issue reopen``. Fail-soft (no raise), matching
        :meth:`close_issue` (#9812). Used by the close-verification controller
        (#10358) to undo a false auto-close.
        """
        self._assert_repo()
        if self._config.dry_run:
            return True
        try:
            await self._run_gh(
                "gh",
                "issue",
                "reopen",
                str(issue_number),
                "--repo",
                self._repo,
            )
        except RuntimeError as exc:
            logger.warning(
                "Could not reopen issue #%d: %s",
                issue_number,
                exc,
            )
            return False
        return True

    async def close_pr(self, pr_number: int) -> bool:
        """Close a GitHub pull request without merging it.

        ``gh pr close`` (not ``gh issue close`` — the latter resolves only
        the ``Issue`` GraphQL type and does not reliably close a PR number).
        """
        self._assert_repo()
        if self._config.dry_run:
            return True
        try:
            await self._run_gh(
                "gh",
                "pr",
                "close",
                str(pr_number),
                "--repo",
                self._repo,
            )
        except RuntimeError as exc:
            logger.warning(
                "Could not close PR #%d: %s",
                pr_number,
                exc,
            )
            return False
        return True

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        """Update the body of a GitHub issue using ``--body-file``."""
        self._assert_repo()
        if self._config.dry_run:
            return
        try:
            await self._run_with_body_file(
                "gh",
                "issue",
                "edit",
                str(issue_number),
                "--repo",
                self._repo,
                body=body,
            )
        except RuntimeError as exc:
            logger.warning(
                "Could not update body for issue #%d: %s",
                issue_number,
                exc,
            )

    async def create_tag(self, tag: str, *, ref: str = "HEAD") -> bool:
        """Create a git tag on the given *ref* and push it to origin.

        Returns *True* on success, *False* on failure.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would create tag %s on %s", tag, ref)
            return True
        try:
            await self._run_gh("git", "tag", tag, ref)
            await self._run_gh("git", "push", "origin", tag)
            return True
        except RuntimeError as exc:
            logger.warning("Could not create tag %s: %s", tag, exc)
            return False

    async def create_release(
        self,
        tag: str,
        title: str,
        body: str,
    ) -> bool:
        """Create a GitHub Release for the given *tag*.

        Returns *True* on success, *False* on failure.
        Uses a temp file for the notes body to avoid argument length limits.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would create release %s", tag)
            return True

        try:
            await self._run_with_body_file(
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                self._repo,
                "--title",
                title,
                body=body,
                file_flag="--notes-file",
            )
            return True
        except RuntimeError as exc:
            logger.warning("Could not create release %s: %s", tag, exc)
            return False

    async def remove_pr_label(self, pr_number: int, label: str) -> None:
        """Remove *label* from a GitHub pull request."""
        await self._remove_label("pr", pr_number, label)

    async def add_pr_labels(self, pr_number: int, labels: list[str]) -> None:
        """Add *labels* to a GitHub pull request."""
        await self._add_labels("pr", pr_number, labels)

    async def swap_pipeline_labels(
        self,
        issue_number: int,
        new_label: str,
        *,
        pr_number: int | None = None,
    ) -> None:
        """Swap to *new_label*, removing all other pipeline labels.

        Adds the new label **first** so the issue is never left without a
        pipeline label.  If the add fails the old labels remain intact and
        the exception propagates — callers can retry or escalate.
        """
        self._assert_repo()
        # --- add new label first (raises on failure) ---
        await self._add_labels_strict("issue", issue_number, [new_label])
        if pr_number is not None:
            await self._add_labels_strict("pr", pr_number, [new_label])

        # The swap is now real on GitHub (add-first defines the new stage) —
        # push it to the in-memory pipeline BEFORE the best-effort removal
        # fan-out so the dashboard card moves in seconds (#9842).
        self._notify_pipeline_label_listener(issue_number, new_label)

        # --- then remove stale labels (best-effort) ---
        all_labels = self._config.all_pipeline_labels
        for lbl in all_labels:
            if lbl != new_label:
                await self._remove_label("issue", issue_number, lbl)
                if pr_number is not None:
                    await self._remove_label("pr", pr_number, lbl)

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

    async def find_label_drift(self) -> list[LabelDrift]:
        """Scan open PRs for cross-entity label drift vs their linked issues.

        Returns a list of :class:`LabelDrift` records, one per drifted pair.
        See ADR-0088 for the drift kinds and reconciliation policy.

        Each tick: fetch open PRs (any state), parse ``Fixes #N`` from the
        body, fetch the linked issue's labels, then classify the pair.
        """
        raw = await self._gh_json_query(
            "gh",
            "pr",
            "list",
            "--repo",
            self._repo,
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,labels,body,isDraft",
            dry_run_return=[],
            error_log="find_label_drift: pr list failed",
        )
        if not isinstance(raw, list):
            return []

        out: list[LabelDrift] = []
        pre_pr_labels = {"hydraflow-ready", "hydraflow-plan", "hydraflow-find"}
        post_pr_labels = {"hydraflow-fixed", "hydraflow-hitl"}
        fixes_re = re.compile(r"(?:fixes|closes|resolves)\s+#(\d+)", re.IGNORECASE)

        for pr in raw:
            if not isinstance(pr, dict):
                continue
            try:
                pr_n = int(pr.get("number", 0))
            except (TypeError, ValueError):
                continue
            if pr_n <= 0:
                continue
            pr_labels = {
                lbl.get("name", "")
                for lbl in (pr.get("labels") or [])
                if isinstance(lbl, dict)
            }
            # The in-progress claim marker (#10168) is not a pipeline stage —
            # exclude it so a ready+in-progress issue reads as ``hydraflow-ready``
            # rather than being mistaken for a stage and mis-classified as drift.
            claim_labels = set(self._config.in_progress_label)
            pr_pipeline = next(
                (
                    lbl
                    for lbl in pr_labels
                    if lbl.startswith("hydraflow-") and lbl not in claim_labels
                ),
                "",
            )
            body = pr.get("body") or ""
            matched_issue_ns = list(
                dict.fromkeys(int(m.group(1)) for m in fixes_re.finditer(body))
            )
            if not matched_issue_ns:
                continue
            issue_n = matched_issue_ns[0]

            # Commit count is fetched per-PR (only for Fixes-matched PRs, which
            # already trigger an issue fetch below) — requesting `commits` in the
            # bulk `pr list` expands each commit's authors connection and blows
            # past GitHub's GraphQL 500k-node ceiling at --limit 200.
            commits = await self._pr_commit_count(pr_n)

            issue_labels_raw = await self._gh_json_query(
                "gh",
                "issue",
                "view",
                str(issue_n),
                "--repo",
                self._repo,
                "--json",
                "labels",
                dry_run_return={"labels": []},
                error_log=f"find_label_drift: issue {issue_n} fetch failed",
            )
            if not isinstance(issue_labels_raw, dict):
                continue
            issue_labels = {
                lbl.get("name", "")
                for lbl in (issue_labels_raw.get("labels") or [])
                if isinstance(lbl, dict)
            }
            issue_pipeline = next(
                (
                    lbl
                    for lbl in issue_labels
                    if lbl.startswith("hydraflow-") and lbl not in claim_labels
                ),
                "",
            )

            # More specific — checked first (#10260): a resolved-but-stale
            # escalation label outranks the pipeline-stage drift kinds below.
            # Requires BOTH labels, not just `hitl-escalation`: diagnostic_loop
            # is the only lineage that pairs them, and it always swaps the
            # issue to `hydraflow-hitl` first — so clearing still leaves a
            # durable queue label behind. Other loops (corpus_learning_loop,
            # trust_fleet_sanity_loop, wiki_rot_detector_loop, etc.) file bare
            # `hitl-escalation` + their own `-stuck` label with NO pipeline
            # label; clearing `hitl-escalation` for those would orphan the
            # issue with no re-escalation path, since those loops don't
            # re-file until the operator closes it. Draft PRs are excluded —
            # a not-ready-for-review PR isn't a reliable resolved signal even
            # with green CI (mirrors find_open_resolving_pr's draft check).
            # A body can link more than one issue (e.g. an epic PR) — the
            # escalated issue may not be the first Fixes/Closes/Resolves
            # match, so every matched issue is a candidate, not just the
            # primary one already fetched above (#10260 review; mirrors
            # find_open_resolving_pr's finditer scan).
            escalation_issue_n = issue_n
            escalation_labels = issue_labels
            if not ({"hitl-escalation", "diagnose-failed"} <= escalation_labels):
                for candidate_n in matched_issue_ns[1:]:
                    candidate_raw = await self._gh_json_query(
                        "gh",
                        "issue",
                        "view",
                        str(candidate_n),
                        "--repo",
                        self._repo,
                        "--json",
                        "labels",
                        dry_run_return={"labels": []},
                        error_log=(
                            f"find_label_drift: issue {candidate_n} fetch failed"
                        ),
                    )
                    if not isinstance(candidate_raw, dict):
                        continue
                    candidate_labels = {
                        lbl.get("name", "")
                        for lbl in (candidate_raw.get("labels") or [])
                        if isinstance(lbl, dict)
                    }
                    if {"hitl-escalation", "diagnose-failed"} <= candidate_labels:
                        escalation_issue_n = candidate_n
                        escalation_labels = candidate_labels
                        break

            escalations = escalation_labels & {"hitl-escalation", "diagnose-failed"}
            kind: str | None = None
            issue_label = issue_pipeline
            if {
                "hitl-escalation",
                "diagnose-failed",
            } <= escalation_labels and not pr.get("isDraft"):
                checks = await self.get_pr_checks(pr_n)
                if checks and all(
                    c.get("state", "").upper() in self._PASSING_STATES for c in checks
                ):
                    kind = "escalated_with_resolving_pr"
                    issue_label = ",".join(sorted(escalations))

            if kind is None:
                if (
                    issue_pipeline in pre_pr_labels
                    and pr_pipeline == "hydraflow-review"
                    and commits > 0
                ):
                    kind = "pr_ahead_of_issue"
                elif pr_pipeline in pre_pr_labels and commits > 0:
                    kind = "pr_at_pre_pr_stage"
                elif pr_pipeline in post_pr_labels and issue_pipeline in pre_pr_labels:
                    kind = "pr_ahead_of_issue"

            if kind is None:
                continue
            out.append(
                LabelDrift(
                    issue=(
                        escalation_issue_n
                        if kind == "escalated_with_resolving_pr"
                        else issue_n
                    ),
                    pr=pr_n,
                    pr_commits=commits,
                    issue_label=issue_label,
                    pr_label=pr_pipeline,
                    kind=kind,  # type: ignore[arg-type]
                    detected_at=datetime.now(UTC),
                )
            )
        return out

    async def find_closed_stage_labeled_issues(
        self,
    ) -> list[ClosedStageLabelDrift]:
        """Return CLOSED issues that still carry an active pipeline-stage label.

        Belt-and-suspenders for #10394: a GitHub-native ``Closes #N``
        auto-close (or any close path that bypassed
        :meth:`close_issue`'s label strip) can leave a closed issue tagged
        ``hydraflow-ready`` etc., which a label-scan dispatcher would
        re-queue as duplicate work. The ``LabelDriftWatcherLoop`` (ADR-0088)
        strips them. One search request keyed on the active stage labels
        (comma-joined = GitHub label OR), scoped to ``is:closed``.
        """
        self._assert_repo()
        stage_labels = self._config.dispatchable_stage_labels
        if not stage_labels:
            return []
        search = "is:closed label:" + ",".join(stage_labels)
        raw = await self._gh_json_query(
            "gh",
            "issue",
            "list",
            "--repo",
            self._repo,
            "--state",
            "closed",
            "--search",
            search,
            "--limit",
            "200",
            "--json",
            "number,labels",
            dry_run_return=[],
            error_log="find_closed_stage_labeled_issues: issue list failed",
        )
        if not isinstance(raw, list):
            return []
        stage_set = set(stage_labels)
        out: list[ClosedStageLabelDrift] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                issue_n = int(item.get("number", 0))
            except (TypeError, ValueError):
                continue
            if issue_n <= 0:
                continue
            labels = {
                lbl.get("name", "")
                for lbl in (item.get("labels") or [])
                if isinstance(lbl, dict)
            }
            stale = sorted(labels & stage_set)
            if stale:
                out.append(ClosedStageLabelDrift(issue=issue_n, stale_labels=stale))
        return out

    async def find_open_resolving_pr(self, issue_number: int) -> int | None:
        """Return the number of an OPEN PR that resolves *issue_number*.

        Reuses the ``find_label_drift`` Fixes-regex scan, keyed by issue
        instead of by PR (#10260). Draft PRs are excluded — a PR the author
        marked not-ready-for-review is not a reliable signal that the issue
        is actually resolved, even with green CI.
        """
        raw = await self._gh_json_query(
            "gh",
            "pr",
            "list",
            "--repo",
            self._repo,
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,body,isDraft",
            dry_run_return=[],
            error_log=f"find_open_resolving_pr: pr list failed for issue #{issue_number}",
        )
        if not isinstance(raw, list):
            return None

        fixes_re = re.compile(r"(?:fixes|closes|resolves)\s+#(\d+)", re.IGNORECASE)
        for pr in raw:
            if not isinstance(pr, dict):
                continue
            if pr.get("isDraft"):
                continue
            body = pr.get("body") or ""
            # A body can carry more than one Fixes/Closes/Resolves link (e.g.
            # an epic PR resolving several issues) — check every match, not
            # just the first, so this issue's link isn't missed when it
            # isn't the leftmost one.
            if not any(
                int(m.group(1)) == issue_number for m in fixes_re.finditer(body)
            ):
                continue
            try:
                pr_n = int(pr.get("number", 0))
            except (TypeError, ValueError):
                continue
            if pr_n > 0:
                return pr_n
        return None

    async def get_dependabot_alerts(self, state: str = "open") -> list[dict]:
        """Fetch Dependabot alerts for the repository.

        Returns a list of alert dicts from the GitHub API, or an empty list
        on error or in dry-run mode.
        """
        return await self._gh_json_query(
            "gh",
            "api",
            f"repos/{self._repo}/dependabot/alerts?state={state}&per_page=100",
            "--paginate",
            dry_run_return=[],
            dry_run_log="[dry-run] Would fetch Dependabot alerts",
            error_log="Failed to fetch Dependabot alerts",
        )

    async def find_existing_issue(self, title: str) -> int:
        """Search for an open issue with an exact title match.

        Returns the issue number of the first match, or 0 if none found.

        #8786 Phase 15: routed through the contracts boundary helper in
        lenient mode against ``GhIssueListItem``. The ``--json number,title``
        shape is a strict subset; drift in either field surfaces via WARN
        without changing the method's return semantics.
        """
        self._assert_repo()
        if self._config.dry_run:
            return 0
        try:
            raw = await self._run_gh(
                "gh",
                "search",
                "issues",
                "--repo",
                self._repo,
                "--state",
                "open",
                "--match",
                "title",
                "--json",
                "number,title",
                "--limit",
                "5",
                "--",
                title,
                cwd=self._config.repo_root,
            )
            if not raw.strip():
                return 0
            from contracts.boundary import (  # noqa: PLC0415
                field_or,
                parse_list_with_shape,
            )
            from contracts.shapes import GhIssueListItem  # noqa: PLC0415

            results = parse_list_with_shape(raw, GhIssueListItem)
            for r in results:
                if field_or(r, "title", "") == title:
                    return int(field_or(r, "number", 0))
            return 0
        except (RuntimeError, ValueError):
            return 0

    @port_span("hf.port.pr.ensure_labels_present")
    async def _ensure_labels_present(self, labels: list[str]) -> None:
        """Create any of *labels* the repo doesn't already have.

        ``gh issue/pr create --label X`` (and ``--add-label X``) abort the
        WHOLE operation when X doesn't exist, so a caller that files with a
        not-yet-provisioned label silently fails — e.g. the ``health_monitor``
        loop-stall dead-man-switch files with ``loop-stalled``, which
        :meth:`ensure_labels_exist` does not create at boot (it only creates
        the fixed lifecycle set). Provisioning missing labels first means
        labeling never fails on an unknown label.

        Idempotent and non-mutating: labels that already exist are left
        untouched (no colour/description reset). Best-effort — a failure to
        list or create degrades to the pre-existing behaviour rather than
        blocking the caller.
        """
        if self._config.dry_run or not labels:
            return
        try:
            listed = await self._run_gh(
                "gh",
                "label",
                "list",
                "--repo",
                self._repo,
                "--limit",
                "500",
                "--json",
                "name",
                "-q",
                ".[].name",
            )
        except RuntimeError as exc:
            logger.warning("Could not list labels to ensure existence: %s", exc)
            return
        existing = {n.strip().lower() for n in listed.splitlines() if n.strip()}
        for label in labels:
            if label.lower() in existing:
                continue
            try:
                await self._run_gh("gh", "label", "create", label, "--repo", self._repo)
                existing.add(label.lower())
                logger.info("Provisioned missing label %r before use", label)
            except RuntimeError as exc:
                logger.warning("Could not provision label %r: %s", label, exc)

    @port_span("hf.port.pr.create_issue")
    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> int:
        """Create a new GitHub issue. Returns the issue number (0 on failure).

        Callers MUST check for ``0`` before storing or referencing the
        returned value.  Treating ``0`` as a real issue number causes
        downstream ``gh issue comment 0`` / ``gh issue close 0`` calls
        to fail with "Could not resolve to an issue or pull request with
        the number of 0" every cycle.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would create issue: %s", title)
            return 0

        existing = await self.find_existing_issue(title)
        if existing:
            logger.info(
                "Skipping duplicate issue creation — #%d already open with title %r",
                existing,
                title,
            )
            return existing

        # Provision any not-yet-existing label so `gh issue create --label X`
        # can't abort on it (e.g. the health_monitor escalation's loop-stalled).
        await self._ensure_labels_present(labels or [])

        cmd = [
            "gh",
            "issue",
            "create",
            "--repo",
            self._repo,
            "--title",
            title,
        ]
        for label in labels or []:
            cmd.extend(["--label", label])

        try:
            output = await self._run_with_body_file(
                *cmd, body=body, cwd=self._config.repo_root
            )
            # gh issue create prints the issue URL — validate before parsing
            url = output.strip()
            if "/issues/" not in url:
                raise RuntimeError(
                    f"Unexpected gh issue create output (expected issue URL): {url[:200]}"
                )
            issue_number = int(url.rstrip("/").split("/")[-1])

            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.ISSUE_CREATED,
                    data=IssueCreatedPayload(
                        number=issue_number,
                        title=title,
                        labels=labels or [],
                    ),
                )
            )
            return issue_number
        except (RuntimeError, ValueError) as exc:
            logger.warning("Issue creation failed for %r: %s", title, exc)
            return 0

    _SCREENSHOT_RELEASE_TAG = "screenshots"

    async def upload_screenshot(self, png_path: Path) -> str:
        """Upload a local PNG to GitHub as a release asset and return the URL.

        Uses a dedicated ``screenshots`` release tag.  The release is
        created automatically on first use.  Each file is uploaded with
        a unique name (timestamp + original stem) so assets never collide.

        Returns an empty string on failure or in dry-run mode.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would upload screenshot")
            return ""

        self._assert_repo()

        try:
            await self._ensure_screenshot_release()

            # Unique asset name to avoid collisions (gh uses the filename)
            import shutil
            import time as _time

            ts = int(_time.time())
            asset_name = f"{ts}-{png_path.stem}.png"
            upload_path = png_path.parent / asset_name
            shutil.copy2(png_path, upload_path)

            try:
                await self._run_gh(
                    "gh",
                    "release",
                    "upload",
                    self._SCREENSHOT_RELEASE_TAG,
                    str(upload_path),
                    "--repo",
                    self._repo,
                    "--clobber",
                )
            finally:
                upload_path.unlink(missing_ok=True)

            url = (
                f"https://github.com/{self._repo}/releases/download/"
                f"{self._SCREENSHOT_RELEASE_TAG}/{asset_name}"
            )
            logger.info("Screenshot uploaded: %s", url)
            return url
        except Exception:
            logger.warning("Screenshot upload failed", exc_info=True)
            return ""

    async def _ensure_screenshot_release(self) -> None:
        """Create the screenshots release if it doesn't exist."""
        try:
            await self._run_gh(
                "gh",
                "release",
                "view",
                self._SCREENSHOT_RELEASE_TAG,
                "--repo",
                self._repo,
            )
        except RuntimeError:
            # Release doesn't exist — create it
            await self._run_gh(
                "gh",
                "release",
                "create",
                self._SCREENSHOT_RELEASE_TAG,
                "--repo",
                self._repo,
                "--title",
                "Screenshot Assets",
                "--notes",
                "Auto-uploaded screenshots from bug reports",
                "--latest=false",
            )

    async def upload_screenshot_gist(self, png_base64: str) -> str:
        """Upload a base64-encoded PNG as a GitHub gist and return the raw URL.

        Returns an empty string on failure or in dry-run mode.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would upload screenshot gist")
            return ""

        # Strip optional data URI prefix
        if png_base64.startswith("data:"):
            _, _, png_base64 = png_base64.partition(",")

        try:
            png_bytes = base64.b64decode(png_base64, validate=True)
        except (ValueError, binascii.Error):
            logger.warning("Screenshot gist upload skipped: invalid base64 payload")
            return ""

        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="hydraflow-screenshot-")
        try:
            try:
                f = os.fdopen(fd, "wb")
            except OSError:
                os.close(fd)
                raise
            with f:
                f.write(png_bytes)

            gist_args = [
                "gh",
                "gist",
                "create",
            ]
            if self._config.screenshot_gist_public:
                gist_args.append("--public")
            gist_args += ["--filename", "screenshot.png", tmp_path]

            output = await self._run_gh(*gist_args)
            return self._gist_raw_url(output, "screenshot.png")
        except Exception:
            logger.warning("Screenshot gist upload failed", exc_info=True)
            return ""
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @staticmethod
    def _gist_raw_url(gist_output: str, filename: str) -> str:
        """Convert ``gh gist create`` output to a raw gist URL for *filename*."""
        gist_url = gist_output.strip()
        if "gist.github.com" not in gist_url:
            logger.warning("Unexpected gist create output: %s", gist_url[:200])
            return ""
        return (
            gist_url.replace("gist.github.com", "gist.githubusercontent.com")
            + f"/raw/{filename}"
        )

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

    # --- CI check methods ---

    async def get_pr_checks(self, pr_number: int) -> list[dict[str, str]]:
        """Fetch CI check results for *pr_number*.

        Returns a list of dicts with ``name`` and ``state`` keys.
        Returns an empty list on failure or in dry-run mode.
        """
        return await self._gh_json_query(
            "gh",
            "pr",
            "checks",
            str(pr_number),
            "--repo",
            self._repo,
            "--json",
            "name,state",
            dry_run_return=[],
            dry_run_log=f"[dry-run] Would fetch CI checks for PR #{pr_number}",
            error_log=f"Could not fetch CI checks for PR #{pr_number}",
        )

    _RUN_ID_PATTERN = re.compile(r"/actions/runs/(\d+)")

    async def _get_failed_check_runs(self, pr_number: int) -> list[tuple[str, str]]:
        """Return [(name, run_id), ...] for failed CI checks on this PR.

        #8786 Phase 13: routed through the contracts boundary helper in
        lenient mode against ``GhCheckRun``. The helper logs WARN on
        shape drift (e.g. a new check state enum value, a renamed URL
        field) and falls back to the raw dict so the existing downstream
        processing keeps working.

        #10510: the ``gh pr checks --json`` URL field is ``link`` — the
        older ``detailsUrl`` name was removed and requesting it makes the
        whole call fail (``Unknown JSON field: "detailsUrl"``), so every
        poll 3x-retried and returned no failed runs.
        """
        from contracts.boundary import field_or, parse_list_with_shape  # noqa: PLC0415
        from contracts.shapes import GhCheckRun  # noqa: PLC0415

        raw = await self._run_gh(
            "gh",
            "pr",
            "checks",
            str(pr_number),
            "--repo",
            self._repo,
            "--json",
            "name,state,link",
        )
        results = parse_list_with_shape(raw, GhCheckRun)

        seen_run_ids: set[str] = set()
        failed_names: list[tuple[str, str]] = []
        for r in results:
            name = str(field_or(r, "name", "unknown"))
            state = str(field_or(r, "state", "")).upper()
            details_url = str(field_or(r, "details_url", "", dict_key="link"))
            if state in self._PASSING_STATES or state in self._PENDING_STATES:
                continue
            if not details_url:
                continue
            match = self._RUN_ID_PATTERN.search(details_url)
            if not match:
                continue
            run_id = match.group(1)
            if run_id not in seen_run_ids:
                seen_run_ids.add(run_id)
                failed_names.append((name or "unknown", run_id))
        return failed_names

    async def _fetch_run_log(self, name: str, run_id: str) -> str:
        """Fetch the --log-failed output for one run, or '' on error."""
        try:
            log_output = await self._run_gh(
                "gh",
                "run",
                "view",
                run_id,
                "--repo",
                self._repo,
                "--log-failed",
            )
            if log_output.strip():
                return f"### {name} (run {run_id})\n\n{log_output}"
        except RuntimeError as exc:
            logger.debug("Could not fetch log for run %s: %s", run_id, exc)
        return ""

    async def fetch_ci_failure_logs(self, pr_number: int) -> str:
        """Fetch full CI failure logs for *pr_number*.

        Queries check runs, extracts run IDs from failed checks, and
        fetches their ``--log-failed`` output.  Returns the concatenated
        log text (one section per failed check) or an empty string on
        error or in dry-run mode.
        """
        if self._config.dry_run:
            return ""

        try:
            failed_runs = await self._get_failed_check_runs(pr_number)
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.warning("Could not fetch CI checks for PR #%d: %s", pr_number, exc)
            return ""

        if not failed_runs:
            return ""

        sections = [
            log
            for name, run_id in failed_runs
            if (log := await self._fetch_run_log(name, run_id))
        ]
        return "\n\n".join(sections)

    async def fetch_code_scanning_alerts(self, branch: str) -> list[CodeScanningAlert]:
        """Fetch open code scanning alerts for *branch*.

        Uses the GitHub code-scanning API via ``gh api``.  Returns a list
        of :class:`CodeScanningAlert` instances (projected to key fields)
        or ``[]`` on error, 404, or when the repository has no code
        scanning configured.
        """
        if self._config.dry_run:
            return []

        jq_expr = (
            "[.[] | {number, rule: .rule.description, "
            "severity: .rule.severity, "
            "security_severity: .rule.security_severity_level, "
            "path: .most_recent_instance.location.path, "
            "start_line: .most_recent_instance.location.start_line, "
            "message: .most_recent_instance.message.text}]"
        )
        try:
            stdout = await run_subprocess(
                "gh",
                "api",
                f"repos/{self._config.repo}/code-scanning/alerts",
                "--field",
                f"ref={branch}",
                "--field",
                "state=open",
                "--field",
                "per_page=50",
                "--jq",
                jq_expr,
                timeout=30,
            )
            raw = json.loads(stdout) if stdout.strip() else []
            return [CodeScanningAlert.model_validate(a) for a in raw]
        except (RuntimeError, json.JSONDecodeError, ValueError):
            logger.debug(
                "Could not fetch code scanning alerts for branch %s",
                branch,
                exc_info=True,
            )
            return []

    _PASSING_STATES = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})
    _PENDING_STATES = frozenset(
        {"PENDING", "QUEUED", "IN_PROGRESS", "REQUESTED", "WAITING"}
    )

    def _evaluate_ci_checks(
        self, checks: list[dict[str, Any]], pr_number: int
    ) -> tuple[bool, str] | None:
        """Evaluate completed CI checks.

        Returns ``(passed, message)`` if all checks have finished,
        or ``None`` if any check is still pending.
        """
        pending = [
            c for c in checks if c.get("state", "").upper() in self._PENDING_STATES
        ]
        if pending:
            return None

        failed = [
            c["name"]
            for c in checks
            if c.get("state", "").upper() not in self._PASSING_STATES
        ]
        if failed:
            return False, f"Failed checks: {', '.join(str(n) for n in failed)}"
        return True, f"All {len(checks)} checks passed"

    async def _advisory_failures_only(self, pr_number: int) -> bool:
        """Return True if only advisory (non-required) checks are non-passing.

        ``_evaluate_ci_checks`` counts *every* non-passing check as a failure,
        but a check that is not in the base branch's required-status-check set
        must not block the merge — GitHub already allows it. Rather than parse
        the base branch's ruleset (``main`` uses a ruleset, not classic branch
        protection), we consult GitHub's own verdict: when all *required*
        checks pass and only advisory checks fail, GitHub reports
        ``mergeable=MERGEABLE`` with ``mergeStateStatus=UNSTABLE``. Any other
        state — or an unreadable response — returns False (fail-closed) so a
        real required-check failure never merges by accident. See #9910.
        """
        if self._config.dry_run:
            return False
        try:
            raw = await self._run_gh(
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                self._repo,
                "--json",
                "mergeable,mergeStateStatus",
            )
        # Fail-closed: any probe error keeps the failure verdict.
        except Exception:
            logger.debug(
                "Could not fetch merge-state for PR #%d (advisory-check gate)",
                pr_number,
                exc_info=True,
            )
            return False
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return False
        mergeable = str(data.get("mergeable", "")).upper()
        merge_state = str(data.get("mergeStateStatus", "")).upper()
        return mergeable == "MERGEABLE" and merge_state in {
            "CLEAN",
            "UNSTABLE",
            "HAS_HOOKS",
        }

    async def wait_for_ci(
        self,
        pr_number: int,
        timeout: int,
        poll_interval: int,
        stop_event: asyncio.Event,
    ) -> tuple[bool, str]:
        """Poll CI checks until all complete or *timeout* seconds elapse.

        Returns ``(passed, summary_message)``.
        """
        if self._config.dry_run:
            logger.info("[dry-run] Would wait for CI on PR #%d", pr_number)
            return True, "Dry-run: CI skipped"

        elapsed = 0
        while elapsed < timeout:
            if stop_event.is_set():
                return False, ci_sentinels.CI_STOPPED

            checks = await self.get_pr_checks(pr_number)

            if not checks:
                # No checks registered yet. For freshly-opened PRs (e.g.
                # RC promotion PRs cut by StagingPromotionLoop), CI may
                # not have registered any checks in the rollup until a
                # few seconds after the PR opens. The legacy behavior
                # ("treat empty as success") raced with the merge
                # attempt: wait_for_ci would return True immediately,
                # the loop would attempt merge, and GitHub would reject
                # because required checks weren't satisfied. Fix: treat
                # empty as PENDING — keep polling until checks appear or
                # timeout. The caller's "timed out" / "ci_pending" path
                # retries on the next loop tick.
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                    return False, ci_sentinels.CI_STOPPED
                except TimeoutError:
                    elapsed += poll_interval
                    continue

            verdict = self._evaluate_ci_checks(checks, pr_number)
            if verdict is None:
                # Still pending — publish event and wait
                pending_count = sum(
                    1
                    for c in checks
                    if c.get("state", "").upper() in self._PENDING_STATES
                )
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.CI_CHECK,
                        data=CICheckPayload(
                            pr=pr_number,
                            status="pending",
                            pending=pending_count,
                            total=len(checks),
                        ),
                    )
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                    return False, ci_sentinels.CI_STOPPED
                except TimeoutError:
                    elapsed += poll_interval
                    continue

            passed, msg = verdict
            if not passed and await self._advisory_failures_only(pr_number):
                advisory = [
                    c["name"]
                    for c in checks
                    if c.get("state", "").upper() not in self._PASSING_STATES
                ]
                logger.info(
                    "PR #%d: all required checks satisfied; %d advisory "
                    "check(s) failing but non-blocking "
                    "(mergeStateStatus=UNSTABLE): %s",
                    pr_number,
                    len(advisory),
                    ", ".join(advisory),
                )
                passed, msg = (
                    True,
                    f"Required checks passed; advisory failing: {', '.join(advisory)}",
                )
            data: CICheckPayload = CICheckPayload(
                pr=pr_number,
                status="passed" if passed else "failed",
            )
            if not passed:
                # Extract failed names from the message for the event
                data["failed"] = [
                    c["name"]
                    for c in checks
                    if c.get("state", "").upper() not in self._PASSING_STATES
                ]
            else:
                data["total"] = len(checks)
            await self._bus.publish(HydraFlowEvent(type=EventType.CI_CHECK, data=data))
            return passed, msg

        return False, ci_sentinels.ci_timeout(timeout)

    async def refresh_pr_branch_with_arch_regen(
        self, pr_number: int, branch: str
    ) -> bool:
        """Self-heal a bot PR stuck red on stale ``docs/arch/generated/``.

        Merges ``origin/<base>`` into the PR head in an ephemeral worktree,
        re-runs ``arch.runner --emit`` to repair the staleness (or resolve an
        arch-generated-only merge conflict), commits, and pushes — re-triggering
        CI. Returns True only when a refresh commit was actually pushed; returns
        False for a clean no-op, a real (non-generated) conflict, or any git/gh
        failure, so the caller falls through to its ``failure_strategy``.

        Never force-pushes (the pre-push hook blocks it); a merge commit
        fast-forwards the remote head and squash-merge collapses it.
        """
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would arch-refresh bot PR #%d on branch %s",
                pr_number,
                branch,
            )
            return False

        from auto_pr import refresh_branch_with_arch_regen  # noqa: PLC0415

        result = await refresh_branch_with_arch_regen(
            repo_root=self._config.repo_root,
            branch=branch,
            base=self._config.base_branch(),
            gh_token=self._credentials.gh_token,
            worktree_parent=self._config.workspace_base,
            commit_author_name=self._config.git_user_name,
            commit_author_email=self._config.git_user_email,
        )
        if result.status == "refreshed":
            logger.info(
                "Arch-refreshed bot PR #%d (%s) — merged base + regenerated "
                "artifacts; CI will re-run",
                pr_number,
                branch,
            )
            return True
        logger.info(
            "Arch-refresh of bot PR #%d (%s) did not push (%s)%s",
            pr_number,
            branch,
            result.status,
            f": {result.error}" if result.error else "",
        )
        return False

    # --- PR activity query helpers ---

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

    # --- Changelog query helpers ---

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

    # --- dashboard query helpers ---

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

    # --- GitHub metrics helpers ---

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

    # --- body-file helpers ---

    # Backward-compatible aliases — delegates to CommentFormatter
    @staticmethod
    def _chunk_body(body: str, limit: int | None = None) -> list[str]:
        """Split *body* into chunks that fit within GitHub's comment limit."""
        return CommentFormatter.chunk(body, limit)

    @classmethod
    def _cap_body(cls, body: str, limit: int | None = None) -> str:
        """Hard-truncate *body* to *limit* characters."""
        return CommentFormatter.cap(body, limit)

    async def _run_with_body_file(
        self,
        *cmd: str,
        body: str,
        cwd: Path | None = None,
        file_flag: str = "--body-file",
    ) -> str:
        """Run a ``gh`` command using a temp file flag instead of inline body.

        Writes *body* to a temporary ``.md`` file, passes *file_flag*
        (default ``--body-file``) to the command, and cleans up afterwards.
        """
        fd, tmp_path = tempfile.mkstemp(suffix=".md", prefix="hydraflow-body-")
        try:
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
            except OSError:
                os.close(fd)
                raise
            with f:
                f.write(body)
            return await run_subprocess_with_retry(
                *cmd,
                file_flag,
                tmp_path,
                cwd=cwd or self._config.repo_root,
                gh_token=self._credentials.gh_token,
                max_retries=self._max_retries,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # TaskTransitioner protocol implementation
    # (transition, post_comment, close_task, create_task)
    # ------------------------------------------------------------------

    async def transition(
        self, issue_number: int, new_stage: str, *, pr_number: int | None = None
    ) -> None:
        """Implement :class:`task_source.TaskTransitioner` — swap pipeline labels."""
        _STAGE_LABEL = {
            "find": (self._config.find_label or ["hydraflow-find"])[0],
            "plan": (self._config.planner_label or ["hydraflow-plan"])[0],
            "ready": (self._config.ready_label or ["hydraflow-ready"])[0],
            "review": (self._config.review_label or ["hydraflow-review"])[0],
            "hitl": (self._config.hitl_label or ["hydraflow-hitl"])[0],
            "diagnose": (self._config.diagnose_label or ["hydraflow-diagnose"])[0],
        }
        label = _STAGE_LABEL.get(new_stage, new_stage)
        await self.swap_pipeline_labels(issue_number, label, pr_number=pr_number)

    async def close_task(self, issue_number: int) -> None:
        """Implement :class:`task_source.TaskTransitioner` — close the issue."""
        await self.close_issue(issue_number)

    async def create_task(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        """Implement :class:`task_source.TaskTransitioner` — create a new issue."""
        return await self.create_issue(title, body, labels)
