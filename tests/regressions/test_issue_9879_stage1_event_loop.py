"""Regression: DiagnosticLoop Stage 1 froze the event loop ~15s (#9879).

The CH-6 gate regex-redacts the ENTIRE prompt synchronously, and the
diagnosis prompt embedded UNBOUNDED CI logs and PR diffs (a full pytest
log is tens of MB). Running that pure-CPU scan inline on the event loop
starved every other coroutine — the dashboard HTTP layer timed out >12s
while the factory kept working, masquerading as a hang and causing
unnecessary restarts. The diagnostic loop was kill-switched (#9898)
partly on this.

Pins (mechanism, not timing — timing pins flake in CI):
- BaseRunner._execute runs gate_prompt OFF the event-loop thread
  (asyncio.to_thread), for every runner.
- The gated (possibly redacted) prompt is still what reaches the stream.
- The diagnosis prompt bounds ci_logs (TAIL — failure evidence lives at
  the end) and pr_diff, so a flood-era context cannot rebuild the
  multi-MB prompt.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from diagnostic_runner import DiagnosticRunner, _build_diagnosis_prompt
from models import EscalationContext
from prompt_gate import GateDecision, GateResult


def _context(**overrides) -> EscalationContext:
    fields = {
        "cause": "review exhausted",
        "origin_phase": "review",
        **overrides,
    }
    return EscalationContext(**fields)


class TestGateRunsOffTheEventLoop:
    @pytest.mark.asyncio
    async def test_gate_prompt_executes_in_a_worker_thread(
        self, config, event_bus
    ) -> None:
        runner = DiagnosticRunner(config=config, event_bus=event_bus)
        seen: dict[str, object] = {}

        def recording_gate(prompt: str, **kwargs) -> GateResult:
            seen["on_main_thread"] = (
                threading.current_thread() is threading.main_thread()
            )
            decision = GateDecision(data_class="internal", action="allow")
            return GateResult(prompt=prompt + "\n<gated>", decision=decision)

        async def fake_stream(**kwargs):
            seen["streamed_prompt"] = kwargs["prompt"]
            return "ok"

        with (
            patch("base_runner.gate_prompt", side_effect=recording_gate),
            patch("base_runner.stream_claude_process", side_effect=fake_stream),
        ):
            await runner._execute(
                ["claude", "-p"],
                "diagnose this",
                config.repo_root,
                {"issue": 1, "source": "diagnostic"},
            )

        assert seen["on_main_thread"] is False, (
            "gate_prompt ran ON the event-loop thread — a large prompt "
            "starves every coroutine for the duration of the regex scan"
        )
        assert str(seen["streamed_prompt"]).endswith("<gated>"), (
            "the gated prompt must still be what reaches the subprocess"
        )


class TestDiagnosisPromptBounded:
    def test_huge_ci_logs_are_tail_capped(self) -> None:
        logs = "HEAD-MARKER " + ("x" * 1_000_000) + " TAIL-MARKER"
        prompt = _build_diagnosis_prompt(1, "t", "b", _context(ci_logs=logs))

        assert "TAIL-MARKER" in prompt  # failure evidence lives at the end
        assert "HEAD-MARKER" not in prompt
        assert len(prompt) < 40_000

    def test_huge_pr_diff_is_capped(self) -> None:
        diff = "+" + ("y" * 1_000_000)
        prompt = _build_diagnosis_prompt(1, "t", "b", _context(pr_diff=diff))

        assert len(prompt) < 40_000

    def test_flood_era_context_stays_bounded_end_to_end(self) -> None:
        ctx = _context(
            ci_logs="l" * 2_000_000,
            pr_diff="d" * 2_000_000,
            agent_transcript="t" * 2_000_000,
        )
        prompt = _build_diagnosis_prompt(1, "t", "b", ctx)

        assert len(prompt) < 60_000
