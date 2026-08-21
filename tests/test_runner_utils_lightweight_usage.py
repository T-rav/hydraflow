"""The lightweight (one-shot ``run_simple``) Claude spawn reports real usage.

``run_lightweight_agent`` -> ``_claude_cli_complete`` spawns
``claude -p ... --output-format json``. The CLI answers with ONE JSON result
envelope (``type: result`` + ``result`` text + ``usage``). The seam unwraps it:
callers keep receiving the bare reply text in ``SimpleResult.stdout`` exactly
as before, and the envelope's ``usage`` flows into the PromptTelemetry row so
the spend is token-accurate instead of being reclassified as a zero-usage
failure (#11514 / #11515 / #11516).
"""

from __future__ import annotations

import json

import pytest

from execution import SimpleResult
from prompt_telemetry import PromptTelemetry
from runner_utils import _claude_cli_complete, run_lightweight_agent
from subprocess_util import CreditExhaustedError
from tests.helpers import ConfigFactory

_CREDIT_TEXT = "Claude usage limit reached. resets at 3pm (America/New_York)"


def _envelope(result_text: str, **overrides: object) -> str:
    body: dict[str, object] = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 1339,
        "num_turns": 1,
        "result": result_text,
        "session_id": "fe99e068-2bfb-4292-b7c2-d5b48beed108",
        "total_cost_usd": 0.0178634,
        "usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 7431,
            "cache_read_input_tokens": 18134,
            "output_tokens": 45,
            "service_tier": "standard",
        },
    }
    body.update(overrides)
    return json.dumps(body)


class _Runner:
    """Duck-typed SubprocessRunner replaying a canned ``run_simple`` result."""

    def __init__(self, stdout: str, *, stderr: str = "", returncode: int = 0) -> None:
        self._result = SimpleResult(stdout=stdout, stderr=stderr, returncode=returncode)
        self.commands: list[list[str]] = []

    async def run_simple(self, cmd, *, env=None, input=None, timeout=None, **_):
        self.commands.append(list(cmd))
        return self._result


class TestClaudeCliCompleteUnwrapsEnvelope:
    @pytest.mark.asyncio
    async def test_stdout_is_the_reply_text_and_usage_out_is_filled(self) -> None:
        usage_out: dict[str, object] = {}
        runner = _Runner(_envelope("pong"))

        result = await _claude_cli_complete(
            runner=runner,
            tool="claude",
            model="sonnet",
            prompt="say pong",
            timeout=5.0,
            gh_token="",
            isolate_user_settings=True,
            usage_out=usage_out,
        )

        assert result.returncode == 0
        assert result.stdout == "pong"
        assert usage_out["input_tokens"] == 10
        assert usage_out["output_tokens"] == 45
        assert usage_out["cache_creation_input_tokens"] == 7431
        assert usage_out["cache_read_input_tokens"] == 18134
        assert usage_out["usage_available"] is True
        assert usage_out["usage_status"] == "available"
        # The spawn asked for the envelope in the first place.
        assert "--output-format" in runner.commands[0]

    @pytest.mark.asyncio
    async def test_plain_text_reply_passes_through_unchanged(self) -> None:
        # An older CLI / a fake that ignores --output-format still works: the
        # text is returned verbatim and usage simply stays unavailable.
        usage_out: dict[str, object] = {}
        runner = _Runner("bare text reply")

        result = await _claude_cli_complete(
            runner=runner,
            tool="claude",
            model="sonnet",
            prompt="p",
            timeout=5.0,
            gh_token="",
            isolate_user_settings=True,
            usage_out=usage_out,
        )

        assert result.stdout == "bare text reply"
        assert usage_out == {}

    @pytest.mark.asyncio
    async def test_callers_json_reply_is_not_mistaken_for_the_envelope(self) -> None:
        # Contract workers reply in JSON themselves. Without the ``type: result``
        # discriminator that JSON must reach the caller untouched.
        reply = json.dumps({"verdict": "agree", "findings": ""})
        runner = _Runner(reply)

        result = await _claude_cli_complete(
            runner=runner,
            tool="claude",
            model="sonnet",
            prompt="p",
            timeout=5.0,
            gh_token="",
            isolate_user_settings=True,
            usage_out={},
        )

        assert result.stdout == reply

    @pytest.mark.asyncio
    async def test_is_error_envelope_is_a_failed_result(self) -> None:
        # The CLI can exit 0 while flagging ``is_error`` (max turns, mid-run
        # API error). Callers branch on ``returncode``; an error envelope must
        # not masquerade as a completed reply.
        runner = _Runner(
            _envelope(
                "API Error: overloaded", is_error=True, subtype="error_during_execution"
            )
        )

        result = await _claude_cli_complete(
            runner=runner,
            tool="claude",
            model="sonnet",
            prompt="p",
            timeout=5.0,
            gh_token="",
            isolate_user_settings=True,
            usage_out={},
        )

        assert result.returncode != 0
        assert result.stdout == "API Error: overloaded"
        assert "overloaded" in result.stderr

    @pytest.mark.asyncio
    async def test_nonzero_exit_is_preserved_through_unwrap(self) -> None:
        runner = _Runner(_envelope("partial", is_error=True), returncode=1)

        result = await _claude_cli_complete(
            runner=runner,
            tool="claude",
            model="sonnet",
            prompt="p",
            timeout=5.0,
            gh_token="",
            isolate_user_settings=True,
            usage_out={},
        )

        assert result.returncode == 1

    @pytest.mark.asyncio
    async def test_credit_exhaustion_inside_the_envelope_still_raises(self) -> None:
        # Credit-out arrives as rc!=0 TEXT on this path. It now arrives wrapped
        # in the envelope's ``result`` — the scan must see the unwrapped text.
        runner = _Runner(_envelope(_CREDIT_TEXT, is_error=True), returncode=1)

        with pytest.raises(CreditExhaustedError):
            await _claude_cli_complete(
                runner=runner,
                tool="claude",
                model="sonnet",
                prompt="p",
                timeout=5.0,
                gh_token="",
                isolate_user_settings=True,
                usage_out={},
            )

    @pytest.mark.asyncio
    async def test_usage_out_none_is_tolerated(self) -> None:
        runner = _Runner(_envelope("pong"))

        result = await _claude_cli_complete(
            runner=runner,
            tool="claude",
            model="sonnet",
            prompt="p",
            timeout=5.0,
            gh_token="",
            isolate_user_settings=True,
        )

        assert result.stdout == "pong"


