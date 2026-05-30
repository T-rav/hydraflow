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


class TestCostRollupCountsEstimatedSpend:
    """WS-2.2 self-review S2: the cost-cap rollup re-prices from token counts, so a
    char-estimated lightweight row (0 actual tokens) must fall back to the stored
    estimated_cost_usd — otherwise lightweight spend re-prices to $0 and never
    counts toward the daily cost cap."""

    def test_char_estimated_row_counts_via_stored_estimate(self, tmp_path) -> None:
        import json
        from datetime import UTC, datetime

        from dashboard_routes._cost_rollups import iter_priced_inferences
        from model_pricing import load_pricing

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        path = config.data_path("metrics", "prompt", "inferences.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            # char-estimated lightweight row: 0 actual tokens, stored estimate > 0
            {
                "timestamp": "2026-05-30T12:00:00+00:00",
                "model": "claude-sonnet-4-5",
                "source": "transcript_summary",
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_usd": 0.05,
            },
            # genuinely-zero row: no actual tokens AND no stored estimate -> stays 0
            {
                "timestamp": "2026-05-30T12:01:00+00:00",
                "model": "claude-sonnet-4-5",
                "source": "transcript_summary",
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_usd": 0.0,
            },
        ]
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

        since = datetime(2026, 5, 1, tzinfo=UTC)
        until = datetime(2026, 6, 1, tzinfo=UTC)
        priced = list(
            iter_priced_inferences(
                config, since=since, until=until, pricing=load_pricing()
            )
        )

        costs = sorted(r["cost_usd"] for r in priced)
        assert costs == [0.0, 0.05], (
            "char-estimated row must contribute its stored estimate to the cost cap; "
            f"got {costs}"
        )


class TestStreamClaudeWithTelemetry:
    """WS-2.2 self-review S4: the streaming wrapper (backing acceptance_criteria,
    report_issue_loop, sentry_loop, verification_judge) records telemetry on success
    AND failure, with issue/pr derived from event_data."""

    @pytest.mark.asyncio
    async def test_records_row_on_success(self, tmp_path) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from runner_utils import StreamConfig, stream_claude_with_telemetry

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        bus = MagicMock()
        bus.current_session_id = "sess-1"
        with patch(
            "runner_utils.stream_claude_process",
            new=AsyncMock(return_value="the transcript"),
        ):
            out = await stream_claude_with_telemetry(
                config=config,
                cmd=["claude", "-p", "x", "--model", "sonnet"],
                prompt="a non-trivial streaming prompt",
                cwd=tmp_path,
                active_procs=set(),
                event_bus=bus,
                event_data={"source": "ac_generator", "issue": 7, "pr": 9},
                logger=MagicMock(),
                stream_config=StreamConfig(),
            )
        assert out == "the transcript"
        rows = PromptTelemetry(config).load_inferences()
        match = [r for r in rows if r.get("source") == "ac_generator"]
        assert match, "streaming wrapper must record a telemetry row on success"
        assert match[-1]["issue_number"] == 7
        assert match[-1]["pr_number"] == 9

    @pytest.mark.asyncio
    async def test_records_row_when_stream_raises(self, tmp_path) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from runner_utils import StreamConfig, stream_claude_with_telemetry

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        bus = MagicMock()
        bus.current_session_id = "sess-2"
        with (
            patch(
                "runner_utils.stream_claude_process",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            pytest.raises(RuntimeError),
        ):
            await stream_claude_with_telemetry(
                config=config,
                cmd=["claude", "-p", "x", "--model", "sonnet"],
                prompt="a non-trivial streaming prompt",
                cwd=tmp_path,
                active_procs=set(),
                event_bus=bus,
                event_data={"source": "sentry_ingest"},
                logger=MagicMock(),
                stream_config=StreamConfig(),
            )
        rows = PromptTelemetry(config).load_inferences()
        match = [r for r in rows if r.get("source") == "sentry_ingest"]
        assert match, (
            "wrapper must record a row in the finally even when the stream raises"
        )
        assert match[-1]["status"] == "failed"
