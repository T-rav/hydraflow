"""Emission of validated findings (§5).

GATE and BUGFIX findings are pattern-shaped by construction — a signal spans N
issues — so they file ONE class issue and later siblings fold into it. POLICY
goes to the HITL memory path instead: a rule that changes how the factory
behaves is signed by a human, not merged by a bot.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from retro_emitter import emit  # noqa: E402
from retro_findings import BugfixFinding, GateFinding, PolicyFinding  # noqa: E402
from retro_signals import EvidenceRef, RetroSignal  # noqa: E402
from tests.helpers import ConfigFactory  # noqa: E402

SIGNAL = RetroSignal(
    id="tool_error-abc1234567",
    family="tool_error",
    signature="Bash: make quality failed",
    count=7,
    issues=[1, 2],
    evidence=[EvidenceRef(locator="traces/1/x", excerpt="make: *** [quality] Error 1")],
)

GATE = GateFinding(
    kind="gate",
    signal_id=SIGNAL.id,
    title="Guard repeated quality failures",
    guard_path="tests/architecture/test_q.py",
    observed="7 occurrences",
)
BUGFIX = BugfixFinding(
    kind="bugfix",
    signal_id=SIGNAL.id,
    title="make quality fails",
    repro_command="make quality",
    repro_file="Makefile",
    error_excerpt="make: *** [quality] Error 1",
)
POLICY = PolicyFinding(
    kind="policy",
    signal_id=SIGNAL.id,
    title="Require quality first",
    doc_path="CLAUDE.md",
    rule_text="Run make quality before finishing.",
)


def _config(**over):
    config = ConfigFactory.create()
    config.retro_findings_max_per_tick = 3
    for k, v in over.items():
        setattr(config, k, v)
    return config


class TestRouting:
    @pytest.mark.asyncio
    async def test_gate_and_bugfix_file_class_issues(self):
        prs = object()
        with (
            patch("retro_emitter.file_or_fold", new=AsyncMock(return_value=123)) as fof,
            patch("retro_emitter.file_memory_suggestion", new=AsyncMock()) as mem,
        ):
            counts = await emit([GATE, BUGFIX], [SIGNAL], prs, _config())

        assert counts["filed"] == 2
        assert fof.await_count == 2
        mem.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_policy_goes_to_the_human_signed_memory_path(self):
        with (
            patch("retro_emitter.file_or_fold", new=AsyncMock(return_value=1)) as fof,
            patch("retro_emitter.file_memory_suggestion", new=AsyncMock()) as mem,
        ):
            counts = await emit([POLICY], [SIGNAL], object(), _config())

        fof.assert_not_awaited()
        assert mem.await_count == 1
        assert counts["policy"] == 1


class TestClassIssueSemantics:
    @pytest.mark.asyncio
    async def test_the_signal_signature_is_the_class_needle(self):
        with patch("retro_emitter.file_or_fold", new=AsyncMock(return_value=1)) as fof:
            await emit([GATE], [SIGNAL], object(), _config())

        assert fof.await_args.kwargs["needle"] == SIGNAL.signature
        assert fof.await_args.kwargs["source"] == "retrospective"

    @pytest.mark.asyncio
    async def test_the_body_carries_the_evidence_and_the_count(self):
        with patch("retro_emitter.file_or_fold", new=AsyncMock(return_value=1)) as fof:
            await emit([BUGFIX], [SIGNAL], object(), _config())

        body = fof.await_args.kwargs["body"]
        assert "make: *** [quality] Error 1" in body
        assert "7" in body


class TestFailureSemantics:
    @pytest.mark.asyncio
    async def test_the_zero_sentinel_is_not_counted_as_filed(self):
        """create_issue returns 0 on failure — the existing contract."""
        with patch("retro_emitter.file_or_fold", new=AsyncMock(return_value=0)):
            counts = await emit([GATE], [SIGNAL], object(), _config())

        assert counts["filed"] == 0

    @pytest.mark.asyncio
    async def test_credit_exhaustion_propagates(self):
        from subprocess_util import CreditExhaustedError

        with (
            patch(
                "retro_emitter.file_or_fold",
                new=AsyncMock(side_effect=CreditExhaustedError("dead")),
            ),
            pytest.raises(CreditExhaustedError),
        ):
            await emit([GATE], [SIGNAL], object(), _config())

    @pytest.mark.asyncio
    async def test_one_failing_finding_does_not_lose_the_others(self):
        with patch(
            "retro_emitter.file_or_fold",
            new=AsyncMock(side_effect=[OSError("network"), 42]),
        ):
            counts = await emit([GATE, BUGFIX], [SIGNAL], object(), _config())

        assert counts["filed"] == 1
        assert counts["errors"] == 1


class TestCap:
    @pytest.mark.asyncio
    async def test_emission_stops_at_the_per_tick_cap(self):
        with patch("retro_emitter.file_or_fold", new=AsyncMock(return_value=1)) as fof:
            await emit(
                [GATE, BUGFIX, GATE, BUGFIX],
                [SIGNAL],
                object(),
                _config(retro_findings_max_per_tick=2),
            )

        assert fof.await_count == 2
