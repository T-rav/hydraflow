"""Unit tests for the sandbox-harness primitives that let a MockWorld scenario
drive decompose-to-converge deterministically (unblocks s54, issue #9758).

Covers the two structural pieces that don't need docker:
- ``DecompositionEnsemble._execute_ensemble`` short-circuits to a scripted
  transcript when a ``_mockworld_fake_llm`` sentinel is attached (no subprocess).
- ``FakeLLM.script_decomposition`` / ``next_decomposition_reply`` FIFO.
- ``MockWorldSeed.auto_agent_attempts`` field (pre-seed the exhaustion counter).

The end-to-end s54 sandbox scenario (which also needs the sandbox_main wiring +
a docker run) is the remaining step tracked in #9758.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from decomposition_ensemble import DecompositionEnsemble
from mockworld.fakes.fake_llm import FakeLLM
from mockworld.seed import MockWorldSeed
from tests.helpers import ConfigFactory


class TestFakeLLMDecompositionQueue:
    def test_replies_pop_in_call_order(self):
        fake = FakeLLM()
        fake.script_decomposition(7, ["DIRECTION", "VALIDATION"])
        assert fake.next_decomposition_reply(7) == "DIRECTION"
        assert fake.next_decomposition_reply(7) == "VALIDATION"

    def test_empty_queue_returns_none(self):
        fake = FakeLLM()
        assert fake.next_decomposition_reply(99) is None  # never scripted
        fake.script_decomposition(7, ["only-one"])
        assert fake.next_decomposition_reply(7) == "only-one"
        assert fake.next_decomposition_reply(7) is None  # drained

    def test_keyed_per_issue(self):
        fake = FakeLLM()
        fake.script_decomposition(1, ["a1"])
        fake.script_decomposition(2, ["b1"])
        assert fake.next_decomposition_reply(2) == "b1"
        assert fake.next_decomposition_reply(1) == "a1"


@pytest.mark.asyncio
class TestExecuteCouncilSentinel:
    async def test_sentinel_short_circuits_to_scripted_reply(self, monkeypatch):
        # If the sentinel path leaks to a real spawn, this raises.
        def _boom(*_a, **_k):
            raise AssertionError(
                "run_lightweight_agent must NOT be called under the sentinel"
            )

        monkeypatch.setattr("runner_utils.run_lightweight_agent", _boom)

        ensemble = DecompositionEnsemble(runner=object(), config=ConfigFactory.create())
        fake = FakeLLM()
        fake.script_decomposition(7, ["DIR-REPLY", "VAL-REPLY"])
        ensemble._mockworld_fake_llm = fake  # attached by sandbox_main in production

        assert (
            await ensemble._execute_ensemble("direction prompt", issue_number=7)
            == "DIR-REPLY"
        )
        assert (
            await ensemble._execute_ensemble("validation prompt", issue_number=7)
            == "VAL-REPLY"
        )
        # Drained → None (the ensemble treats None as a garbled/retryable pass).
        assert await ensemble._execute_ensemble("p", issue_number=7) is None

    async def test_no_sentinel_uses_real_seam(self, monkeypatch):
        # Without the sentinel, the real seam is used (proves the bypass is
        # gated on the sentinel, not always-on).
        calls = {"n": 0}

        async def _fake_seam(**_kw):
            calls["n"] += 1
            from execution import SimpleResult

            return SimpleResult(stdout="from-seam", returncode=0)

        monkeypatch.setattr("runner_utils.run_lightweight_agent", _fake_seam)
        ensemble = DecompositionEnsemble(runner=object(), config=ConfigFactory.create())
        out = await ensemble._execute_ensemble("p", issue_number=7)
        assert calls["n"] == 1
        assert out == "from-seam"


class TestSeedAutoAgentAttempts:
    def test_field_defaults_empty(self):
        assert MockWorldSeed().auto_agent_attempts == {}

    def test_field_accepts_preseeded_counts(self):
        seed = MockWorldSeed(auto_agent_attempts={5: 3})
        assert seed.auto_agent_attempts[5] == 3
