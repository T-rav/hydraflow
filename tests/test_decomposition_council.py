"""Tests for DecompositionCouncil (ADR-0105 decompose-to-converge, Task 3).

The LLM seam (``run_lightweight_agent``) is always mocked here -- these tests
never call a real model. ``DecompositionCouncil._execute_council`` does a
deferred ``from runner_utils import run_lightweight_agent`` (matching every
other lightweight caller in the codebase, e.g. ``adr_reviewer.py``,
``term_proposer_runtime.py``), so the seam is patched at its definition site,
``runner_utils.run_lightweight_agent`` -- not at the importing module's
namespace, which never binds the name at module scope.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from decomposition_council import DecompositionCouncil
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


def _council(monkeypatch, *, results):
    """Wire a DecompositionCouncil whose seam call returns each of *results*
    in turn (as ``SimpleResult(stdout=..., returncode=0)``), and return the
    council plus a list that records every prompt the seam was called with.
    """
    from execution import SimpleResult

    calls: list[str] = []
    remaining = list(results)

    async def _fake_seam(**kwargs):
        calls.append(kwargs["prompt"])
        stdout = remaining.pop(0) if remaining else remaining[-1]
        return SimpleResult(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr("runner_utils.run_lightweight_agent", _fake_seam)
    council = DecompositionCouncil(runner=AsyncMock(), config=ConfigFactory.create())
    return council, calls


def _reply(**fields) -> str:
    return json.dumps(fields)


class TestDecompositionCouncilAccept:
    """A sound split is accepted on the first pass -- no retry."""

    @pytest.mark.asyncio
    async def test_sound_split_accepts_with_children_and_high_confidence(
        self, monkeypatch
    ) -> None:
        reply = _reply(
            should_decompose=True,
            confidence="high",
            epic_title="Epic: split the frobnicator",
            epic_body="## Sub-issues\n\n- [ ] Child 1\n- [ ] Child 2",
            children=[
                {"title": "Extract the parser", "body": "Split out parsing."},
                {"title": "Extract the renderer", "body": "Split out rendering."},
            ],
            reasoning="Two independently shippable layers.",
        )
        council, calls = _council(monkeypatch, results=[reply])
        task = TaskFactory.create(id=101, title="Fix the frobnicator")

        result = await council.decide(
            task=task, stall_context="stalled after 3 attempts", doc_context="", depth=0
        )

        assert result.should_decompose is True
        assert len(result.children) >= 2
        assert result.confidence == "high"
        assert result.epic_title == "Epic: split the frobnicator"
        assert len(calls) == 1, "an accept must not retry"


class TestDecompositionCouncilDeclineHighConfidence:
    """A high-confidence atomic/clone decline is final immediately -- no retry."""

    @pytest.mark.asyncio
    async def test_atomic_decline_is_final_with_no_retry(self, monkeypatch) -> None:
        reply = _reply(
            should_decompose=False,
            confidence="high",
            reasoning="This is a single atomic bug fix; splitting it would "
            "produce clone children with no independent value.",
        )
        council, calls = _council(monkeypatch, results=[reply])
        task = TaskFactory.create(id=102, title="Fix off-by-one in parser")

        result = await council.decide(
            task=task, stall_context="stalled after 3 attempts", doc_context="", depth=0
        )

        assert result.should_decompose is False
        assert result.confidence == "high"
        assert len(calls) == 1, "a high-confidence decline must not retry"


class TestDecompositionCouncilDeclineLowConfidence:
    """A low-confidence or garbled decline is retried once, then treated as final."""

    @pytest.mark.asyncio
    async def test_low_confidence_decline_retries_once_then_final(
        self, monkeypatch
    ) -> None:
        first = _reply(
            should_decompose=False,
            confidence="low",
            reasoning="Unclear whether this can be split.",
        )
        second = _reply(
            should_decompose=False,
            confidence="medium",
            reasoning="Still unclear on second look; declining.",
        )
        council, calls = _council(monkeypatch, results=[first, second])
        task = TaskFactory.create(id=103, title="Untangle the legacy importer")

        result = await council.decide(
            task=task, stall_context="stalled after 3 attempts", doc_context="", depth=1
        )

        assert len(calls) == 2, "a low-confidence decline must retry exactly once"
        assert result.should_decompose is False
        # The retry result is final regardless of its own confidence -- no
        # unbounded retry loop even if the second pass is still not "high".
        assert result.confidence == "medium"

    @pytest.mark.asyncio
    async def test_garbled_reply_counts_as_low_confidence_and_retries(
        self, monkeypatch
    ) -> None:
        garbled = "not valid json at all"
        clean_decline = _reply(
            should_decompose=False,
            confidence="high",
            reasoning="Confirmed atomic on retry.",
        )
        council, calls = _council(monkeypatch, results=[garbled, clean_decline])
        task = TaskFactory.create(id=104, title="Some stalled task")

        result = await council.decide(
            task=task, stall_context="stalled", doc_context="", depth=0
        )

        assert len(calls) == 2, (
            "a garbled reply must be retried once like a low-confidence decline"
        )
        assert result.should_decompose is False
        assert result.confidence == "high"

    @pytest.mark.asyncio
    async def test_accept_with_too_few_children_is_treated_as_garbled_and_retries(
        self, monkeypatch
    ) -> None:
        malformed_accept = _reply(
            should_decompose=True,
            confidence="high",
            epic_title="Epic: oops",
            epic_body="",
            children=[{"title": "Only one child", "body": ""}],
            reasoning="Forgot the second child.",
        )
        clean_decline = _reply(
            should_decompose=False,
            confidence="high",
            reasoning="Actually atomic.",
        )
        council, calls = _council(
            monkeypatch, results=[malformed_accept, clean_decline]
        )
        task = TaskFactory.create(id=105, title="Some stalled task")

        result = await council.decide(
            task=task, stall_context="stalled", doc_context="", depth=0
        )

        assert len(calls) == 2
        assert result.should_decompose is False


class TestDecompositionCouncilPromptContext:
    """doc_context and stall_context are injected verbatim into the prompt."""

    @pytest.mark.asyncio
    async def test_doc_context_and_stall_context_reach_the_prompt(
        self, monkeypatch
    ) -> None:
        reply = _reply(should_decompose=False, confidence="high", reasoning="atomic")
        council, calls = _council(monkeypatch, results=[reply])
        task = TaskFactory.create(id=106, title="Some stalled task")

        await council.decide(
            task=task,
            stall_context="STALL_MARKER: three preflight attempts failed",
            doc_context="DOC_MARKER: relevant ADR excerpt",
            depth=2,
        )

        assert "STALL_MARKER: three preflight attempts failed" in calls[0]
        assert "DOC_MARKER: relevant ADR excerpt" in calls[0]


class TestDecompositionCouncilCreditExhaustion:
    """A credit-exhaustion signal from the seam must propagate, not be swallowed."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_out_of_decide(self, monkeypatch) -> None:
        from subprocess_util import CreditExhaustedError

        async def _raising_seam(**kwargs):
            raise CreditExhaustedError("out of credits")

        monkeypatch.setattr("runner_utils.run_lightweight_agent", _raising_seam)
        council = DecompositionCouncil(
            runner=AsyncMock(), config=ConfigFactory.create()
        )
        task = TaskFactory.create(id=107, title="Some stalled task")

        with pytest.raises(CreditExhaustedError):
            await council.decide(
                task=task, stall_context="stalled", doc_context="", depth=0
            )
