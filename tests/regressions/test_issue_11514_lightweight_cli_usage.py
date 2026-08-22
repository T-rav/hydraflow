"""Regression: issue_refinement / sampled_audit / sampled_audit_adjudicate report usage.

Fixes #11514, #11515, #11516.

Live-ledger signature (``metrics/prompt/inferences.jsonl``, 2026-07-22 ..
2026-08-21): EVERY row from ``issue_refinement`` (187/187), ``sampled_audit``
(63/63) and ``sampled_audit_adjudicate`` (37/37) carried ``status=failed``,
``usage_status=unavailable``, ``token_source=estimated``,
``usage_anomaly=zero_usage_with_prompt`` and ``estimated_cost_usd=0`` — while
the adjudicate rows ran 30-240 s and returned 1.2-2.4k-char transcripts, i.e.
completed calls. Every other claude-CLI ``run_lightweight_agent`` source
(``wiki_compilation`` 667/667, ``term_proposer`` 563/563, ``triage_honeypot``
589/589, ...) showed the same; the same sources via the zai HTTP backend were
``success/available``.

Root cause: ``build_lightweight_command`` spawned ``claude -p <prompt> --model
<m>`` with NO ``--output-format json``. Bare text carries no usage, so the
seam recorded ``stats=None``; ``PromptTelemetry.record``'s zero-usage guard
then reclassified every successful non-trivial call as failed/$0. The only
claude one-shot row ever recorded ``success`` had ``prompt_chars=4`` — under
the guard's prompt threshold — which confirms the mechanism.

These pins drive each source's PRODUCTION client class (not a hand-built
``run_lightweight_agent`` call) through a replayed CLI JSON envelope and assert
both halves of the contract: the caller's parser still accepts the reply text,
and the telemetry row is usage-bearing.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from audit.adjudicate import parse_adjudication
from execution import SimpleResult
from issue_refinement import parse_dup_verdict
from issue_refinement_loop import _CLIRefinementLLM
from prompt_telemetry import PromptTelemetry
from sampled_audit_loop import (
    _CLIAdjudicatorLLM,
    _CLIAuditLLM,
    parse_audit_response,
)
from tests.helpers import ConfigFactory

# Recorded from ``claude -p ... --output-format json`` (CLI 2.1.238, 2026-08-21)
# with the per-source ``result`` swapped in. Token counts are the recorded ones.
_RECORDED_USAGE = {
    "input_tokens": 10,
    "cache_creation_input_tokens": 7431,
    "cache_read_input_tokens": 18134,
    "output_tokens": 45,
    "output_tokens_details": {"thinking_tokens": 37},
    "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
    "service_tier": "standard",
    "cache_creation": {
        "ephemeral_1h_input_tokens": 7431,
        "ephemeral_5m_input_tokens": 0,
    },
    "iterations": [
        {
            "input_tokens": 10,
            "output_tokens": 45,
            "cache_read_input_tokens": 18134,
            "cache_creation_input_tokens": 7431,
            "type": "message",
        }
    ],
}


def _recorded_envelope(result_text: str) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 84976,
            "duration_api_ms": 84100,
            "num_turns": 1,
            "result": result_text,
            "session_id": "fe99e068-2bfb-4292-b7c2-d5b48beed108",
            "total_cost_usd": 0.0178634,
            "usage": dict(_RECORDED_USAGE),
            "modelUsage": {
                "claude-sonnet-4-5": {
                    "inputTokens": 908,
                    "outputTokens": 56,
                    "cacheReadInputTokens": 18134,
                    "cacheCreationInputTokens": 7431,
                    "costUSD": 0.0178634,
                }
            },
            "uuid": "0b4f0d3c-2b0a-4a7e-9a3e-5f6d7c8b9a01",
        }
    )


class _ReplayRunner:
    def __init__(self, stdout: str) -> None:
        self._result = SimpleResult(stdout=stdout, returncode=0)
        self.commands: list[list[str]] = []

    async def run_simple(self, cmd, *, env=None, input=None, timeout=None, **_):
        self.commands.append(list(cmd))
        return self._result


# A prompt comfortably above the zero-usage guard's prompt threshold — the
# live prompts for these sources are 6-14k chars.
_PROMPT = "Judge this pair carefully.\n" * 300

_DUP_REPLY = json.dumps(
    {
        "verdict": "likely_dup",
        "canonical": 11514,
        "evidence": "Both report the same zero-usage telemetry signature.",
        "confidence": "high",
    }
)
_AUDIT_REPLY = json.dumps(
    {"verdict": "disagree", "findings": "The guard drops a real branch."}
)
_ADJUDICATE_REPLY = json.dumps(
    {"verdict": "upheld", "rationale": "The auditor's finding reproduces."}
)


def _usage_rows(config, source: str) -> list[dict[str, object]]:
    return [
        r
        for r in PromptTelemetry(config).load_inferences()
        if r.get("source") == source
    ]


def _assert_usage_bearing(row: dict[str, object]) -> None:
    assert row["status"] == "success", row
    assert row["usage_available"] is True, row
    assert row["usage_status"] == "available", row
    assert row["token_source"] == "actual", row
    assert row["input_tokens"] == _RECORDED_USAGE["input_tokens"]
    assert row["output_tokens"] == _RECORDED_USAGE["output_tokens"]
    assert row["cache_read_input_tokens"] == _RECORDED_USAGE["cache_read_input_tokens"]
    assert (
        row["cache_creation_input_tokens"]
        == _RECORDED_USAGE["cache_creation_input_tokens"]
    )
    assert int(row["total_tokens"]) > 0
    assert "usage_anomaly" not in row, "zero-usage guard must not fire on real usage"
    assert float(row["estimated_cost_usd"]) > 0
    # Priced as an Anthropic-shaped stream (#11573): cache not subtracted twice.
    assert row["usage_shape"] == "anthropic"


_Complete = Callable[[Any, str], Coroutine[Any, Any, str]]


@pytest.mark.asyncio
async def test_issue_refinement_spawn_reports_usage(tmp_path, monkeypatch) -> None:
    """Fixes #11514 — ``_CLIRefinementLLM.complete`` records token-accurate usage."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    runner = _ReplayRunner(_recorded_envelope(_DUP_REPLY))
    monkeypatch.setattr("issue_refinement_loop.get_default_runner", lambda: runner)

    text = await _CLIRefinementLLM(config).complete(_PROMPT)

    # The loop's parser sees the bare reply, exactly as before the fix.
    assert parse_dup_verdict(text).verdict == "likely_dup"
    assert "--output-format" in runner.commands[0]
    rows = _usage_rows(config, "issue_refinement")
    assert len(rows) == 1
    _assert_usage_bearing(rows[0])


