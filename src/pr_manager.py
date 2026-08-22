"""Pull request lifecycle management via the ``gh`` CLI."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar

from comment_formatter import CommentFormatter, SelfReviewError
from config import Credentials, HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from false_close import CLOSE_KEYWORD_RE
from label_transitions import pipeline_stage_labels
from models import (
    GitHubIssue,
    LabelCounts,
    MergeUpdatePayload,
    PRCreatedPayload,
    PRInfo,
    merge_diff_stats,
)
from pr_manager_artifacts import PRManagerArtifactsMixin
from pr_manager_branches import PRManagerBranchesMixin
from pr_manager_ci import PRManagerCIMixin
from pr_manager_comments import PRManagerCommentsMixin
from pr_manager_common import (
    _GIT_OID_RE,
    _LABEL_CACHE_TTL,
    _BranchPRRow,
    _gh_wire_labels,
    _is_missing_label_404,
    _normalise_issue_comment,
    _parse_branch_pr_row,
    _project_issue_summaries,
)
from pr_manager_dashboard import PRManagerDashboardMixin
from pr_manager_drift import PRManagerDriftMixin
from pr_manager_issues import PRManagerIssuesMixin
from pr_manager_labels import PRManagerLabelsMixin
from pr_manager_pr_queries import PRManagerPRQueriesMixin
from pr_manager_promotion import PRManagerPromotionMixin
from prep import HYDRAFLOW_LABELS, HYDRAFLOW_LITERAL_LABELS
from repro_manifest import append_manifest
from subprocess_util import run_subprocess, run_subprocess_with_retry
from traceability import append_req_trailer, extract_req_id

logger = logging.getLogger("hydraflow.pr_manager")
_JSONValue = TypeVar("_JSONValue")


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


# Re-exports for backward compatibility. Each mixin carries one cohesive
# GitHub surface extracted out of this module; PRManager inherits them all, so
# every previously-defined method — and every module-level helper other
# modules or tests import from here — remains reachable unchanged.
__all__ = [
    "CommentFormatter",
    "SelfReviewError",
    "PRManager",
    "PRManagerArtifactsMixin",
    "PRManagerBranchesMixin",
    "PRManagerCIMixin",
    "PRManagerCommentsMixin",
    "PRManagerDashboardMixin",
    "PRManagerDriftMixin",
    "PRManagerIssuesMixin",
    "PRManagerLabelsMixin",
    "PRManagerPRQueriesMixin",
    "PRManagerPromotionMixin",
    "_BranchPRRow",
    "_GIT_OID_RE",
    "_LABEL_CACHE_TTL",
    "_gh_wire_labels",
    "_is_missing_label_404",
    "_normalise_issue_comment",
    "_parse_branch_pr_row",
    "_project_issue_summaries",
]


class PRManager(
    PRManagerArtifactsMixin,
    PRManagerBranchesMixin,
    PRManagerCIMixin,
    PRManagerCommentsMixin,
    PRManagerDashboardMixin,
    PRManagerDriftMixin,
    PRManagerIssuesMixin,
    PRManagerLabelsMixin,
    PRManagerPRQueriesMixin,
    PRManagerPromotionMixin,
):
    """Pushes branches, creates PRs, merges, and manages labels.

    What stays here is the core: construction, the ``gh`` invocation
    primitives every surface shares (``_run_gh`` / ``_gh_json_query`` /
    ``_run_with_body_file``), the push → create → merge → close PR lifecycle,
    and the ``transition`` / ``create_task`` / ``close_task`` façade the
    pipeline drives.

    Each remaining GitHub surface was extracted to a sibling mixin module
    (god-class decomposition, Refs #11547 — same shape as the ADR-0042
    promotion slice from #10840): artifacts, branches, CI, comments,
    dashboard, drift, issues, labels, PR queries, promotion. They are part of
    this class via inheritance, so the public surface — and every
    ``patch("pr_manager.PRManager.<method>")`` target — is unchanged.
    """

    _GITHUB_COMMENT_LIMIT = CommentFormatter.GITHUB_COMMENT_LIMIT
    _TRUNCATION_MARKER = CommentFormatter.TRUNCATION_MARKER
    _HEADER_RESERVE = 50  # room for "*Part X/Y*\n\n" prefix

    # Re-export from prep module for backward compatibility
    _HYDRAFLOW_LABELS = HYDRAFLOW_LABELS
    _HYDRAFLOW_LITERAL_LABELS = HYDRAFLOW_LITERAL_LABELS

    _REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

    # Class-level constants the extracted mixins read through ``self``. They
    # stay on PRManager so ``PRManager._PASSING_STATES`` (referenced by tests
    # and by auto_agent_preflight_loop's commentary) keeps its identity.
    _SCREENSHOT_RELEASE_TAG = "screenshots"
    _RUN_ID_PATTERN = re.compile(r"/actions/runs/(\d+)")
    _PASSING_STATES = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})
    _PENDING_STATES = frozenset(
        {"PENDING", "QUEUED", "IN_PROGRESS", "REQUESTED", "WAITING"}
    )

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

            payload = PRCreatedPayload(
                pr=pr_number,
                issue=issue.number,
                branch=branch,
                draft=draft,
                url=pr_url,
                title=title,
            )
            # Best-effort diff-stat enrichment for the operator timeline
            # (#10788). Failure omits the keys — never blocks the event.
            merge_diff_stats(payload, await self.get_pr_diff_stats(pr_number))
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.PR_CREATED,
                    data=payload,
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
            # per-issue cost check below. Prefer a closing-verb-anchored match
            # — the canonical ``false_close.CLOSE_KEYWORD_RE``, which covers
            # every form GitHub auto-closes on (#11481) — so a title like
            # "Part of #34 - Fixed #12" bills the issue the PR actually fixes
            # rather than the epic it merely references; fall back to the first
            # "#N" for keyword-less titles (e.g. "feat(x): do thing (#123)")
            # so cost is still attributed.
            issue_match = CLOSE_KEYWORD_RE.search(pr_title or "") or re.search(
                r"#(\d+)", pr_title or ""
            )
            issue_no = int(issue_match.group(1)) if issue_match else None

            payload = MergeUpdatePayload(pr=pr_number, status="merged")
            if pr_title:
                payload["title"] = pr_title
            if issue_no is not None:
                payload["issue"] = issue_no
            # Best-effort diff-stat enrichment for the operator timeline
            # (#10788). Fetched post-merge so ``commit_sha`` resolves to the
            # squash merge commit (``mergeCommit.oid``); failure omits the keys.
            merge_diff_stats(payload, await self.get_pr_diff_stats(pr_number))
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
        # Consult the canonical ADR-0002 state machine (single source of truth:
        # label_transitions.LABEL_TRANSITIONS). Advisory and fail-open per the
        # dark-factory contract — a label move is never blocked — but a target
        # that is neither a canonical pipeline stage nor a known non-stage
        # target (e.g. diagnose) is surfaced for observability (#10621).
        if label not in pipeline_stage_labels() and new_stage not in _STAGE_LABEL:
            logger.debug(
                "transition: target %r (%s) is not a canonical ADR-0002 "
                "pipeline stage; proceeding fail-open",
                new_stage,
                label,
            )
        await self.swap_pipeline_labels(issue_number, label, pr_number=pr_number)

    async def close_task(self, issue_number: int) -> None:
        """Implement :class:`task_source.TaskTransitioner` — close the issue."""
        await self.close_issue(issue_number)

    async def create_task(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        """Implement :class:`task_source.TaskTransitioner` — create a new issue."""
        return await self.create_issue(title, body, labels)
