"""Scope-check and plan-compliance must not go inert for want of a plan.

``AgentRunner`` loads plan text for its post-implementation skills. Without
a worktree it saw only ``.hydraflow/plans/``, so a cache miss — a GC sweep,
a different host, a re-plan — left ``plan_text`` empty. Two safety skills
degrade silently on that:

- ``build_scope_check_prompt`` returns a canned **auto-pass** prompt.
- plan-compliance produces an empty prompt and does not execute at all.

Neither failure is visible: the pipeline reports the same shape as a real
pass. ``tests/scenarios/test_agent_realistic.py`` even encoded it as
expected — "plan-compliance is skipped: empty prompt with no plan".

The call sites themselves are pinned by the SCENARIO layer, which counts
the skills that actually run — mutation-proven: removing the argument
reddens it. A signature assertion would not have; the parameter has existed
since ADR-0149 landed, and what was missing is anyone passing it.
"""

from __future__ import annotations

import pytest

from scope_check import build_scope_check_prompt

_AUTO_PASS = "No implementation plan is available"
_PLAN = "## Plan\n\n## File Delta\nMODIFIED: src/a.py\n"
_DIFF = "diff --git a/src/unplanned.py b/src/unplanned.py\n"


@pytest.mark.parametrize(
    ("plan_text", "expect_auto_pass"),
    [
        ("", True),
        ("   \n  ", True),
        (_PLAN, False),
    ],
)
def test_only_an_empty_plan_reaches_the_scope_check_auto_pass(
    plan_text: str, expect_auto_pass: bool
):
    """The degradation this exists to keep unreachable, pinned as fact."""
    prompt = build_scope_check_prompt(
        issue_number=1, issue_title="t", diff=_DIFF, plan_text=plan_text
    )

    assert (_AUTO_PASS in prompt) is expect_auto_pass


@pytest.mark.asyncio
async def test_the_judged_diff_excludes_the_harnesss_own_chain(tmp_path):
    """A blocking gate must not judge files the agent never wrote.

    `_get_branch_diff` feeds the post-implementation skills, and scope-check
    is blocking. The harness commits `docs/changes/issue-N/*.md` to the
    branch BEFORE the agent starts, so those files are in the branch diff of
    every change — and no plan's File Delta names them. Without the
    exclusion, arming scope-check lets it fail a change for the artifact
    chain itself.

    The two other consumers of this diff already exclude it for the same
    reason (`agent/_commit.py`, `null_delivery.py`); this is the third.
    """
    import subprocess

    from agent._prequality import AgentPreQualityReviewMixin
    from execution import get_default_runner
    from tests.helpers import ConfigFactory

    repo = tmp_path / "wt"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "base")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    git("checkout", "-q", "-b", "agent/issue-7")

    chain = repo / "docs" / "changes" / "issue-7"
    chain.mkdir(parents=True)
    (chain / "plan.md").write_text("the committed plan\n", encoding="utf-8")
    (repo / "real_work.py").write_text("def frob(): return 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "work plus the harness chain")

    class _Host(AgentPreQualityReviewMixin):
        def __init__(self) -> None:
            self._config = ConfigFactory.create()
            self._runner = get_default_runner()

    diff = await _Host()._get_branch_diff(repo, "agent/issue-7")

    assert "real_work.py" in diff, "the agent's own work must still be judged"
    assert "docs/changes" not in diff, (
        "the harness's artifact chain is in the diff scope-check judges; a "
        "blocking gate can now fail a change for files the agent never wrote"
    )
