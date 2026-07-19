"""Regression: diagnostic transcript prose raised false credit exhaustion (#9895).

DiagnosticLoop analyzes FAILED issues' transcripts, which routinely quote
credit-error prose ("usage limit reached", "credit balance is too low").
The stream runner scanned stderr + accumulated stdout for those phrases, so
essentially every diagnostic run raised a false global CreditExhaustedError
— the flood (#9888) that got the loop kill-switched (#9898). Compounding it
(absorbed #9845), ``_escalate_to_hitl`` posted unconditionally: ~33
identical no-op diagnosis comments landed on one issue during the 2026-06
exhaustion.

Pins:
- ``StreamConfig.credit_prose_scan=False`` limits credit detection to
  stderr (the CLI's own signal); agent stdout prose cannot raise. True
  (the default) keeps the old broad scan for every other runner.
- ``DiagnosticRunner.CREDIT_PROSE_SCAN`` is False, ``BaseRunner``'s default
  is True, and ``_execute`` threads the ClassVar into StreamConfig.
- ``_escalate_to_hitl`` dedups identical comments per issue (bounded at one
  hash key per issue; a CHANGED diagnosis re-posts and replaces the key).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from base_runner import BaseRunner
from diagnostic_loop import DiagnosticLoop
from diagnostic_runner import DiagnosticRunner
from runner_utils import StreamConfig, _post_stream_result
from subprocess_util import CreditExhaustedError
from tests.helpers import make_bg_loop_deps

_CREDIT_PROSE = "the run failed because your credit balance is too low"


def _post(*, accumulated: str = "", stderr: str = "", scan: bool) -> str:
    return _post_stream_result(
        raw_lines=[accumulated] if accumulated else [],
        accumulated_text=accumulated,
        result_text="analysis complete",
        early_killed=False,
        returncode=0,
        stderr_text=stderr,
        parser=MagicMock(),
        config=StreamConfig(credit_prose_scan=scan),
        logger=logging.getLogger("test"),
    )


class TestCreditProseScanFlag:
    def test_prose_in_stdout_raises_under_default_scan(self) -> None:
        with pytest.raises(CreditExhaustedError):
            _post(accumulated=_CREDIT_PROSE, scan=True)

    def test_prose_in_stdout_does_not_raise_when_scan_disabled(self) -> None:
        transcript = _post(accumulated=_CREDIT_PROSE, scan=False)
        assert transcript == "analysis complete"

    def test_stderr_signal_still_raises_when_scan_disabled(self) -> None:
        """The CLI's OWN billing failure must fire in both modes."""
        with pytest.raises(CreditExhaustedError):
            _post(stderr="Error: credit balance is too low", scan=False)


class TestRunnerClassVarThreading:
    def test_diagnostic_runner_opts_out_and_base_default_is_broad(self) -> None:
        assert BaseRunner.CREDIT_PROSE_SCAN is True
        assert DiagnosticRunner.CREDIT_PROSE_SCAN is False

    @pytest.mark.asyncio
    async def test_execute_threads_the_classvar_into_stream_config(
        self, config, event_bus
    ) -> None:
        runner = DiagnosticRunner(config=config, event_bus=event_bus)
        captured: dict[str, StreamConfig] = {}

        async def fake_stream(**kwargs):
            captured["config"] = kwargs["config"]
            return "ok"

        with patch("base_runner.stream_claude_process", side_effect=fake_stream):
            await runner._execute(
                ["claude", "-p"],
                "prompt",
                config.repo_root,
                {"issue": 1, "source": "diagnostic"},
            )

        assert captured["config"].credit_prose_scan is False


class TestEscalateCommentDedup:
    def _make_loop(self, tmp_path: Path) -> tuple[DiagnosticLoop, MagicMock]:
        deps = make_bg_loop_deps(tmp_path)
        object.__setattr__(deps.config, "diagnostic_loop_enabled", True)
        prs = MagicMock()
        prs.post_comment = AsyncMock()
        prs.swap_pipeline_labels = AsyncMock()
        prs.add_labels = AsyncMock()
        loop = DiagnosticLoop(
            config=deps.config,
            runner=MagicMock(),
            prs=prs,
            state=MagicMock(),
            deps=deps.loop_deps,
        )
        return loop, prs

    @pytest.mark.asyncio
    async def test_identical_comment_posted_once(self, tmp_path: Path) -> None:
        loop, prs = self._make_loop(tmp_path)

        await loop._escalate_to_hitl(42, comment="same diagnosis")
        await loop._escalate_to_hitl(42, comment="same diagnosis")

        prs.post_comment.assert_awaited_once_with(42, "same diagnosis")
        # Labeling still runs on every escalation (idempotent on GitHub).
        assert prs.swap_pipeline_labels.await_count == 2

    @pytest.mark.asyncio
    async def test_changed_comment_reposts_and_replaces_key(
        self, tmp_path: Path
    ) -> None:
        loop, prs = self._make_loop(tmp_path)

        await loop._escalate_to_hitl(42, comment="first diagnosis")
        await loop._escalate_to_hitl(42, comment="second diagnosis")

        assert prs.post_comment.await_count == 2
        # Bounded: exactly one dedup key per issue survives.
        keys = {k for k in loop._hitl_comment_dedup.get() if k.startswith("42:")}
        assert len(keys) == 1

    @pytest.mark.asyncio
    async def test_issues_are_deduped_independently(self, tmp_path: Path) -> None:
        loop, prs = self._make_loop(tmp_path)

        await loop._escalate_to_hitl(42, comment="same diagnosis")
        await loop._escalate_to_hitl(43, comment="same diagnosis")

        assert prs.post_comment.await_count == 2

    @pytest.mark.asyncio
    async def test_failed_post_is_not_marked_seen(self, tmp_path: Path) -> None:
        """A failed comment post must retry next escalation, not dedup away."""
        loop, prs = self._make_loop(tmp_path)
        prs.post_comment.side_effect = [RuntimeError("gh down"), None]

        await loop._escalate_to_hitl(42, comment="same diagnosis")
        await loop._escalate_to_hitl(42, comment="same diagnosis")

        assert prs.post_comment.await_count == 2
