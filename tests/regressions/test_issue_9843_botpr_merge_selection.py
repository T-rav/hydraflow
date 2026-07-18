"""Regression: DependabotMergeLoop merged nothing (#9843, fixed in #9857).

Selection dropped every eligible bot PR:
- ``gh --json author`` renders a GitHub App as ``app/dependabot``, which never
  equals the configured ``dependabot[bot]`` — so even real Dependabot PRs were
  skipped.
- The UL/pricing/wiki maintenance loops open PRs under a *user* token
  (``HydraOps-T-rav`` / ``T-rav``, ``is_bot=False``) on ``ul-*`` / ``pricing`` /
  ``wiki`` branches that matched neither the author allowlist nor the
  ``agent/auto-agent-`` prefix.

The fix (#9857) detects bots via ``author.is_bot`` + a normalized author
comparison + a set of factory-maintenance branch prefixes. This pins those two
selection primitives so the flagship regression (loop selects zero PRs) can't
silently return.
"""

from __future__ import annotations

from dependabot_merge_loop import (
    _FACTORY_MAINTENANCE_BRANCH_PREFIXES,
    _normalize_author,
)


def test_app_prefixed_bot_login_matches_configured_bot() -> None:
    """gh's ``app/dependabot`` must normalize to the same key as the configured
    ``dependabot[bot]`` — otherwise real Dependabot PRs are never selected."""
    assert _normalize_author("app/dependabot") == _normalize_author("dependabot[bot]")
    assert _normalize_author("app/dependabot") == "dependabot"
    # Case-insensitive + Renovate too.
    assert _normalize_author("Renovate[bot]") == _normalize_author("app/renovate")


def test_factory_maintenance_branches_are_selectable() -> None:
    """Every UL/pricing/wiki maintenance branch namespace must be recognized so
    those PRs (opened under a user token, ``is_bot=False``) get an auto-merge
    path."""
    for branch in (
        "ul-proposer/abc123",
        "ul-evidence/abc123",
        "ul-edges/abc123",
        "ul-pruner/abc123",
        "pricing-refresh-auto",
        "hydraflow/wiki-maint-20260718-1200",
    ):
        assert branch.startswith(_FACTORY_MAINTENANCE_BRANCH_PREFIXES), branch


def test_human_and_lookalike_branches_not_selectable() -> None:
    """Human branches (and ``ul-`` look-alikes without the exact prefix) must
    NOT be auto-merge-selectable."""
    for branch in ("fix/manual-thing", "agent/issue-42", "ul-cleanup-notes"):
        assert not branch.startswith(_FACTORY_MAINTENANCE_BRANCH_PREFIXES), branch
