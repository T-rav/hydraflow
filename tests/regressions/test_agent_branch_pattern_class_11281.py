"""Regression pins for the #11281 agent-branch-pattern class.

Class: every module that resolves "the branch for issue N" knew only
``agent/issue-{N}`` and was blind to Auto-Agent's ``agent/auto-agent-{N}``.
Three sites were found separately —
- issue_fetcher (#11282): the review loop never saw auto-agent PRs, so
  their CI failures never fed back into a commit (fixed in #11334),
- pr_manager (#11323): HITL items / PR lookups missed them,
- branch_gc_scan (#11281, this fix): StaleIssueLoop treated live
  auto-agent branches as unrecognised.

Pins:
1. The GC branch extractor recognises BOTH mint patterns.
2. ``config.agent_branches_for_issue`` returns both, manual first (the
   precedence consumers use).
3. Non-agent branches are still ignored.
"""

from __future__ import annotations

from branch_gc_scan import extract_issue_number
from config import AUTO_AGENT_BRANCH_PREFIX, HydraFlowConfig


def test_gc_extractor_recognises_both_mint_patterns() -> None:
    assert extract_issue_number("agent/issue-42", []) == 42
    assert extract_issue_number("agent/auto-agent-42", []) == 42


def test_gc_extractor_ignores_non_agent_branches() -> None:
    for branch in ("feature/x", "main", "staging", "rc/2026-08-17-0900"):
        assert extract_issue_number(branch, []) == 0


def test_config_exposes_the_canonical_pair() -> None:
    config = HydraFlowConfig()
    pair = config.agent_branches_for_issue(42)
    assert pair == ("agent/issue-42", f"{AUTO_AGENT_BRANCH_PREFIX}42")
    # Manual-first ordering is load-bearing: consumers resolve in this
    # precedence when both branches somehow exist.
    assert pair[0] == config.branch_for_issue(42)
    assert pair[1] == config.auto_agent_branch_for_issue(42)


def test_helper_covers_every_known_mint_site() -> None:
    """Both prefixes an agent branch can carry are reachable from config —
    a third mint pattern must extend the helper, not add a fourth
    hand-rolled f-string."""
    config = HydraFlowConfig()
    prefixes = {
        branch.rsplit("-", 1)[0] for branch in config.agent_branches_for_issue(1)
    }
    assert prefixes == {"agent/issue", "agent/auto-agent"}
