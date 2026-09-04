"""Scope-check and plan-compliance must not go inert for want of a plan.

``AgentRunner`` loads plan text for its post-implementation skills. Without
a worktree it saw only ``.hydraflow/plans/``, so a cache miss — a GC sweep,
a different host, a re-plan — left ``plan_text`` empty. Two safety skills
degrade silently on that:

- ``build_scope_check_prompt`` returns a canned **auto-pass** prompt
  ("No implementation plan is available — auto-pass").
- plan-compliance produces an empty prompt and does not execute at all.

Neither failure is visible: the pipeline reports the same shape as a real
pass. ``tests/scenarios/test_agent_realistic.py`` even encoded it as
expected — "plan-compliance is skipped: empty prompt with no plan".

ADR-0149 commits the plan to the change's own branch precisely so it
outlives the cache. Threading the worktree into the fallback is what makes
the committed copy reachable.
"""

from __future__ import annotations

import pytest

from scope_check import build_scope_check_prompt

_AUTO_PASS = "No implementation plan is available"
_PLAN = "## Plan\n\n## File Delta\nMODIFIED: src/a.py\n"
_DIFF = "diff --git a/src/unplanned.py b/src/unplanned.py\n"


def test_an_empty_plan_still_auto_passes_scope_check():
    """The degradation this exists to keep unreachable, pinned as fact."""
    prompt = build_scope_check_prompt(
        issue_number=1, issue_title="t", diff=_DIFF, plan_text=""
    )

    assert _AUTO_PASS in prompt


def test_a_plan_makes_scope_check_compare_instead_of_auto_pass():
    prompt = build_scope_check_prompt(
        issue_number=1, issue_title="t", diff=_DIFF, plan_text=_PLAN
    )

    assert _AUTO_PASS not in prompt


def test_the_comparison_names_the_planned_file():
    prompt = build_scope_check_prompt(
        issue_number=1, issue_title="t", diff=_DIFF, plan_text=_PLAN
    )

    assert "src/a.py" in prompt


def test_the_runner_passes_its_worktree_to_the_plan_fallback():
    """The wiring, by signature rather than by spelling.

    ``_load_plan_fallback`` takes an optional worktree; a caller that omits
    it silently gets the cache-only behaviour and both skills degrade. This
    pins that the parameter exists to be passed — the call site itself is
    covered by the scenario layer, which counts the skills that run.
    """
    import inspect

    from agent._plan import AgentPlanMixin

    signature = inspect.signature(AgentPlanMixin._load_plan_fallback)

    assert "worktree" in signature.parameters


@pytest.mark.parametrize(
    ("plan_text", "expect_auto_pass"),
    [
        ("", True),
        ("   \n  ", True),
        (_PLAN, False),
    ],
)
def test_only_a_genuinely_empty_plan_reaches_the_auto_pass(
    plan_text: str, expect_auto_pass: bool
):
    prompt = build_scope_check_prompt(
        issue_number=1, issue_title="t", diff=_DIFF, plan_text=plan_text
    )

    assert (_AUTO_PASS in prompt) is expect_auto_pass
