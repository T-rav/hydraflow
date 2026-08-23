"""RC promotion and branch-protection surface of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's, so the fake and the thing it
doubles read alike. This module is the fake's side of:

    pr_manager_promotion.PRManagerPromotionMixin

One concern: the ADR-0042 two-tier release path — cutting an ``rc/*`` branch,
opening / finding / merging its promotion PR, the base and branch updates that
keep it mergeable, branch bookkeeping, and the ruleset / legacy branch-protection
reads the guard configuration is checked against.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from mockworld.fakes._factories import PRInfoFactory

from ._common import _RC_BRANCH_PREFIX, _RC_FIXED_DATE, FakePR

if TYPE_CHECKING:
    from typing import Any


class FakeGitHubPromotionMixin:
    """RC promotion and branch-protection surface of ``FakeGitHub``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``FakeGitHub.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``FakeGitHub``'s MRO.
    # ------------------------------------------------------------------
    _branch_commits: dict[str, list[dict[str, str]]]
    _legacy_protection: dict[str, dict[str, Any]]
    _pr_counter: int
    _prs: dict[int, FakePR]
    _rc_branches: dict[str, str]
    _rulesets: dict[str, dict[str, Any]]

    if TYPE_CHECKING:

        def _maybe_rate_limit(self) -> None: ...  # provided by _seeding

    async def create_rc_branch(self, rc_branch: str) -> str:
        self._rc_branches[rc_branch] = _RC_FIXED_DATE
        return f"sha-{rc_branch}"

    async def push_synthetic_commit(self, branch: str, message: str) -> str:
        """Record a synthetic commit; deterministic SHA in scenarios."""
        _ = (message,)
        self._maybe_rate_limit()
        return f"synthetic-sha-{branch}"

    async def create_promotion_pr(
        self, *, rc_branch: str, title: str, body: str, **_kw: Any
    ) -> int:
        _ = (title, body)
        num = self._pr_counter
        self._pr_counter += 1
        self._prs[num] = FakePR(
            number=num,
            issue_number=0,
            branch=rc_branch,
            draft=False,
            url=f"https://github.com/test/repo/pull/{num}",
        )
        return num

    async def find_open_promotion_pr(self) -> Any:
        """First open ``rc/*`` PR, as PRInfo — the real read's projection."""
        for pr in sorted(self._prs.values(), key=lambda p: p.number):
            if (
                pr.branch.startswith(_RC_BRANCH_PREFIX)
                and not pr.merged
                and not pr.closed
            ):
                return PRInfoFactory.create(
                    number=pr.number,
                    issue_number=0,
                    branch=pr.branch,
                    url=pr.url,
                    draft=pr.draft,
                )
        return None

    async def merge_promotion_pr(self, pr_number: int, **_kw: Any) -> bool:
        if pr_number in self._prs:
            self._prs[pr_number].merged = True
        return True

    async def update_pr_branch(self, pr_number: int, *, method: str = "rebase") -> bool:
        """Fake rebase: clears mergeable flag, always succeeds when PR exists."""
        _ = (method,)
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return False
        pr.mergeable = True
        return True

    async def update_pr_base(self, pr_number: int, *, base: str) -> bool:
        """Fake retarget: records the new base on the in-memory PR."""
        self._maybe_rate_limit()
        if pr_number in self._prs:
            self._prs[pr_number].base = base
            return True
        return False

    async def list_rc_branches(self) -> list[tuple[str, str]]:
        return list(self._rc_branches.items())

    async def delete_branch(self, branch: str) -> bool:
        self._rc_branches.pop(branch, None)
        self._branch_commits.pop(branch, None)
        return True

    async def list_recent_promotion_prs(self, days: int = 7) -> list[dict[str, Any]]:
        """Closed ``rc/*`` PRs in the ``GhPromotionPR`` projection shape."""
        _ = days  # every fake entry is "recent" — fixed dates, no wall clock
        return [
            {
                "number": pr.number,
                "branch": pr.branch,
                "merged": pr.merged,
                "closed_at": _RC_FIXED_DATE,
                "url": pr.url,
            }
            for pr in sorted(self._prs.values(), key=lambda p: p.number)
            if pr.branch.startswith(_RC_BRANCH_PREFIX) and (pr.merged or pr.closed)
        ]

    async def ensure_branch_exists(self, branch: str, *, base: str) -> bool:
        _ = (branch, base)
        return False

    async def apply_staging_branch_protection(self, branch: str) -> dict[str, Any]:
        return {"status": "protected", "branch": branch}

    def fetch_rulesets(self, repo: str) -> dict[str, dict[str, Any]]:
        """Serve seeded branch-protection rulesets, keyed by ruleset name.

        Sync mirror of ``branch_protection_audit.gh_fetch_rulesets`` (which
        shells out to ``gh api /repos/{repo}/rulesets``). Injectable verbatim
        as the ``fetch_rulesets=`` seam of ``branch_protection_audit.audit_repo``
        so a sandbox / scenario ``branch_protection_auditor`` run observes drift
        against the canonical contract without a real network fetch — the seam
        the s41 scenario needs (#9644, ADR-0082).

        ``repo`` is accepted for signature parity with ``gh_fetch_rulesets`` but
        ignored: the Fake serves one repo's worth of seeded state. Returns a
        deep copy so a caller mutating the result cannot corrupt seeded state.
        """
        _ = repo
        return copy.deepcopy(self._rulesets)

    def fetch_legacy_protection(self, repo: str, branch: str) -> dict[str, Any] | None:
        """Serve seeded classic branch-protection config for one branch.

        Sync mirror of ``branch_protection_audit.gh_fetch_legacy_protection``
        (which shells out to ``gh api /repos/{repo}/branches/{branch}/
        protection``, 404-ing to ``None`` when no classic rule exists).
        Injectable verbatim as the ``fetch_legacy_protection=`` seam of
        ``branch_protection_audit.audit_repo`` so a sandbox / scenario
        ``branch_protection_auditor`` run can observe an undeclared
        legacy-layer drift without a real network fetch (#10148).

        ``repo`` is accepted for signature parity with
        ``gh_fetch_legacy_protection`` but ignored: the Fake serves one
        repo's worth of seeded state. Returns a deep copy so a caller
        mutating the result cannot corrupt seeded state. ``None`` (not an
        empty dict) when ``branch`` was never seeded — matches the raw
        fetcher's "no classic rule" return.
        """
        _ = repo
        protection = self._legacy_protection.get(branch)
        return copy.deepcopy(protection) if protection is not None else None
