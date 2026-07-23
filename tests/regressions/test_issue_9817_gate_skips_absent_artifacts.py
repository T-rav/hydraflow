"""Regression: blocking gates failed issues over ABSENT artifacts (#9817, #9823).

The post-implementation skill loop (src/agent.py) runs discover-completeness
and shape-coherence as BLOCKING gates on every issue, but never passes a
``brief``/``proposal`` — so a plain bugfix routed straight to implement was
rubric-failed over an empty document (``missing-section:intent``), discarding
clean, quality-passing attempts (live case: #9553's 16-minute run-2).

Contract: the prompt builders return "" when their artifact is absent — the
skill loop's existing empty-prompt escape then passes with "no input data".
Real artifacts still produce full rubric prompts.
"""

from __future__ import annotations

from discover_completeness import build_discover_completeness_prompt
from shape_coherence import build_shape_coherence_prompt


def test_absent_brief_yields_no_prompt_instead_of_rubric_fail() -> None:
    prompt = build_discover_completeness_prompt(
        issue_number=9553,
        issue_title="subprocess reaping on watchdog cancellation",
        diff="+ real code change",  # what the agent.py skill loop passes
        plan_text="fix plan",
    )

    assert prompt == ""


def test_whitespace_brief_is_treated_as_absent() -> None:
    assert (
        build_discover_completeness_prompt(
            issue_number=1, issue_title="t", brief="   \n  "
        )
        == ""
    )


def test_real_brief_still_gets_the_full_rubric_prompt() -> None:
    prompt = build_discover_completeness_prompt(
        issue_number=1,
        issue_title="t",
        issue_body="original issue",
        brief="## Intent\nReal discovery content.",
    )

    assert "five-criterion rubric" in prompt
    assert "Real discovery content." in prompt


def test_absent_shape_proposal_yields_no_prompt() -> None:
    assert (
        build_shape_coherence_prompt(
            issue_number=9553,
            issue_title="t",
            diff="+ change",
            plan_text="plan",
        )
        == ""
    )


def test_real_shape_proposal_still_prompts() -> None:
    prompt = build_shape_coherence_prompt(
        issue_number=1,
        issue_title="t",
        proposal="## Direction A\nreal proposal",
    )

    assert "real proposal" in prompt
