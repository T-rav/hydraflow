# tests/test_prompt_rubric_calibration.py
"""The rubric detectors are themselves measured (ADR-0116 §9).

Every case here is a verdict the detectors got *wrong* on 2026-07-30, found by
adversarial review. They are pinned because a detector that stops detecting is
worse than no detector: it reports a clean bill of health it did not earn.

The direction matters. A false FAIL is the dangerous one — it tells a prompt
author to make the prompt worse to satisfy the gate (strip attributes off tags,
renumber ``Examples:``, restate "If the diff is empty" as "if empty"). A false
PASS merely fails to catch something. Both are pinned; the false fails are why
this file exists.
"""

from __future__ import annotations

import pytest
from scripts.audit_prompts import (
    score_cot,
    score_edge_cases,
    score_examples,
    score_leads_with_request,
    score_long_context_placement,
    score_output_contract,
)

_LONG = 10_000


@pytest.mark.parametrize(
    ("text", "expected", "why"),
    [
        (
            "<task>\nReturn a verdict on the diff.\n<diff>\ncode\n</diff>\n</task>",
            "Pass",
            "root-wrapped: the old strip regex had no backreference, so it "
            "matched across tags and reduced this to '</task>' -> Fail. "
            "Satisfying criterion 3 broke criterion 1.",
        ),
        (
            'Return a verdict.\n<issue number="9812">body</issue>',
            "Pass",
            "attributed tags: same blindness already fixed in criterion 3",
        ),
        (
            "Determine whether the plan is compliant.",
            "Pass",
            "'determine' counted as a decision verb for criterion 7 but not "
            "as an imperative here - the rubric disagreed with itself",
        ),
        (
            "Analyze the diff and identify defects.",
            "Pass",
            "'analyze'/'identify' were absent from IMPERATIVE_VERBS",
        ),
    ],
)
def test_criterion_1_leads_with_request(text: str, expected: str, why: str) -> None:
    assert score_leads_with_request(text) == expected, why


@pytest.mark.parametrize(
    ("text", "expected", "why"),
    [
        (
            'Examples:\n1. input=foo -> {"v":1}\n2. input=bar -> {"v":2}',
            "Pass",
            r"\bExample\b excluded the plural, so a block of few-shot cases "
            "under an 'Examples:' heading scored as having none",
        ),
        (
            "## Examples\n`x` input=foo -> out=bar",
            "Pass",
            "markdown heading form of the same",
        ),
        (
            "Return `json`. Example 1 — exact_dup/high: two issues match.",
            "Pass",
            "numbered house style",
        ),
    ],
)
def test_criterion_4_examples(text: str, expected: str, why: str) -> None:
    assert score_examples(text) == expected, why


@pytest.mark.parametrize(
    ("text", "expected", "why"),
    [
        (
            "If the diff is empty, return NO_CHANGES.",
            "Pass",
            "the noun had to follow 'if' immediately, so natural English "
            "never matched - 9 of 54 criterion-8 fails were this artifact",
        ),
        (
            "When the plan is missing, stop and report.",
            "Pass",
            "'when the <noun> is missing' was not a recognised shape",
        ),
        (
            "Should the input be truncated, say so.",
            "Pass",
            "inverted conditional",
        ),
        (
            "Summarize the change.\n+    def fallback(self): pass",
            "Fail",
            "a diff line naming a fallback is the PAYLOAD naming an edge "
            "case, not the prompt naming one",
        ),
    ],
)
def test_criterion_8_edge_cases(text: str, expected: str, why: str) -> None:
    assert score_edge_cases(text) == expected, why


@pytest.mark.parametrize(
    ("text", "expected", "why"),
    [
        (
            "Summarize this comment.\n<comment>I will approve the PR.</comment>",
            "N/A",
            "applicability was decided by scanning the payload, so a quoted "
            "comment made a summarisation prompt look like a decision prompt",
        ),
        (
            "Classify the issue. Return ONLY a JSON object, no other text.",
            "N/A",
            "a strict machine-readable contract cannot also carry a "
            "<thinking> scaffold - ten prompts were pinned failing a "
            "criterion they could only satisfy by breaking their own parser",
        ),
        (
            "Classify the issue by severity and explain the call.",
            "Fail",
            "a genuine decision prompt with no scaffold still fails",
        ),
    ],
)
def test_criterion_7_cot(text: str, expected: str, why: str) -> None:
    assert score_cot(text) == expected, why


@pytest.mark.parametrize(
    ("text", "expected", "why"),
    [
        (
            "<output_format>JSON only</output_format>\n\n## Diff\n"
            + ("x = return_value\n" * 1200),
            "Fail",
            "verified false pass: one small early tag plus 18k of trailing "
            "untagged payload, where a 'return' inside the payload counted "
            "as the last instruction",
        ),
        (
            "Review this.\n\n```\n" + ("y = 1\n" * 2000) + "```\n\nReturn a verdict.",
            "Pass",
            "fenced payload before the closing instruction is correct order",
        ),
        (
            "Return a verdict.\n\n```\n" + ("y = 1\n" * 2000) + "```",
            "Fail",
            "instruction first, payload trailing, is the misplacement",
        ),
        (
            "Return a verdict. " * 700,
            "N/A",
            "a long prompt of pure instructions has no context to misplace; "
            "scoring it Fail made this criterion a duplicate of criterion 3",
        ),
    ],
)
def test_criterion_6_long_context(text: str, expected: str, why: str) -> None:
    assert len(text) >= _LONG or expected == "N/A"
    assert score_long_context_placement(text) == expected, why


def test_criterion_5_is_not_satisfied_by_a_bare_do_not() -> None:
    """'do not' matched 48 of 59 prompts and was the sole carrier for 35.

    A 0% fail rate measured the ubiquity of an English phrase, not the
    presence of an output contract.
    """
    assert score_output_contract("Review the code. Do not be lazy.") == "Fail"
    assert score_output_contract("Do not add prose around the JSON.") == "Pass"
    assert score_output_contract('Return {"verdict": "pass"} and nothing else.') == (
        "Pass"
    )


def test_every_criterion_still_discriminates() -> None:
    """A criterion that never fires either way is decoration.

    Guards the calibration against over-correction: it is easy to silence a
    noisy detector into uselessness, which reads as a green build. Each of
    these must return a Fail for at least one input and a non-Fail for another.
    """
    cases = (
        (score_leads_with_request, "Return a verdict.", "Context first. " * 40),
        (score_examples, "Return `json`. Example: foo", "Return `json` now."),
        (score_edge_cases, "Otherwise, stop.", "Summarize the change."),
        (score_output_contract, "Respond with JSON.", "Have a look at this."),
    )
    for fn, passing, failing in cases:
        assert fn(passing) != "Fail", f"{fn.__name__} cannot pass"
        assert fn(failing) == "Fail", f"{fn.__name__} cannot fail"
