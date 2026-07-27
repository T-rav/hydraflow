"""ADR-0042 enforcement: the two-tier branch model's ruleset encoding.

ADR-0042 (Two-tier branch model with automated release-candidate promotion)
decides that the branch model is *encoded in two GitHub rulesets* — version
controlled at ``docs/standards/branch_protection/`` — so the platform itself
rejects violations rather than relying on convention. The load-bearing,
machine-checkable core of that decision:

* ``main`` accepts **merge commits only** (squash rejected — squash from a
  long-lived integration branch produces a growing-diff regression).
* ``staging`` accepts **squash and merge**.
* Both rulesets are active and block deletion, block force-push, and require a
  pull request (no direct pushes).
* Each ruleset targets its own explicit branch ref (``main`` is targeted by an
  explicit ref, not ``~DEFAULT_BRANCH``, because ``staging`` is the GitHub
  default branch).
* ``main`` additionally requires CodeQL code-scanning at ``high_or_higher``.

These asserting tests read the canonical rulesets through the same loader the
branch-protection auditor uses, so the decision's encoding cannot silently
drift (e.g. someone re-enabling squash into ``main``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import branch_protection_audit as bpa

_MAIN = "main protect"
_STAGING = "staging protect"


def _canonical(repo_root: Path) -> dict[str, dict[str, Any]]:
    return bpa.load_canonical(repo_root / "docs" / "standards" / "branch_protection")


def _merge_methods(ruleset: dict[str, Any]) -> list[str]:
    for rule in ruleset["rules"]:
        if rule["type"] == "pull_request":
            return rule["parameters"]["allowed_merge_methods"]
    raise AssertionError("ruleset has no pull_request rule")


def _rule_types(ruleset: dict[str, Any]) -> set[str]:
    return {rule["type"] for rule in ruleset["rules"]}


def test_main_ruleset_is_merge_commit_only(real_repo_root: Path) -> None:
    """ADR-0042: squash into ``main`` is rejected — only merge commits."""
    canonical = _canonical(real_repo_root)
    assert _merge_methods(canonical[_MAIN]) == ["merge"]


def test_staging_ruleset_allows_squash_and_merge(real_repo_root: Path) -> None:
    """ADR-0042: ``staging`` is the fast integration branch — squash or merge."""
    canonical = _canonical(real_repo_root)
    assert set(_merge_methods(canonical[_STAGING])) == {"squash", "merge"}


def test_both_rulesets_are_active_and_block_deletion_forcepush_and_direct_push(
    real_repo_root: Path,
) -> None:
    """ADR-0042: both tiers block deletion + force-push and require a PR."""
    canonical = _canonical(real_repo_root)
    for name in (_MAIN, _STAGING):
        ruleset = canonical[name]
        assert ruleset["enforcement"] == "active"
        assert {"deletion", "non_fast_forward", "pull_request"} <= _rule_types(ruleset)


def test_rulesets_target_their_explicit_branch_refs(real_repo_root: Path) -> None:
    """ADR-0042: ``main`` is protected by an explicit ref (not
    ``~DEFAULT_BRANCH``, which is ``staging``); each ruleset targets its tier."""
    canonical = _canonical(real_repo_root)
    assert canonical[_MAIN]["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    assert canonical[_STAGING]["conditions"]["ref_name"]["include"] == [
        "refs/heads/staging"
    ]


def test_main_ruleset_requires_high_or_higher_codeql(real_repo_root: Path) -> None:
    """ADR-0042: ``main`` requires CodeQL code-scanning at high_or_higher."""
    canonical = _canonical(real_repo_root)
    scanning = [
        rule for rule in canonical[_MAIN]["rules"] if rule["type"] == "code_scanning"
    ]
    assert scanning, "main ruleset must carry a code_scanning rule"
    tools = scanning[0]["parameters"]["code_scanning_tools"]
    codeql = [t for t in tools if t["tool"] == "CodeQL"]
    assert codeql, "main ruleset must require the CodeQL tool"
    assert codeql[0]["security_alerts_threshold"] == "high_or_higher"
