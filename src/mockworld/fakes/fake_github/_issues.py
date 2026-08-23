"""Issue lifecycle and issue queries of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's: this module is the fake's side
of ``pr_manager_issues.PRManagerIssuesMixin``, so the fake and the thing it doubles read alike.

One concern: the issue side of the GitHub surface — closing (with the #10394
dispatchable-label strip), reopening, creating, body edits, the state/label/body
reads, and the label-scoped listings the dispatchers poll.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import _DISPATCHABLE_STAGE_LABELS

if TYPE_CHECKING:
    from typing import Any

    from ._common import FakeIssue, FakePR


class FakeGitHubIssuesMixin:
    """Issue lifecycle and issue queries of ``FakeGitHub``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``FakeGitHub.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``FakeGitHub``'s MRO.
    # ------------------------------------------------------------------
    _issues: dict[int, FakeIssue]
    _prs: dict[int, FakePR]

    if TYPE_CHECKING:

        @staticmethod
        def _issue_summary(
            issue: FakeIssue,
        ) -> dict[str, Any]: ...  # provided by _dashboard

        def _maybe_rate_limit(self) -> None: ...  # provided by _seeding

        def add_issue(
            self,
            number: int,
            title: str,
            body: str,
            labels: list[str] | None = None,
            state: str = "open",
            updated_at: str | None = None,
            created_at: str | None = None,
        ) -> None: ...  # provided by _seeding

    async def close_issue(
        self, issue_number: int, *, reason: str | None = None
    ) -> bool:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.state = "closed"
            # Mirror gh: `--reason "not planned"` -> stateReason NOT_PLANNED;
            # no --reason -> COMPLETED (get_issue_state's empty fallback).
            issue.state_reason = reason.upper().replace(" ", "_") if reason else ""
            # Mirror PRManager.close_issue's #10394 strip: a closed issue must
            # never keep an active pipeline-stage label, or a label-scan
            # dispatcher would re-queue shipped work. Scoped to the exact
            # dispatchable set (terminal + orthogonal markers survive).
            issue.labels = [
                lbl for lbl in issue.labels if lbl not in _DISPATCHABLE_STAGE_LABELS
            ]
        elif issue_number in self._prs:
            # gh treats PRs as issues — `gh issue close <pr#>` closes the PR.
            # StagingPromotionLoop closes red promotion PRs through this exact
            # call (#10309); without the fallthrough the fake left them open
            # and the loop re-found the same "open" PR every tick.
            self._prs[issue_number].closed = True
        return True

    async def reopen_issue(self, issue_number: int) -> bool:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            issue.state = "open"
            issue.state_reason = ""
            issue.closed_at = ""
        return True

    async def find_existing_issue(self, title: str) -> int:
        self._maybe_rate_limit()
        for issue in self._issues.values():
            if issue.title == title and issue.state == "open":
                return issue.number
        return 0

    async def list_issues_by_label(self, label: str) -> list[dict[str, Any]]:
        """Return open issues carrying *label* as GitHubIssueSummary-style dicts."""
        self._maybe_rate_limit()
        return [
            self._issue_summary(issue)
            for issue in self._issues.values()
            if issue.state == "open" and label in issue.labels
        ]

    async def list_open_issues(self) -> list[dict[str, Any]]:
        """Return ALL open issues (no label filter), mirroring the gh projection.

        Used by IssueRefinementLoop's backlog-wide sweep (#9957).
        """
        self._maybe_rate_limit()
        return [
            self._issue_summary(issue)
            for issue in self._issues.values()
            if issue.state == "open"
        ]

    async def list_open_issue_numbers(self, limit: int = 500) -> list[int]:
        """Return numbers of ALL open issues, mirroring the gh projection (#9905)."""
        self._maybe_rate_limit()
        numbers = [
            issue.number for issue in self._issues.values() if issue.state == "open"
        ]
        return sorted(numbers)[:limit]

    async def list_closed_issues_by_label(
        self,
        label: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return closed issues carrying *label* (most recent up to *limit*).

        ``closed_at`` mirrors the adapter's ``closedAt`` projection (#9727)
        so churn windows keyed on close time behave identically under the
        fake and the real port. ``labels`` (#8996) reuses ``_issue_summary``
        so ``escalation_reconcile.is_bot_close`` sees the same gh-wire-shape
        label list under the fake as under the real adapter.

        ``limit`` stays positional-or-keyword (#11423) — matching
        ``PRPort.list_closed_issues_by_label`` and the ``PRManager``
        adapter, both of which permit ``list_closed_issues_by_label(label,
        limit)`` as a fully positional call.
        """
        self._maybe_rate_limit()
        rows = [
            {
                **self._issue_summary(issue),
                "closed_at": getattr(issue, "closed_at", "")
                or getattr(issue, "updated_at", "2026-01-01T00:00:00Z"),
            }
            for issue in self._issues.values()
            if issue.state != "open" and label in issue.labels
        ]
        return rows[:limit]

    async def get_issue_updated_at(self, issue_number: int) -> str:
        """Return updated_at timestamp for an issue."""
        self._maybe_rate_limit()
        if issue_number in self._issues:
            return getattr(
                self._issues[issue_number], "updated_at", "2026-01-01T00:00:00Z"
            )
        return ""

    async def get_issue_state(self, issue_number: int) -> str:
        """Return issue state as GitHub GraphQL style (OPEN/COMPLETED/NOT_PLANNED).

        An unknown issue returns ``"UNKNOWN"`` — matching prod
        ``PRManager.get_issue_state``, which fail-closes with ``"UNKNOWN"``
        when the ``gh`` read errors. The fake previously fail-opened with
        ``"OPEN"`` here, which made every still-open guard (e.g. the
        refinement TOCTOU stale-close check) pass vacuously for issues the
        fake never saw (#10025).
        """
        self._maybe_rate_limit()
        if issue_number in self._issues:
            issue = self._issues[issue_number]
            if issue.state == "closed":
                return issue.state_reason or "COMPLETED"
            return "OPEN"
        return "UNKNOWN"

    async def get_issue_labels(self, issue_number: int) -> list[str]:
        """Return the label names on an issue (empty list when unknown)."""
        self._maybe_rate_limit()
        if issue_number in self._issues:
            return list(self._issues[issue_number].labels)
        return []

    async def get_issue_body(self, issue_number: int) -> str:
        """Return the body text of an issue (empty string when unknown)."""
        self._maybe_rate_limit()
        issue = self._issues.get(issue_number)
        return issue.body if issue is not None else ""

    async def list_all_issues(
        self, *, state: str = "all", limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Return issues in *state* as raw gh-wire dicts (#11418).

        Mirrors ``PRManager.list_all_issues``' field shape: number, title,
        state, labels, createdAt, updatedAt, closedAt.
        """
        self._maybe_rate_limit()
        wanted = {"open", "closed"} if state == "all" else {state.lower()}
        items = [
            {
                "number": issue.number,
                "title": issue.title,
                "state": issue.state.upper(),
                "labels": [{"name": lbl} for lbl in issue.labels],
                "createdAt": issue.created_at,
                "updatedAt": issue.updated_at,
                "closedAt": issue.closed_at or None,
            }
            for issue in self._issues.values()
            if issue.state in wanted
        ]
        return items[:limit]

    async def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
        **_unused: Any,
    ) -> int:
        """Create a new issue and return its number."""
        self._maybe_rate_limit()
        num = max(self._issues.keys(), default=9000) + 1
        self.add_issue(num, title, body, labels=labels)
        return num

    async def get_dependabot_alerts(self, **_kw: Any) -> list[dict[str, Any]]:
        """Return Dependabot alerts."""
        self._maybe_rate_limit()
        return []

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        self._maybe_rate_limit()
        if issue_number in self._issues:
            self._issues[issue_number].body = body
