"""Tests for AdrDriftResolverLLMClient (#9976).

Mirrors ``test_term_proposer_runtime.py::TestClaudeCLIClient``: the seam
(``runner_utils.run_lightweight_agent``) is mocked, so this only asserts
the adapter's own wiring (JSON extraction, error surfacing, issue context
threaded through) — the seam's own credit/gate/telemetry behavior is
covered by ``test_llm_provider.py``. No real model calls anywhere here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from adr_drift_resolver_runtime import AdrDriftResolverLLMClient


def _client(monkeypatch, *, stdout="", returncode=0):
    from execution import SimpleResult
    from tests.helpers import ConfigFactory

    captured: dict = {}

    async def _fake_seam(**kwargs):
        captured.update(kwargs)
        return SimpleResult(stdout=stdout, stderr="boom", returncode=returncode)

    monkeypatch.setattr("runner_utils.run_lightweight_agent", _fake_seam)
    client = AdrDriftResolverLLMClient(
        runner=AsyncMock(),
        config=ConfigFactory.create(),
        tool="claude",
        model="sonnet",
        provider="claude",
        timeout=90,
    )
    return client, captured


class TestAdrDriftResolverLLMClient:
    async def test_returns_parsed_json(self, monkeypatch) -> None:
        client, _ = _client(
            monkeypatch,
            stdout='{"classification": "consistent", "rationale": "x", "section": ""}',
        )
        out = await client.complete_structured(
            prompt="hi",
            schema={},
            issue_number=9001,
            issue_labels=["hydraflow-adr-drift"],
        )
        assert out["classification"] == "consistent"

    async def test_extracts_json_from_markdown_fence(self, monkeypatch) -> None:
        client, _ = _client(
            monkeypatch,
            stdout='Here:\n```json\n{"classification": "real_drift", "rationale": "y"}\n```\n',
        )
        out = await client.complete_structured(
            prompt="hi", schema={}, issue_number=1, issue_labels=[]
        )
        assert out["classification"] == "real_drift"

    async def test_raises_on_nonzero_returncode(self, monkeypatch) -> None:
        client, _ = _client(monkeypatch, returncode=1)
        with pytest.raises(RuntimeError, match="triage failed"):
            await client.complete_structured(
                prompt="hi", schema={}, issue_number=1, issue_labels=[]
            )

    async def test_raises_when_no_json_in_output(self, monkeypatch) -> None:
        client, _ = _client(monkeypatch, stdout="just prose, no json here")
        with pytest.raises(RuntimeError, match="no JSON object"):
            await client.complete_structured(
                prompt="hi", schema={}, issue_number=1, issue_labels=[]
            )

    async def test_threads_issue_number_and_labels_to_the_seam(
        self, monkeypatch
    ) -> None:
        client, captured = _client(
            monkeypatch, stdout='{"classification": "consistent", "rationale": "x"}'
        )
        await client.complete_structured(
            prompt="hi",
            schema={"type": "object"},
            issue_number=9001,
            issue_labels=["hydraflow-adr-drift", "hydraflow-find"],
        )
        assert captured["issue_number"] == 9001
        assert captured["issue_labels"] == ["hydraflow-adr-drift", "hydraflow-find"]
        assert captured["response_schema"] == {"type": "object"}
        assert captured["source"] == "adr_drift_resolver"
