"""Branch-level queries of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's: this module is the fake's
side of ``pr_manager_branches.PRManagerBranchesMixin``, so the fake and the thing it doubles read alike.

One concern: questions asked about a BRANCH rather than a PR — finding the open
PR for a branch, its combined PR state, whether it differs from main, remote ref
and sha resolution, and the seeded commit history the branch-GC scan reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mockworld.fakes._factories import PRInfoFactory

from ._common import _GIT_OID_RE

if TYPE_CHECKING:
    from typing import Any

    from ._common import FakePR


class FakeGitHubBranchesMixin:
    """Branch-level queries of ``FakeGitHub``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``FakeGitHub.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``FakeGitHub``'s MRO.
    # ------------------------------------------------------------------
    _branch_commits: dict[str, list[dict[str, str]]]
    _branch_heads: dict[str, str | None]
    _prs: dict[int, FakePR]
    _rc_branches: dict[str, str]

    if TYPE_CHECKING:

        def _maybe_rate_limit(self) -> None: ...  # provided by _seeding

    async def find_open_pr_for_branch(
        self,
        branch: str,
        *,
        issue_number: int | None = None,
        **_unused: Any,
    ) -> Any:
        self._maybe_rate_limit()
        for p in self._prs.values():
            if p.branch == branch and not p.merged and not p.closed:
                return PRInfoFactory.create(
                    number=p.number,
                    issue_number=p.issue_number,
                    branch=p.branch,
                )
        # No open PR for this branch — signal absence with number=0
        return PRInfoFactory.create(
            number=0,
            issue_number=issue_number or 0,
            branch=branch,
        )

    async def get_branch_pr_state(
        self, branch: str, head_sha: str, base_branch: str
    ) -> str:
        """Mirror production's exact-HEAD historical PR lookup (#11502).

        A merged PR on a reused branch is deliberately ignored unless its
        seeded base and ``head_sha`` match the caller's current integration
        target and HEAD. Multiple exact matches are ambiguous and fail closed.
        """
        self._maybe_rate_limit()
        normalized_branch = branch.removeprefix("refs/heads/")
        normalized_sha = head_sha.strip().lower()
        normalized_base = base_branch.removeprefix("refs/heads/")
        if (
            not normalized_branch
            or _GIT_OID_RE.fullmatch(normalized_sha) is None
            or not normalized_base
        ):
            return "UNKNOWN"
        matches = [
            pr
            for pr in self._prs.values()
            if pr.branch == normalized_branch
            and pr.head_sha.lower() == normalized_sha
            and pr.base_branch == normalized_base
        ]
        if not matches:
            return "NONE"
        if len(matches) != 1:
            return "UNKNOWN"
        pr = matches[0]
        if pr.merged:
            return "MERGED"
        return "CLOSED" if pr.closed else "OPEN"

    async def branch_has_diff_from_main(self, branch: str) -> bool:
        self._maybe_rate_limit()
        return True

    async def pull_main(self, **_kw: Any) -> None:
        self._maybe_rate_limit()

    async def resolve_remote_branch_sha(self, branch: str) -> str | None:
        """Seeded head for *branch* (``None`` = unresolvable), else ``sha-<branch>``."""
        self._maybe_rate_limit()
        if branch in self._branch_heads:
            return self._branch_heads[branch]
        return f"sha-{branch}"

    async def list_branch_refs(self, prefix: str) -> list[tuple[str, str]]:
        """Return ``[(branch_name, sha), ...]`` for ``refs/heads/<prefix>*`` (#11418).

        Searches every branch namespace the fake tracks — seeded GC
        branches (``add_gc_branch``), rc/* branches, and open PR head
        branches — mirroring the real ``matching-refs`` API, which is not
        scoped to any one branch lifecycle. The sha is synthetic
        (``sha-<branch>``); nothing in the fake resolves it back to a real
        commit — :meth:`list_branch_commits` looks commits up by branch
        name directly.
        """
        self._maybe_rate_limit()
        branch_names = (
            set(self._branch_commits)
            | set(self._rc_branches)
            | {pr.branch for pr in self._prs.values() if pr.branch}
        )
        return [
            (branch, f"sha-{branch}")
            for branch in sorted(branch_names)
            if branch.startswith(prefix)
        ]

    async def list_branch_commits(
        self, branch: str, *, limit: int = 30
    ) -> list[dict[str, str]]:
        """Return seeded commit history for *branch*, newest first (#11418).

        Empty when *branch* was never seeded via :meth:`add_gc_branch` —
        a scenario must explicitly seed the commit history it wants
        StaleIssueLoop's branch-GC to discover, mirroring the
        ``add_issue``/``add_pr`` seed-explicitly convention.
        """
        self._maybe_rate_limit()
        commits = self._branch_commits.get(branch, [])
        return [dict(c) for c in commits[:limit]]
