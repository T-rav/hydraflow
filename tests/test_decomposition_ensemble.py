"""Tests for DecompositionEnsemble (ADR-0105 decompose-to-converge, Task 3 refine).

The ensemble is a GENUINE two-pass design: a direction call proposes a
candidate split, and a SEPARATE, independent validation call adversarially
critiques it and owns ``should_decompose``/``confidence``. These tests mock
the seam (``run_lightweight_agent``) to return one reply per call, in order,
so the assertions can pin exactly which call is direction and which is
validation -- proving the two are genuinely independent (validation CAN
overturn a direction pass that proposed a split), not one completion
rationalizing itself.

The LLM seam is always mocked here -- these tests never call a real model.
``DecompositionEnsemble._execute_ensemble`` does a deferred
``from runner_utils import run_lightweight_agent`` (matching every other
lightweight caller in the codebase, e.g. ``adr_reviewer.py``,
``term_proposer_runtime.py``), so the seam is patched at its definition site,
``runner_utils.run_lightweight_agent`` -- not at the importing module's
namespace, which never binds the name at module scope.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from decomposition_ensemble import DecompositionEnsemble
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


def _ensemble(monkeypatch, *, results):
    """Wire a DecompositionEnsemble whose seam call returns each of *results*
    in turn (as ``SimpleResult(stdout=..., returncode=0)``), and return the
    ensemble plus a list that records every prompt the seam was called with
    (in call order -- so ``calls[0]`` is always the first direction call,
    ``calls[1]`` the first validation call, ``calls[2]`` a retried direction
    call, etc).
    """
    from execution import SimpleResult

    calls: list[str] = []
    remaining = list(results)

    async def _fake_seam(**kwargs):
        calls.append(kwargs["prompt"])
        stdout = remaining.pop(0) if remaining else remaining[-1]
        return SimpleResult(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr("runner_utils.run_lightweight_agent", _fake_seam)
    ensemble = DecompositionEnsemble(runner=AsyncMock(), config=ConfigFactory.create())
    return ensemble, calls


def _direction_reply(**fields) -> str:
    fields.setdefault("epic_title", "Epic: split the frobnicator")
    fields.setdefault("epic_body", "## Sub-issues\n\n- [ ] Child 1\n- [ ] Child 2")
    fields.setdefault(
        "children",
        [
            {"title": "Extract the parser", "body": "Split out parsing."},
            {"title": "Extract the renderer", "body": "Split out rendering."},
        ],
    )
    fields.setdefault("rationale", "Two independently shippable layers.")
    return json.dumps(fields)


def _validation_reply(**fields) -> str:
    fields.setdefault("decision", "approve")
    fields.setdefault("confidence", "high")
    fields.setdefault("reasoning", "Sound, non-overlapping split.")
    return json.dumps(fields)


class TestDecompositionEnsembleAccept:
    """A sound split: direction proposes, validation APPROVEs -- no retry."""

    @pytest.mark.asyncio
    async def test_sound_split_accepts_via_two_independent_calls(
        self, monkeypatch
    ) -> None:
        direction = _direction_reply()
        validation = _validation_reply(
            decision="approve",
            confidence="high",
            reasoning="Two independently shippable layers, no overlap.",
        )
        ensemble, calls = _ensemble(monkeypatch, results=[direction, validation])
        task = TaskFactory.create(id=101, title="Fix the frobnicator")

        result = await ensemble.decide(
            task=task, stall_context="stalled after 3 attempts", doc_context="", depth=0
        )

        assert result.should_decompose is True
        assert len(result.children) >= 2
        assert result.confidence == "high"
        assert result.epic_title == "Epic: split the frobnicator"
        assert len(calls) == 2, (
            "accept requires exactly one direction + one validation call"
        )

        # The two calls are genuinely separate seam invocations with
        # distinct prompts -- direction proposes, validation critiques.
        assert "Direction phase" in calls[0]
        assert "Validation phase" in calls[1]
        # Validation's prompt is seeded with direction's actual proposed
        # split (not just replayed blind) -- proving it received the output
        # of the direction call rather than being independent of it entirely.
        assert "Extract the parser" in calls[1]
        assert "Extract the renderer" in calls[1]
        assert "Epic: split the frobnicator" in calls[1]


class TestDecompositionEnsembleValidationOverturnsDirection:
    """Validation is independent: it can REJECT a split direction proposed.

    This is the crux of the two-pass design -- a single completion that
    proposes AND validates its own split would never produce this shape.
    """

    @pytest.mark.asyncio
    async def test_validation_rejects_clone_children_high_confidence_no_retry(
        self, monkeypatch
    ) -> None:
        # Direction proposes a split -- but the "children" are clones with
        # no independent value (same work stated twice).
        direction = _direction_reply(
            epic_title="Epic: fix the parser",
            children=[
                {"title": "Fix the parser bug", "body": "Fix the off-by-one."},
                {"title": "Fix the parser issue", "body": "Fix the off-by-one bug."},
            ],
            rationale="Split by... uh, two tickets for the same fix.",
        )
        validation = _validation_reply(
            decision="reject",
            confidence="high",
            reasoning="Children are near-duplicate clones of the same fix -- no "
            "independent value.",
        )
        ensemble, calls = _ensemble(monkeypatch, results=[direction, validation])
        task = TaskFactory.create(id=102, title="Fix off-by-one in parser")

        result = await ensemble.decide(
            task=task, stall_context="stalled after 3 attempts", doc_context="", depth=0
        )

        assert result.should_decompose is False, (
            "validation must be able to overturn a split direction proposed"
        )
        assert result.confidence == "high"
        assert len(calls) == 2, "a high-confidence validation decline must not retry"
        # Proves the two calls are independent: direction proposed a split
        # (it authored real children), but the final decision is False
        # because validation is the sole owner of should_decompose and
        # disagreed -- exactly the "independent second look" the two-pass
        # design exists for.
        assert "Fix the parser bug" in calls[1], (
            "validation's prompt must be seeded with direction's actual proposal"
        )


class TestDecompositionEnsembleDeclineLowConfidence:
    """A low-confidence or garbled decline is retried once (whole pair), then final."""

    @pytest.mark.asyncio
    async def test_low_confidence_validation_decline_retries_whole_pair_once(
        self, monkeypatch
    ) -> None:
        direction_1 = _direction_reply(rationale="First candidate, shaky split.")
        validation_1 = _validation_reply(
            decision="revise",
            confidence="low",
            reasoning="Unclear whether these are truly independent.",
        )
        direction_2 = _direction_reply(rationale="Second attempt, same candidate.")
        validation_2 = _validation_reply(
            decision="revise",
            confidence="medium",
            reasoning="Still unclear on second look; declining.",
        )
        ensemble, calls = _ensemble(
            monkeypatch,
            results=[direction_1, validation_1, direction_2, validation_2],
        )
        task = TaskFactory.create(id=103, title="Untangle the legacy importer")

        result = await ensemble.decide(
            task=task, stall_context="stalled after 3 attempts", doc_context="", depth=1
        )

        assert len(calls) == 4, (
            "a low-confidence validation decline must retry the WHOLE PAIR "
            "(direction + validation) exactly once"
        )
        assert result.should_decompose is False
        # The retry result is final regardless of its own confidence -- no
        # unbounded retry loop even if the second pass is still not "high".
        assert result.confidence == "medium"

    @pytest.mark.asyncio
    async def test_garbled_direction_reply_counts_as_low_confidence_and_retries(
        self, monkeypatch
    ) -> None:
        garbled_direction = "not valid json at all"
        direction_2 = _direction_reply()
        validation_2 = _validation_reply(
            decision="reject",
            confidence="high",
            reasoning="Confirmed atomic on retry.",
        )
        ensemble, calls = _ensemble(
            monkeypatch, results=[garbled_direction, direction_2, validation_2]
        )
        task = TaskFactory.create(id=104, title="Some stalled task")

        result = await ensemble.decide(
            task=task, stall_context="stalled", doc_context="", depth=0
        )

        # Pass 1: direction is garbled -> nothing to validate, so validation
        # is never called for that pass (1 call). Pass 2 (retry): direction
        # succeeds, validation is called (2 more calls). Total 3.
        assert len(calls) == 3, (
            "a garbled direction reply must be retried (as the whole pair) "
            "once, without wasting a validation call on unparseable output"
        )
        assert result.should_decompose is False
        assert result.confidence == "high"

    @pytest.mark.asyncio
    async def test_direction_candidate_with_too_few_children_retries_without_validating(
        self, monkeypatch
    ) -> None:
        malformed_direction = _direction_reply(
            children=[{"title": "Only one child", "body": ""}]
        )
        direction_2 = _direction_reply()
        validation_2 = _validation_reply(
            decision="reject",
            confidence="high",
            reasoning="Actually atomic.",
        )
        ensemble, calls = _ensemble(
            monkeypatch, results=[malformed_direction, direction_2, validation_2]
        )
        task = TaskFactory.create(id=105, title="Some stalled task")

        result = await ensemble.decide(
            task=task, stall_context="stalled", doc_context="", depth=0
        )

        assert len(calls) == 3
        assert result.should_decompose is False

    @pytest.mark.asyncio
    async def test_garbled_validation_reply_counts_as_low_confidence_and_retries(
        self, monkeypatch
    ) -> None:
        direction_1 = _direction_reply()
        garbled_validation = "not valid json at all"
        direction_2 = _direction_reply()
        validation_2 = _validation_reply(
            decision="approve",
            confidence="high",
            reasoning="Sound split confirmed on retry.",
        )
        ensemble, calls = _ensemble(
            monkeypatch,
            results=[direction_1, garbled_validation, direction_2, validation_2],
        )
        task = TaskFactory.create(id=108, title="Some stalled task")

        result = await ensemble.decide(
            task=task, stall_context="stalled", doc_context="", depth=0
        )

        assert len(calls) == 4, (
            "a garbled validation reply must retry the whole pair once"
        )
        assert result.should_decompose is True
        assert result.confidence == "high"


class TestDecompositionEnsemblePromptContext:
    """doc_context and stall_context are injected verbatim into the direction prompt."""

    @pytest.mark.asyncio
    async def test_doc_context_and_stall_context_reach_the_direction_prompt(
        self, monkeypatch
    ) -> None:
        direction = _direction_reply()
        validation = _validation_reply(decision="reject", confidence="high")
        ensemble, calls = _ensemble(monkeypatch, results=[direction, validation])
        task = TaskFactory.create(id=106, title="Some stalled task")

        await ensemble.decide(
            task=task,
            stall_context="STALL_MARKER: three preflight attempts failed",
            doc_context="DOC_MARKER: relevant ADR excerpt",
            depth=2,
        )

        assert "STALL_MARKER: three preflight attempts failed" in calls[0]
        assert "DOC_MARKER: relevant ADR excerpt" in calls[0]
        # Validation also receives the same context, so its architecture
        # consistency / budget checks aren't blind to it.
        assert "STALL_MARKER: three preflight attempts failed" in calls[1]
        assert "DOC_MARKER: relevant ADR excerpt" in calls[1]


class TestDecompositionEnsembleCreditExhaustion:
    """A credit-exhaustion signal from the seam must propagate, not be swallowed."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_out_of_decide(self, monkeypatch) -> None:
        from subprocess_util import CreditExhaustedError

        async def _raising_seam(**kwargs):
            raise CreditExhaustedError("out of credits")

        monkeypatch.setattr("runner_utils.run_lightweight_agent", _raising_seam)
        ensemble = DecompositionEnsemble(
            runner=AsyncMock(), config=ConfigFactory.create()
        )
        task = TaskFactory.create(id=107, title="Some stalled task")

        with pytest.raises(CreditExhaustedError):
            await ensemble.decide(
                task=task, stall_context="stalled", doc_context="", depth=0
            )

    @pytest.mark.asyncio
    async def test_credit_exhausted_from_validation_call_propagates(
        self, monkeypatch
    ) -> None:
        """Credit exhaustion surfacing on the SECOND (validation) call must
        also propagate -- not just when it happens on the first call.
        """
        from execution import SimpleResult
        from subprocess_util import CreditExhaustedError

        call_count = 0

        async def _seam(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return SimpleResult(stdout=_direction_reply(), stderr="", returncode=0)
            raise CreditExhaustedError("out of credits mid-ensemble")

        monkeypatch.setattr("runner_utils.run_lightweight_agent", _seam)
        ensemble = DecompositionEnsemble(
            runner=AsyncMock(), config=ConfigFactory.create()
        )
        task = TaskFactory.create(id=109, title="Some stalled task")

        with pytest.raises(CreditExhaustedError):
            await ensemble.decide(
                task=task, stall_context="stalled", doc_context="", depth=0
            )
        assert call_count == 2
