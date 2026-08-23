"""Read-only PR queries of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's, so the fake and the thing it
doubles read alike. This module is the fake's side of:

    pr_manager_pr_queries.PRManagerPRQueriesMixin

One concern: what a caller can ask ABOUT a pull request — its labels, diff,
diff stats, changed file names, commit messages and recent commit diffs, HEAD
sha, title/body, reviews, approvers, mergeability, and the label-scoped and
conflicting-PR listings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mockworld.fakes._factories import PRInfoFactory
from models import PRDiffStats

if TYPE_CHECKING:
    from typing import Any

    from ._common import FakePR


class FakeGitHubPRQueriesMixin:
    """Read-only PR queries of ``FakeGitHub``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``FakeGitHub.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``FakeGitHub``'s MRO.
    # ------------------------------------------------------------------
    _commit_diffs: dict[int, list[str]]
    _default_pr_diff: str | None
    _pr_commit_messages: dict[int, str]
    _pr_diff_names: dict[int, list[str]]
    _pr_diff_stats: dict[int, PRDiffStats]
    _pr_diffs: dict[int, str]
    _prs: dict[int, FakePR]

    if TYPE_CHECKING:

        def _maybe_rate_limit(self) -> None: ...  # provided by _seeding

    async def get_pr_labels(self, pr_number: int) -> list[str]:
        """Return the label names on a PR (empty list when unknown)."""
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return []
        return list(pr.labels)

    async def get_pr_diff(self, pr_number: int) -> str:
        self._maybe_rate_limit()
        if pr_number in self._pr_diffs:
            return self._pr_diffs[pr_number]
        if self._default_pr_diff is not None:
            return self._default_pr_diff
        return "diff --git a/x b/x"

    async def get_pr_head_sha(self, pr_number: int) -> str:
        self._maybe_rate_limit()
        return "abc123"

    async def get_pr_diff_stats(self, pr_number: int) -> PRDiffStats:
        """Return seeded diff stats, or a deterministic non-empty default.

        Mirrors :meth:`PRManager.get_pr_diff_stats` (#10788): a snake_case
        ``PRDiffStats`` the operator timeline can render. Defaults to a small
        single-file diff so unseeded scenarios still exercise the enriched
        path rather than the degraded (keys-absent) one.
        """
        self._maybe_rate_limit()
        seeded = self._pr_diff_stats.get(pr_number)
        if seeded is not None:
            return seeded.copy()
        return PRDiffStats(
            commit_sha="abc123", files_changed=1, additions=1, deletions=0
        )

    async def get_pr_diff_names(self, pr_number: int) -> list[str]:
        self._maybe_rate_limit()
        return list(self._pr_diff_names.get(pr_number, ["src/app.py"]))

    async def get_pr_commit_messages(self, pr_number: int) -> str:
        self._maybe_rate_limit()
        return self._pr_commit_messages.get(pr_number, "")

    async def get_pr_recent_commit_diffs(self, pr_number: int, *, n: int = 3) -> str:
        """Return a stub diff block for the last *n* commits on *pr_number*.

        Returns a deterministic non-empty string so scenarios can assert that
        the context block is populated without hitting the GitHub API.
        """
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        branch = pr.branch if pr is not None else f"pr-{pr_number}"
        commits = self._commit_diffs.get(pr_number) or []
        if commits:
            return "\n\n".join(commits[-n:])
        return f"## deadbeef stub-commit — {branch}\ndiff --git a/x b/x\n+fix"

    async def get_pr_approvers(self, pr_number: int) -> list[str]:
        self._maybe_rate_limit()
        return ["octocat"]

    async def get_pr_title_and_body(self, pr_number: int) -> tuple[str, str]:
        """Serve seeded ``FakePR.title``/``FakePR.body`` (#11480).

        Defaults to ``("", "")`` — the same "unreadable" shape the real
        adapter returns on failure — so an unseeded PR never accidentally
        declares a closing keyword for its issue.
        """
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return ("", "")
        return (pr.title, pr.body)

    async def get_pr_reviews(self, pr_number: int) -> list[dict[str, str]]:
        """No GitHub reviews in the air-gapped sandbox. Empty → epic detail
        rendering derives no review status rather than AttributeError-ing (same
        /api/epics rendering path as get_pr_checks)."""
        self._maybe_rate_limit()
        return []

    async def list_prs_by_label(self, label: str) -> list[Any]:
        """Return open (non-merged) PRs carrying *label*.

        Mirrors ``PRManager.list_prs_by_label`` (which delegates to
        ``gh pr list --label <label> --state open``). Used by
        SandboxFailureFixerLoop to poll auto-fix candidates.

        The returned ``PRInfo`` carries the full label set so secondary
        filters (e.g. the ``no-auto-fix`` opt-out) can be applied without
        a second round-trip.
        """
        self._maybe_rate_limit()
        out: list[Any] = []
        for pr in self._prs.values():
            if pr.merged:
                continue
            if label not in pr.labels:
                continue
            out.append(
                PRInfoFactory.create(
                    number=pr.number,
                    issue_number=pr.issue_number,
                    branch=pr.branch,
                    draft=pr.draft,
                    labels=list(pr.labels),
                )
            )
        return out

    async def get_pr_mergeable(self, pr_number: int) -> bool | None:
        self._maybe_rate_limit()
        return True

    async def list_conflicting_prs(self) -> list[Any]:
        """Return PRs flagged as conflicting in the fake state."""
        from merge_state_watcher import ConflictingPR  # noqa: PLC0415

        self._maybe_rate_limit()
        results: list[Any] = []
        for pr in self._prs.values():
            if getattr(pr, "mergeable", True):
                continue
            results.append(
                ConflictingPR(
                    number=pr.number,
                    # FakePR's field is ``branch`` (mirrors headRefName). The
                    # old ``getattr(pr, "head_ref", "")`` read a field that
                    # never existed, so every conflicting PR came back with an
                    # empty branch — masked until the auto-rebase actuator
                    # (#11595) made the head-branch namespace load-bearing.
                    branch=pr.branch or "",
                    labels=list(getattr(pr, "labels", []) or []),
                )
            )
        return results
