"""extract_json + SpecJudge tolerance for fenced/prose/empty agent output.

The lightweight adversarial agent path returns the model's free-form stdout,
which commonly wraps JSON in a ```json fence or prepends prose, and returns ""
on soft-fail. A bare ``json.loads`` on that raises
``Expecting value: line 1 column 1 (char 0)``, which SpecJudge mistook for an
unparseable spec and converted into a false SPEC-JUDGE-001/HIGH carryover.
``extract_json`` recovers the JSON from fenced/prose replies while still
raising ``json.JSONDecodeError`` on genuinely-empty/no-JSON input so the
fail-closed path still fires.
"""

from __future__ import annotations

import json

import pytest
from src.adversarial_agents import extract_json
from src.spec_judge import JudgeResult, SpecJudge


class _StubAgent:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def run(self, system_prompt: str, user_message: str) -> str:
        return self.payload


def test_extract_json_parses_bare_object() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_json_fence() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_strips_bare_fence() -> None:
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_tolerates_leading_prose() -> None:
    assert extract_json('Here is the result:\n{"a": 1}') == {"a": 1}


def test_extract_json_tolerates_trailing_prose() -> None:
    assert extract_json('{"a": 1}\nHope that helps!') == {"a": 1}


def test_extract_json_handles_nested_braces_and_string_braces() -> None:
    raw = '{"a": "x}y", "b": {"c": 2}}'
    assert extract_json(raw) == {"a": "x}y", "b": {"c": 2}}


@pytest.mark.parametrize("raw", ["", "   \n  ", "just prose, no json"])
def test_extract_json_raises_on_no_recoverable_json(raw: str) -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json(raw)


@pytest.mark.asyncio
async def test_spec_judge_parses_fenced_output() -> None:
    payload = '```json\n{"verdict": "PASS", "findings": []}\n```'
    judge = SpecJudge(agent=_StubAgent(payload))

    result = await judge.evaluate(plan_text="a plan", acceptance_criteria=["AC1"])

    assert isinstance(result, JudgeResult)
    assert result.verdict == "PASS"
    assert result.findings == []


@pytest.mark.asyncio
async def test_spec_judge_parses_prose_wrapped_findings() -> None:
    payload = (
        "Sure, here is my judgement:\n"
        '{"verdict": "FAIL", "findings": '
        '[{"severity": "HIGH", "concern": "AC1 is not observable"}]}'
    )
    judge = SpecJudge(agent=_StubAgent(payload))

    result = await judge.evaluate(plan_text="a plan", acceptance_criteria=["AC1"])

    assert result.verdict == "FAIL"
    assert [f.concern for f in result.findings] == ["AC1 is not observable"]


@pytest.mark.asyncio
async def test_spec_judge_fails_closed_on_empty_output() -> None:
    judge = SpecJudge(agent=_StubAgent(""))

    result = await judge.evaluate(plan_text="a plan", acceptance_criteria=["AC1"])

    assert result.verdict == "FAIL"
    assert len(result.findings) == 1
    assert result.findings[0].id == "SPEC-JUDGE-001"
    assert result.findings[0].severity == "HIGH"
