"""Regression: the lightweight (run_simple) LLM spawn path detects credit + records telemetry.

Before WS-2.2, ``run_simple`` LLM callers silently swallowed credit exhaustion
(it arrives as ``rc != 0`` text, never an exception) and recorded no telemetry,
so the spend was invisible to the cost cap. ``runner_utils.run_lightweight_agent``
and ``raise_if_credit_exhausted`` close both gaps; ``term_proposer_runtime`` keeps
its own credit scan because it has no config to thread telemetry through.

Ref: ADR-0086 / dark-factory audit findings ``run-simple-agent-spawn-no-credit-detection``
and ``untelemetried-llm-spawners``.
"""

from __future__ import annotations

import pytest

from execution import SimpleResult
from prompt_telemetry import PromptTelemetry
from runner_utils import raise_if_credit_exhausted, run_lightweight_agent
from subprocess_util import CreditExhaustedError
from term_proposer_runtime import ClaudeCLIClient
from tests.helpers import ConfigFactory

_CREDIT_TEXT = "Claude usage limit reached. resets at 3pm (America/New_York)"


class _FakeRunner:
    """Minimal duck-typed SubprocessRunner returning a canned run_simple result."""

    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        raise_exc: BaseException | None = None,
    ) -> None:
        self._result = SimpleResult(stdout=stdout, stderr=stderr, returncode=returncode)
        self._raise_exc = raise_exc

    async def run_simple(
        self,
        cmd,
        *,
        input=None,
        timeout=None,
        env=None,
        cwd=None,  # noqa: A002
    ) -> SimpleResult:
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._result


class TestRunLightweightAgentCredit:
    @pytest.mark.asyncio
    async def test_raises_credit_exhausted_on_output_text(self, tmp_path) -> None:
        # run_simple surfaces credit-out as rc!=0 text, NOT an exception.
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        runner = _FakeRunner(stdout=_CREDIT_TEXT, returncode=1)

        with pytest.raises(CreditExhaustedError):
            await run_lightweight_agent(
                runner=runner,
                config=config,
                tool="claude",
                model="sonnet",
                prompt="summarize this",
                source="unit_test",
                timeout=5.0,
            )

    @pytest.mark.asyncio
    async def test_propagates_likely_bug(self, tmp_path) -> None:
        # A likely-bug exception (TypeError) must propagate, not soft-fail.
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        runner = _FakeRunner(raise_exc=TypeError("boom"))

        with pytest.raises(TypeError):
            await run_lightweight_agent(
                runner=runner,
                config=config,
                tool="claude",
                model="sonnet",
                prompt="x",
                source="unit_test",
                timeout=5.0,
            )

    @pytest.mark.asyncio
    async def test_transient_failure_collapses_to_soft_result(self, tmp_path) -> None:
        # A transient exception (OSError) becomes a soft rc=-1 result.
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        runner = _FakeRunner(raise_exc=OSError("network blip"))

        result = await run_lightweight_agent(
            runner=runner,
            config=config,
            tool="claude",
            model="sonnet",
            prompt="x",
            source="unit_test",
            timeout=5.0,
        )

        assert result.returncode == -1

    @pytest.mark.asyncio
    async def test_records_telemetry_row_with_source(self, tmp_path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        runner = _FakeRunner(stdout="ok", returncode=0)

        await run_lightweight_agent(
            runner=runner,
            config=config,
            tool="claude",
            model="sonnet",
            prompt="a non-trivial prompt for telemetry",
            source="unit_test_source",
            timeout=5.0,
        )

        rows = PromptTelemetry(config).load_inferences()
        assert any(row.get("source") == "unit_test_source" for row in rows), (
            "run_lightweight_agent must record a PromptTelemetry inference row so the "
            "lightweight spawn's spend is visible to the cost cap"
        )


class TestRaiseIfCreditExhausted:
    def test_raises_on_credit_text(self) -> None:
        with pytest.raises(CreditExhaustedError):
            raise_if_credit_exhausted(_CREDIT_TEXT, "", "claude")

    def test_noop_on_benign_output(self) -> None:
        # No exception on ordinary output.
        raise_if_credit_exhausted("some normal model output", "", "claude")


class TestTermProposerCreditDetection:
    @pytest.mark.asyncio
    async def test_complete_structured_raises_credit_exhausted(self) -> None:
        # Regression: term_proposer's config-less CLI path previously raised a
        # generic RuntimeError on credit-out; it must now raise CreditExhaustedError.
        runner = _FakeRunner(stdout=_CREDIT_TEXT, returncode=1)
        client = ClaudeCLIClient(runner=runner)

        with pytest.raises(CreditExhaustedError):
            await client.complete_structured(prompt="propose terms", schema={})
