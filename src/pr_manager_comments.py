"""Comment + review-submission surface of :class:`pr_manager.PRManager`.

Extracted VERBATIM from ``pr_manager.py`` (god-class decomposition, Refs
#11547) as a mixin, same shape as ``pr_manager_promotion.py``. ``PRManager``
inherits :class:`PRManagerCommentsMixin`, so ``PRManager().post_comment`` and
the ten ``patch("pr_manager.PRManager.post_comment")`` sites in the suite
resolve exactly as before.

One cohesive concern: everything HydraFlow *says* on GitHub — chunked issue
and PR comments, the comment listing the loops read back, and the formal
review submission (approve / request-changes / comment).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Literal

from comment_formatter import CommentFormatter, SelfReviewError
from models import ReviewVerdict
from pr_manager_common import _normalise_issue_comment

if TYPE_CHECKING:
    from pathlib import Path

    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.pr_manager")


class PRManagerCommentsMixin:
    """Comment and review posting mixed into :class:`pr_manager.PRManager`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by PRManager or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in PRManager's MRO.
    # ------------------------------------------------------------------
    _config: HydraFlowConfig
    _repo: str
    _HEADER_RESERVE: int

    if TYPE_CHECKING:

        def _assert_repo(self) -> None: ...  # provided by PRManager

        async def _run_gh(
            self, *cmd: str, cwd: Path | None = None
        ) -> str: ...  # provided by PRManager

        async def _run_with_body_file(
            self,
            *cmd: str,
            body: str,
            cwd: Path | None = None,
            file_flag: str = "--body-file",
        ) -> str: ...  # provided by PRManager

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
