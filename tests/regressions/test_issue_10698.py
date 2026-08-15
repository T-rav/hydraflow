"""Regression for #10698 — WorkspaceGCLoop must attribute worktrees to issues
across ALL branch namespaces, not just ``agent/issue-<N>``.

The defect: `_collect_orphaned_branches` only matched ``^agent/issue-(\\d+)$``,
so worktrees on ``fix/…-<N>`` / ``feat/…`` / ``refactor/…`` branches (what the
pipeline and sub-agents actually create) were invisible to GC and leaked
forever (250+ orphans found 2026-07-26). The fix adds
``WorkspaceGCLoop._parse_issue_from_branch`` covering every namespace, and
returns ``None`` (fail-closed — never guessed) for anything that is not an
issue branch.
"""

from __future__ import annotations

import pytest

from workspace_gc_loop import WorkspaceGCLoop

parse = WorkspaceGCLoop._parse_issue_from_branch


@pytest.mark.parametrize(
    ("branch", "expected"),
    [
        # factory-native (must still work — no behaviour change)
        ("issue-10698", 10698),
        ("agent/issue-10698", 10698),
        ("agent/auto-agent-10698", 10698),  # #11182: Auto-Agent session branches
        # the namespaces the defect missed
        ("fix/workspace-gc-all-roots-10698", 10698),
        ("feat/operator-console-shell-10556", 10556),
        ("refactor/plan-flow-p3a-10682", 10682),
        ("chore/some-cleanup-9321", 9321),
        ("test/scenario-auth-8816", 8816),
        ("docs/backlog-reflection-7777", 7777),
    ],
)
def test_parses_issue_number_across_all_namespaces(branch: str, expected: int) -> None:
    assert parse(branch) == expected


@pytest.mark.parametrize(
    "branch",
    [
        None,
        "",
        "main",
        "staging",
        "rc/2026-07-26-1015",  # release-candidate branch — not an issue branch
        "fix/no-trailing-number",
        "feat/plain-slug",
        "some-random-branch",
    ],
)
def test_non_issue_branches_are_fail_closed_none(branch) -> None:
    # Must NOT guess an issue number for a branch it cannot attribute; guessing
    # would let GC reap a worktree against the wrong issue's state.
    assert parse(branch) is None
