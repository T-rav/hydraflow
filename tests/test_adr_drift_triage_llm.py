"""Tests for the ADR-drift TRIAGE LLM wrapper (#9976).

Mirrors ``tests/test_term_proposer_llm.py``'s shape: a fake ``LLMClient``
returns a pre-canned dict, the wrapper validates it into the strict
Pydantic model. No real model calls anywhere in this file.
"""

from __future__ import annotations

import pytest

from adr_drift_triage_llm import AdrDriftTriageLLM, TriageContext


class FakeLLMClient:
    """Stub that returns a pre-canned structured response."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def complete_structured(
        self, *, prompt: str, schema: dict, issue_number: int, issue_labels: list[str]
    ) -> dict:
        self.calls.append(
            {
                "prompt": prompt,
                "schema": schema,
                "issue_number": issue_number,
                "issue_labels": issue_labels,
            }
        )
        return self.response


@pytest.fixture
def ctx() -> TriageContext:
    return TriageContext(
        adr_number=56,
        adr_title="ADR touchpoint gate to caretaker loop",
        adr_markdown=(
            "# ADR-0056: Example\n\n"
            "## Context\n\nBackground.\n\n"
            "## Decision\n\nWe do X.\n"
        ),
        pr_number=8473,
        pr_diff="diff --git a/src/agent.py b/src/agent.py\n+new line\n",
        issue_number=9001,
        issue_labels=("hydraflow-adr-drift", "hydraflow-find"),
    )


class TestAdrDriftTriageLLM:
    @pytest.mark.asyncio
    async def test_returns_validated_verdict(self, ctx: TriageContext) -> None:
        fake = FakeLLMClient(
            response={
                "classification": "consistent",
                "rationale": "The diff only touches an unrelated caller.",
                "section": "",
            }
        )
        triage = AdrDriftTriageLLM(client=fake)
        verdict = await triage.classify(ctx)
        assert verdict.classification.value == "consistent"
        assert "unrelated caller" in verdict.rationale
        assert len(fake.calls) == 1

    @pytest.mark.asyncio
    async def test_threads_issue_context_through(self, ctx: TriageContext) -> None:
        fake = FakeLLMClient(
            response={"classification": "low_confidence", "rationale": "unclear"}
        )
        triage = AdrDriftTriageLLM(client=fake)
        await triage.classify(ctx)
        call = fake.calls[0]
        assert call["issue_number"] == 9001
        assert call["issue_labels"] == ["hydraflow-adr-drift", "hydraflow-find"]

    @pytest.mark.asyncio
    async def test_prompt_includes_adr_and_diff_evidence(
        self, ctx: TriageContext
    ) -> None:
        fake = FakeLLMClient(
            response={
                "classification": "real_drift",
                "rationale": "x",
                "section": "Decision",
            }
        )
        triage = AdrDriftTriageLLM(client=fake)
        await triage.classify(ctx)
        prompt = fake.calls[0]["prompt"]
        assert "ADR-0056" in prompt
        assert "We do X." in prompt
        assert "PR #8473" in prompt
        assert "src/agent.py" in prompt

    @pytest.mark.asyncio
    async def test_rejects_garbage_response(self, ctx: TriageContext) -> None:
        fake = FakeLLMClient(response={"classification": "not_a_real_value"})
        triage = AdrDriftTriageLLM(client=fake)
        with pytest.raises(ValueError, match="invalid TriageVerdict"):
            await triage.classify(ctx)

    @pytest.mark.asyncio
    async def test_rejects_missing_rationale(self, ctx: TriageContext) -> None:
        fake = FakeLLMClient(response={"classification": "consistent"})
        triage = AdrDriftTriageLLM(client=fake)
        with pytest.raises(ValueError, match="invalid TriageVerdict"):
            await triage.classify(ctx)
