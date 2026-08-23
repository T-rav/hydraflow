"""Dashboard / cache aggregate reads of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's, so the fake and the thing it
doubles read alike. This module is the fake's side of:

    pr_manager_dashboard.PRManagerDashboardMixin

One concern: the bulk snapshots ``GitHubCacheLoop`` and the dashboard poll —
the full issue and PR listings, the HITL queue, the label counts, and the two
open-PR views.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    from ._common import FakeIssue, FakePR


class FakeGitHubDashboardMixin:
    """Dashboard / cache aggregate reads of ``FakeGitHub``."""

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

        def _maybe_rate_limit(self) -> None: ...  # provided by _seeding

        def pr_for_issue(
            self, issue_number: int
        ) -> FakePR | None: ...  # provided by _seeding

    async def list_all_prs(
        self, *, state: str = "all", limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Return PRs in *state* as raw gh-wire dicts (#11418).

        Mirrors ``PRManager.list_all_prs``' field shape: number, state,
        labels, createdAt, closedAt, mergedAt.
        """
        self._maybe_rate_limit()

        def _pr_state(pr: FakePR) -> str:
            if pr.merged:
                return "merged"
            if pr.closed:
                return "closed"
            return "open"

        wanted = None if state == "all" else state.lower()
        items = []
        for pr in self._prs.values():
            pr_state = _pr_state(pr)
            if wanted is not None and pr_state != wanted:
                continue
            items.append(
                {
                    "number": pr.number,
                    "state": pr_state.upper(),
                    "labels": [{"name": lbl} for lbl in pr.labels],
                    "createdAt": pr.created_at,
                    "closedAt": (pr.closed_at or pr.created_at)
                    if pr_state != "open"
                    else None,
                    "mergedAt": (pr.merged_at or pr.created_at) if pr.merged else None,
                }
            )
        return items[:limit]

    async def list_hitl_items(
        self, hitl_labels: list[str], *, concurrency: int = 10
    ) -> list[Any]:
        """Return HITLItem-compatible objects for issues with HITL labels."""
        self._maybe_rate_limit()
        from models import HITLItem

        items: list[HITLItem] = []
        for issue in self._issues.values():
            if issue.state != "open":
                continue
            if any(lbl in issue.labels for lbl in hitl_labels):
                pr = self.pr_for_issue(issue.number)
                items.append(
                    HITLItem(
                        issue=issue.number,
                        title=issue.title,
                        pr=pr.number if pr else 0,
                        branch=pr.branch if pr else "",
                        cause="ci_failure",
                    )
                )
        return items

    async def get_label_counts(self, config: Any) -> dict[str, Any]:
        """Return open-by-label / total-closed / total-merged counts.

        Mirrors ``PRManager.get_label_counts``. Used by ``GitHubCacheLoop``
        to pre-warm the dashboard's "throughput" tile. The Fake walks
        ``_issues`` for open counts and ``_prs`` for merged counts.
        """
        self._maybe_rate_limit()
        label_map = {
            "hydraflow-plan": getattr(config, "planner_label", ["hydraflow-plan"]),
            "hydraflow-ready": getattr(config, "ready_label", ["hydraflow-ready"]),
            "hydraflow-review": getattr(config, "review_label", ["hydraflow-review"]),
            "hydraflow-hitl": getattr(config, "hitl_label", ["hydraflow-hitl"]),
            "hydraflow-fixed": getattr(config, "fixed_label", ["hydraflow-fixed"]),
        }
        open_by_label: dict[str, int] = {}
        for canonical, labels in label_map.items():
            wanted = set(labels) if isinstance(labels, list) else {labels}
            count = sum(
                1
                for issue in self._issues.values()
                if issue.state == "open" and (set(issue.labels) & wanted)
            )
            open_by_label[canonical] = count

        fixed_label = (
            getattr(config, "fixed_label", ["hydraflow-fixed"])[0]
            if getattr(config, "fixed_label", None)
            else "hydraflow-fixed"
        )
        total_closed = sum(
            1
            for issue in self._issues.values()
            if issue.state != "open" and fixed_label in issue.labels
        )
        total_merged = sum(1 for pr in self._prs.values() if pr.merged)

        return {
            "open_by_label": open_by_label,
            "total_closed": total_closed,
            "total_merged": total_merged,
        }

    async def list_open_prs(self, labels: list[str]) -> list[Any]:
        """Return open PRs carrying any of *labels* as PRListItem-style objects.

        Mirrors ``PRManager.list_open_prs``. Used by ``GitHubCacheLoop`` to
        warm its PR-by-label cache. The Fake walks ``_prs`` filtered by
        ``merged=False`` and label intersection.
        """
        self._maybe_rate_limit()
        from models import PRListItem

        wanted = set(labels)
        out: list[PRListItem] = []
        for pr in self._prs.values():
            if pr.merged:
                continue
            if wanted and not (wanted & set(pr.labels)):
                continue
            out.append(
                PRListItem(
                    pr=pr.number,
                    issue=pr.issue_number,
                    branch=pr.branch,
                    url=pr.url or "",
                    draft=pr.draft,
                    title="",
                    merged=pr.merged,
                    author=pr.author,
                    is_bot=pr.is_bot,
                )
            )
        return out

    async def list_all_open_prs(self) -> list[Any]:
        """Return ALL open PRs regardless of label, including author login.

        Mirrors ``PRManager.list_all_open_prs``. Used by ``GitHubCacheLoop``
        to warm the all-open-PRs snapshot that ``DependabotMergeLoop`` reads
        (it filters by author). Bot PRs carry only GitHub-native labels like
        ``dependencies`` and are invisible to the label-filtered
        ``list_open_prs`` cache — this method does not filter by label.
        """
        self._maybe_rate_limit()
        from models import PRListItem

        return [
            PRListItem(
                pr=pr.number,
                issue=pr.issue_number,
                branch=pr.branch,
                url=pr.url or "",
                draft=pr.draft,
                title="",
                merged=pr.merged,
                author=pr.author,
                is_bot=pr.is_bot,
            )
            for pr in self._prs.values()
            if not pr.merged
        ]
