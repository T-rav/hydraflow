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

from agent._prequality import HARNESS_WRITTEN_PATHSPECS
from scope_check import build_scope_check_prompt

_AUTO_PASS = "No implementation plan is available"
_PLAN = "## Plan\n\n## File Delta\nMODIFIED: src/a.py\n"
_DIFF = "diff --git a/src/unplanned.py b/src/unplanned.py\n"


@pytest.mark.parametrize(
    ("plan_text", "expect_auto_pass"),
    [
        ("", True),
        ("   \n  ", True),
        ("## Plan\n\n1. Do the thing", False),
        (_PLAN, False),
    ],
    ids=["no-plan", "whitespace", "no-file-delta", "real-plan"],
)
def test_only_a_genuinely_absent_plan_reaches_the_no_plan_auto_pass(
    plan_text: str, expect_auto_pass: bool
):
    """The degradation this PR closes, pinned at the boundary.

    The no-plan auto-pass is correct for genuinely absent plan text and
    wrong for everything else. Before the worktree was threaded, a cache
    miss put a REAL plan into that branch — the gate reporting a pass it
    never made. A plan without a File Delta still reaches the classifier
    (that is pre-existing behaviour, deliberately not changed here).
    """
    prompt = build_scope_check_prompt(
        issue_number=1, issue_title="t", diff=_DIFF, plan_text=plan_text
    )

    assert (_AUTO_PASS in prompt) is expect_auto_pass
    if not expect_auto_pass:
        assert "Classification Rules" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pathspec",
    HARNESS_WRITTEN_PATHSPECS,
    ids=lambda spec: spec.removeprefix(":(exclude)"),
)
async def test_the_judged_diff_excludes_every_harness_written_path(
    tmp_path, pathspec: str
):
    """A blocking gate must not judge files the agent never wrote.

    Parametrised over the paths `HARNESS_WRITTEN_PATHSPECS` names — one case
    per exclusion, so dropping any single entry reddens. A single-path test
    let four of five be deleted silently, which is exactly what
    docs/standards/parametrised_guards/ exists to prevent.
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

    # Derived from the pathspec so the case list cannot drift from the set:
    # a prefix entry needs a file under it, a file entry is the file.
    excluded = pathspec.removeprefix(":(exclude)")
    harness_path = (
        excluded if excluded.endswith(".jsonl") or excluded.endswith(".lock")
        else f"{excluded}/issue-7/plan.md"
    )
    target = repo / harness_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("harness wrote this\n", encoding="utf-8")
    (repo / "real_work.py").write_text("def frob(): return 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "work plus a harness artifact")

    class _Host(AgentPreQualityReviewMixin):
        def __init__(self) -> None:
            self._config = ConfigFactory.create()
            self._runner = get_default_runner()

    diff = await _Host()._get_branch_diff(repo, "agent/issue-7")

    assert "real_work.py" in diff, "the agent's own work must still be judged"
    assert harness_path not in diff, (
        f"{harness_path} is harness-written and reached the diff a BLOCKING "
        "scope-check judges; it can fail a change for work the agent never did"
    )


@pytest.mark.asyncio
async def test_an_agent_written_generated_path_is_still_judged(tmp_path):
    """The exclusion must not blind the skills to the agent's own delivery.

    `repo_wiki/` and `docs/arch/generated/` are written BY the agent via
    `make arch-regen`. Excluding them (as an earlier cut of this change did,
    by reusing null_delivery's "not a deliverable" set) hides the entire
    delivery of a wiki or arch issue — and an all-excluded diff short-
    circuits every blocking skill to a pass.
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

    generated = repo / "docs" / "arch" / "generated" / "modules.md"
    generated.parent.mkdir(parents=True)
    generated.write_text("the agent regenerated this\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "arch regen delivery")

    class _Host(AgentPreQualityReviewMixin):
        def __init__(self) -> None:
            self._config = ConfigFactory.create()
            self._runner = get_default_runner()

    diff = await _Host()._get_branch_diff(repo, "agent/issue-7")

    assert "docs/arch/generated/modules.md" in diff, (
        "the agent's own generated-arch delivery was hidden from the skills; "
        "an all-excluded diff short-circuits every blocking gate to a pass"
    )