class TestRunLightweightAgentRecordsRealUsage:
    @pytest.mark.asyncio
    async def test_envelope_usage_lands_in_the_telemetry_row(self, tmp_path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        runner = _Runner(_envelope("pong"))

        result = await run_lightweight_agent(
            runner=runner,
            config=config,
            tool="claude",
            model="sonnet",
            prompt="a non-trivial prompt " * 20,
            source="unit_lightweight_usage",
            timeout=5.0,
        )

        assert result.returncode == 0
        assert result.stdout == "pong"
        rows = [
            r
            for r in PromptTelemetry(config).load_inferences()
            if r.get("source") == "unit_lightweight_usage"
        ]
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "success"
        assert row["usage_available"] is True
        assert row["usage_status"] == "available"
        assert row["token_source"] == "actual"
        assert row["input_tokens"] == 10
        assert row["output_tokens"] == 45
        assert row["cache_creation_input_tokens"] == 7431
        assert row["cache_read_input_tokens"] == 18134
        assert row["total_tokens"] > 0
        assert "usage_anomaly" not in row
        assert row["estimated_cost_usd"] > 0
        assert row["raw_usage"][0]["path"] == "usage"
        # #11573: the CLI envelope is Anthropic-shaped (input_tokens EXCLUDES
        # cache); the row must carry that stamp so pricing never subtracts the
        # cache from an already-exclusive input count.
        assert row["usage_shape"] == "anthropic"

    @pytest.mark.asyncio
    async def test_plain_text_reply_still_records_a_row(self, tmp_path) -> None:
        # Legacy behaviour is preserved for a text-only reply: the row exists,
        # usage is honestly unavailable (the guard keeps doing its job).
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        runner = _Runner("bare text reply")

        await run_lightweight_agent(
            runner=runner,
            config=config,
            tool="claude",
            model="sonnet",
            prompt="a non-trivial prompt " * 20,
            source="unit_lightweight_text",
            timeout=5.0,
        )

        rows = [
            r
            for r in PromptTelemetry(config).load_inferences()
            if r.get("source") == "unit_lightweight_text"
        ]
        assert len(rows) == 1
        assert rows[0]["usage_status"] == "unavailable"
        assert rows[0]["token_source"] == "estimated"

    @pytest.mark.asyncio
    async def test_error_envelope_records_a_failed_row_with_its_usage(
        self, tmp_path
    ) -> None:
        # A flagged error still burned tokens; the row is failed AND carries the
        # usage the CLI reported, so the cost cap sees the spend.
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        runner = _Runner(
            _envelope("API Error: overloaded", is_error=True, subtype="error_max_turns")
        )

        result = await run_lightweight_agent(
            runner=runner,
            config=config,
            tool="claude",
            model="sonnet",
            prompt="a non-trivial prompt " * 20,
            source="unit_lightweight_error",
            timeout=5.0,
        )

        assert result.returncode != 0
        rows = [
            r
            for r in PromptTelemetry(config).load_inferences()
            if r.get("source") == "unit_lightweight_error"
        ]
        assert len(rows) == 1
        assert rows[0]["status"] == "failed"
        assert rows[0]["usage_available"] is True
        assert rows[0]["output_tokens"] == 45
