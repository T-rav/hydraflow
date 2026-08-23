"""Comment and review-submission surface of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's: this module is the fake's
side of ``pr_manager_comments.PRManagerCommentsMixin``, so the fake and the thing it doubles read alike.

One concern: everything that writes or reads a comment — issue comments, PR
comments, submitted reviews, and the structured ``list_issue_comments`` read
that carries each comment's ``login`` / ``created_at``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import FakeComment

if TYPE_CHECKING:
    from typing import Any

    from ._common import FakeIssue


class FakeGitHubCommentsMixin:
    """Comment and review-submission surface of ``FakeGitHub``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``FakeGitHub.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``FakeGitHub``'s MRO.
    # ------------------------------------------------------------------
    _comments: list[tuple[int, str]]
    _issues: dict[int, FakeIssue]

    if TYPE_CHECKING:

        def _maybe_rate_limit(self) -> None: ...  # provided by _seeding

    async def post_comment(self, issue_number: int, body: str) -> None:
        self._maybe_rate_limit()
        self._comments.append((issue_number, body))
        if issue_number in self._issues:
            self._issues[issue_number].comments.append(FakeComment(body))

    async def post_pr_comment(self, pr_number: int, body: str) -> None:
        self._maybe_rate_limit()
        self._comments.append((pr_number, body))

    async def submit_review(
        self, pr_number: int, verdict: Any, body: str, **_kw: Any
    ) -> bool:
        """Submit a formal PR review (no-op stub — always returns True)."""
        self._maybe_rate_limit()
        return True

    async def list_issue_comments(self, issue_number: int) -> list[dict[str, Any]]:
        """Return comments seeded on the issue (oldest first).

        FakeIssue.comments stores structured FakeComment records (each a str
        subclass carrying its own login/created_at); this method wraps each
        into a `gh issue view --json comments`-shaped dict so callers (notably
        gather_context, which does `c.get("user", {}).get("login", ...)`)
        operate on dicts as the real PRPort contract requires.
        """
        self._maybe_rate_limit()
        issue = self._issues.get(issue_number)
        if issue is None:
            return []
        return [
            {
                "user": {"login": getattr(comment, "login", "fake-author")},
                "body": str(comment),
                "created_at": getattr(comment, "created_at", "2026-01-01T00:00:00Z"),
            }
            for comment in (getattr(issue, "comments", []) or [])
        ]