@pytest.mark.asyncio
async def test_sampled_audit_spawn_reports_usage(tmp_path, monkeypatch) -> None:
    """Fixes #11515 — ``_CLIAuditLLM.audit`` records token-accurate usage."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    runner = _ReplayRunner(_recorded_envelope(_AUDIT_REPLY))
    monkeypatch.setattr("sampled_audit_loop.get_default_runner", lambda: runner)

    text = await _CLIAuditLLM(config).audit(prompt=_PROMPT)

    assert parse_audit_response(text) == ("disagree", "The guard drops a real branch.")
    rows = _usage_rows(config, "sampled_audit")
    assert len(rows) == 1
    _assert_usage_bearing(rows[0])


@pytest.mark.asyncio
async def test_sampled_audit_adjudicate_spawn_reports_usage(
    tmp_path, monkeypatch
) -> None:
    """Fixes #11516 — ``_CLIAdjudicatorLLM.adjudicate`` records token-accurate usage."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    runner = _ReplayRunner(_recorded_envelope(_ADJUDICATE_REPLY))
    monkeypatch.setattr("sampled_audit_loop.get_default_runner", lambda: runner)

    text = await _CLIAdjudicatorLLM(config).adjudicate(prompt=_PROMPT)

    assert parse_adjudication(text) == ("upheld", "The auditor's finding reproduces.")
    rows = _usage_rows(config, "sampled_audit_adjudicate")
    assert len(rows) == 1
    _assert_usage_bearing(rows[0])


@pytest.mark.asyncio
async def test_live_ledger_signature_is_gone_for_all_three(
    tmp_path, monkeypatch
) -> None:
    """The exact live signature — failed + unavailable + zero_usage_with_prompt + $0
    on a completed call — must not be reproducible for any of the three sources."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    clients: list[tuple[str, str, _Complete]] = [
        (
            "issue_refinement_loop.get_default_runner",
            _DUP_REPLY,
            lambda cfg, p: _CLIRefinementLLM(cfg).complete(p),
        ),
        (
            "sampled_audit_loop.get_default_runner",
            _AUDIT_REPLY,
            lambda cfg, p: _CLIAuditLLM(cfg).audit(prompt=p),
        ),
        (
            "sampled_audit_loop.get_default_runner",
            _ADJUDICATE_REPLY,
            lambda cfg, p: _CLIAdjudicatorLLM(cfg).adjudicate(prompt=p),
        ),
    ]
    for target, reply, complete in clients:
        runner = _ReplayRunner(_recorded_envelope(reply))
        monkeypatch.setattr(target, lambda _runner=runner: _runner)
        await complete(config, _PROMPT)

    rows = PromptTelemetry(config).load_inferences()
    by_source = {r["source"]: r for r in rows}
    assert set(by_source) == {
        "issue_refinement",
        "sampled_audit",
        "sampled_audit_adjudicate",
    }
    for source, row in by_source.items():
        signature = (
            row["status"],
            row["usage_status"],
            row.get("usage_anomaly"),
            row["estimated_cost_usd"],
        )
        assert signature != ("failed", "unavailable", "zero_usage_with_prompt", 0.0), (
            f"{source} still records the #11514 blind-spot signature: {row}"
        )
