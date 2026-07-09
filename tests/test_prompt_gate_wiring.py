"""Wiring tests: every LLM spawn seam consults the CH-6 prompt gate (#9734).

Seams under test (the same set the WS-2.2 telemetry containment approves):

* ``BaseRunner._execute`` — gates before ``stream_claude_process``; blocks
  propagate (phase escalation machinery routes hard failures to HITL).
* ``runner_utils.run_lightweight_agent`` — gates before spawning; blocks
  collapse to the seam's soft-failure ``SimpleResult(returncode=-1)``.
* ``runner_utils.stream_claude_with_telemetry`` — gates; blocks propagate.
* ``BaseSubprocessRunner.run`` — gates; blocks collapse to a crashed outcome
  (the seam's never-raises contract).
* ``preflight.context.gather_context`` — redaction-only assembly gate.

Zero-regression pins: with the default ``internal`` class the prompt reaches
the spawn primitive byte-identical.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_runner import BaseRunner
from prompt_gate import PromptGateBlockedError
from runners.base_subprocess_runner import BaseSubprocessRunner, SpawnOutcome
from tests.helpers import ConfigFactory

_SENSITIVE = "patient SSN 123-45-6789 needs a fix"


def _config(tmp_path, **updates):
    cfg = ConfigFactory.create(repo_root=tmp_path)
    return cfg.model_copy(update=updates) if updates else cfg


def _regulated_config(tmp_path, *, backends=None):
    return _config(
        tmp_path,
        repo_data_class="regulated-phi",
        data_class_allowed_backends=(
            backends if backends is not None else {"regulated-phi": ["claude"]}
        ),
    )


def _read_audit(config) -> list[dict]:
    path = config.prompt_gate_audit_path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _event_bus() -> MagicMock:
    bus = MagicMock()
    bus.current_session_id = "sess-test"
    return bus


class _WiringRunner(BaseRunner):
    _log = logging.getLogger("hydraflow.test_prompt_gate_wiring")


class TestBaseRunnerExecuteGate:
    @pytest.mark.asyncio
    async def test_internal_class_prompt_reaches_stream_unchanged(
        self, tmp_path: Path
    ) -> None:
        """Zero-regression pin: default class → byte-identical prompt."""
        runner = _WiringRunner(_config(tmp_path), _event_bus())
        with patch("base_runner.stream_claude_process", new_callable=AsyncMock) as mock:
            mock.return_value = "out"
            await runner._execute(["claude", "-p"], _SENSITIVE, tmp_path, {"issue": 1})
        assert mock.call_args[1]["prompt"] == _SENSITIVE
        assert not runner._config.prompt_gate_audit_path.exists()

    @pytest.mark.asyncio
    async def test_regulated_class_prompt_is_redacted_before_spawn(
        self, tmp_path: Path
    ) -> None:
        runner = _WiringRunner(_regulated_config(tmp_path), _event_bus())
        with patch("base_runner.stream_claude_process", new_callable=AsyncMock) as mock:
            mock.return_value = "out"
            await runner._execute(["claude", "-p"], _SENSITIVE, tmp_path, {"issue": 1})
        sent = mock.call_args[1]["prompt"]
        assert "123-45-6789" not in sent
        assert "[REDACTED:ssn_like]" in sent

    @pytest.mark.asyncio
    async def test_regulated_class_disallowed_backend_blocks_before_spawn(
        self, tmp_path: Path
    ) -> None:
        config = _regulated_config(tmp_path, backends={"regulated-phi": ["codex"]})
        runner = _WiringRunner(config, _event_bus())
        with (
            patch("base_runner.stream_claude_process", new_callable=AsyncMock) as mock,
            pytest.raises(PromptGateBlockedError),
        ):
            await runner._execute(["claude", "-p"], _SENSITIVE, tmp_path, {"issue": 5})
        mock.assert_not_awaited()
        records = _read_audit(config)
        assert len(records) == 1
        assert records[0]["action"] == "block"
        assert records[0]["issue_number"] == 5

    @pytest.mark.asyncio
    async def test_issue_labels_elevate_class_at_execute(self, tmp_path: Path) -> None:
        config = _config(
            tmp_path, data_class_allowed_backends={"regulated-phi": ["claude"]}
        )
        runner = _WiringRunner(config, _event_bus())
        with patch("base_runner.stream_claude_process", new_callable=AsyncMock) as mock:
            mock.return_value = "out"
            await runner._execute(
                ["claude", "-p"],
                _SENSITIVE,
                tmp_path,
                {"issue": 2},
                issue_labels=["data-class:regulated-phi"],
            )
        assert "[REDACTED:ssn_like]" in mock.call_args[1]["prompt"]


class TestRunLightweightAgentGate:
    @pytest.mark.asyncio
    async def test_internal_class_is_noop(self, tmp_path: Path) -> None:
        from execution import SimpleResult
        from runner_utils import run_lightweight_agent

        runner = MagicMock()
        runner.run_simple = AsyncMock(return_value=SimpleResult(returncode=0))
        result = await run_lightweight_agent(
            runner=runner,
            config=_config(tmp_path),
            tool="claude",
            model="haiku",
            prompt=_SENSITIVE,
            source="wiki_compilation",
            timeout=10,
        )
        assert result.returncode == 0
        runner.run_simple.assert_awaited_once()
        cmd = runner.run_simple.call_args[0][0]
        cmd_input = runner.run_simple.call_args[1].get("input")
        blob = " ".join(cmd) + (cmd_input or b"").decode("utf-8", "ignore")
        assert "123-45-6789" in blob  # prompt reached the CLI unchanged

    @pytest.mark.asyncio
    async def test_regulated_class_redacts_prompt(self, tmp_path: Path) -> None:
        from execution import SimpleResult
        from runner_utils import run_lightweight_agent

        runner = MagicMock()
        runner.run_simple = AsyncMock(return_value=SimpleResult(returncode=0))
        await run_lightweight_agent(
            runner=runner,
            config=_regulated_config(tmp_path),
            tool="claude",
            model="haiku",
            prompt=_SENSITIVE,
            source="wiki_compilation",
            timeout=10,
        )
        cmd = runner.run_simple.call_args[0][0]
        cmd_input = runner.run_simple.call_args[1].get("input")
        blob = " ".join(cmd) + (cmd_input or b"").decode("utf-8", "ignore")
        assert "123-45-6789" not in blob
        assert "[REDACTED:ssn_like]" in blob

    @pytest.mark.asyncio
    async def test_block_collapses_to_soft_failure_without_spawn(
        self, tmp_path: Path
    ) -> None:
        from runner_utils import run_lightweight_agent

        config = _regulated_config(tmp_path, backends={})
        runner = MagicMock()
        runner.run_simple = AsyncMock()
        result = await run_lightweight_agent(
            runner=runner,
            config=config,
            tool="claude",
            model="haiku",
            prompt=_SENSITIVE,
            source="wiki_compilation",
            timeout=10,
        )
        assert result.returncode == -1
        assert "prompt gate blocked" in result.stderr
        runner.run_simple.assert_not_awaited()
        assert _read_audit(config)[0]["action"] == "block"


class TestStreamClaudeWithTelemetryGate:
    @pytest.mark.asyncio
    async def test_block_raises_before_spawn(self, tmp_path: Path) -> None:
        import runner_utils
        from runner_utils import stream_claude_with_telemetry

        config = _regulated_config(tmp_path, backends={})
        with (
            patch.object(
                runner_utils, "stream_claude_process", new_callable=AsyncMock
            ) as mock,
            pytest.raises(PromptGateBlockedError),
        ):
            await stream_claude_with_telemetry(
                config=config,
                cmd=["claude", "-p"],
                prompt=_SENSITIVE,
                cwd=tmp_path,
                active_procs=set(),
                event_bus=_event_bus(),
                event_data={"issue": 3, "source": "sentry"},
                logger=logging.getLogger("test"),
            )
        mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_regulated_redacts_prompt(self, tmp_path: Path) -> None:
        import runner_utils
        from runner_utils import stream_claude_with_telemetry

        config = _regulated_config(tmp_path)
        with patch.object(
            runner_utils, "stream_claude_process", new_callable=AsyncMock
        ) as mock:
            mock.return_value = "out"
            await stream_claude_with_telemetry(
                config=config,
                cmd=["claude", "-p"],
                prompt=_SENSITIVE,
                cwd=tmp_path,
                active_procs=set(),
                event_bus=_event_bus(),
                event_data={"issue": 3, "source": "sentry"},
                logger=logging.getLogger("test"),
            )
        assert "[REDACTED:ssn_like]" in mock.call_args[1]["prompt"]


@dataclass(frozen=True)
class _SpawnResult:
    crashed: bool
    transcript: str


class _GateProbeRunner(BaseSubprocessRunner[_SpawnResult]):
    def _telemetry_source(self) -> str:
        return "gate_probe"

    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        return ["claude", "-p"]

    def _make_result(self, outcome: SpawnOutcome) -> _SpawnResult:
        return _SpawnResult(crashed=outcome.crashed, transcript=outcome.transcript)


class TestBaseSubprocessRunnerGate:
    @pytest.mark.asyncio
    async def test_internal_class_prompt_unchanged(self, tmp_path: Path) -> None:
        runner = _GateProbeRunner(config=_config(tmp_path), event_bus=_event_bus())
        with patch(
            "runners.base_subprocess_runner.stream_claude_process",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = "out"
            result = await runner.run(
                prompt=_SENSITIVE, worktree_path=str(tmp_path), issue_number=7
            )
        assert not result.crashed
        assert mock.call_args[1]["prompt"] == _SENSITIVE

    @pytest.mark.asyncio
    async def test_regulated_class_redacts_prompt(self, tmp_path: Path) -> None:
        runner = _GateProbeRunner(
            config=_regulated_config(tmp_path), event_bus=_event_bus()
        )
        with patch(
            "runners.base_subprocess_runner.stream_claude_process",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = "out"
            await runner.run(
                prompt=_SENSITIVE, worktree_path=str(tmp_path), issue_number=7
            )
        assert "[REDACTED:ssn_like]" in mock.call_args[1]["prompt"]

    @pytest.mark.asyncio
    async def test_block_collapses_to_crashed_outcome_without_spawn(
        self, tmp_path: Path
    ) -> None:
        config = _regulated_config(tmp_path, backends={})
        runner = _GateProbeRunner(config=config, event_bus=_event_bus())
        with patch(
            "runners.base_subprocess_runner.stream_claude_process",
            new_callable=AsyncMock,
        ) as mock:
            result = await runner.run(
                prompt=_SENSITIVE, worktree_path=str(tmp_path), issue_number=7
            )
        mock.assert_not_awaited()
        assert result.crashed
        assert "prompt gate blocked" in result.transcript
        assert "123-45-6789" not in result.transcript
        assert _read_audit(config)[0]["action"] == "block"


class _StubAuditStore:
    def entries_for_issue(self, issue_number: int) -> list[Any]:
        return []


def _pr_port(comment_body: str) -> MagicMock:
    port = MagicMock()
    port.list_issue_comments = AsyncMock(
        return_value=[
            {"user": {"login": "alice"}, "body": comment_body, "created_at": "t"}
        ]
    )
    return port


class TestGatherContextGate:
    @pytest.mark.asyncio
    async def test_no_config_is_backward_compatible(self) -> None:
        from preflight.context import gather_context

        state = MagicMock()
        state.get_escalation_context.return_value = None
        ctx = await gather_context(
            issue_number=1,
            issue_body=_SENSITIVE,
            sub_label="x",
            pr_port=_pr_port("comment"),
            wiki_store=None,
            state=state,
            audit_store=_StubAuditStore(),
            repo_slug="",
        )
        assert ctx.issue_body == _SENSITIVE

    @pytest.mark.asyncio
    async def test_internal_class_leaves_context_unchanged(
        self, tmp_path: Path
    ) -> None:
        from preflight.context import gather_context

        state = MagicMock()
        state.get_escalation_context.return_value = None
        ctx = await gather_context(
            issue_number=1,
            issue_body=_SENSITIVE,
            sub_label="x",
            pr_port=_pr_port("note token=abc123secret"),
            wiki_store=None,
            state=state,
            audit_store=_StubAuditStore(),
            repo_slug="",
            config=_config(tmp_path),
        )
        assert ctx.issue_body == _SENSITIVE
        assert ctx.issue_comments[0].body == "note token=abc123secret"

    @pytest.mark.asyncio
    async def test_regulated_class_redacts_body_comments_and_wiki(
        self, tmp_path: Path
    ) -> None:
        from preflight.context import gather_context

        config = _regulated_config(tmp_path)
        state = MagicMock()
        state.get_escalation_context.return_value = None
        wiki = MagicMock()
        wiki.query.return_value = "wiki says password=hunter2"
        ctx = await gather_context(
            issue_number=1,
            issue_body=_SENSITIVE,
            sub_label="x",
            pr_port=_pr_port("note token=abc123secret"),
            wiki_store=wiki,
            state=state,
            audit_store=_StubAuditStore(),
            repo_slug="acme/regulated",
            config=config,
        )
        assert "123-45-6789" not in ctx.issue_body
        assert "[REDACTED:ssn_like]" in ctx.issue_body
        assert "abc123secret" not in ctx.issue_comments[0].body
        assert "hunter2" not in ctx.wiki_excerpts
        records = _read_audit(config)
        assert len(records) == 1
        assert records[0]["source"] == "preflight_context"

    @pytest.mark.asyncio
    async def test_issue_labels_elevate_context_class(self, tmp_path: Path) -> None:
        from preflight.context import gather_context

        state = MagicMock()
        state.get_escalation_context.return_value = None
        ctx = await gather_context(
            issue_number=1,
            issue_body=_SENSITIVE,
            sub_label="x",
            pr_port=_pr_port("c"),
            wiki_store=None,
            state=state,
            audit_store=_StubAuditStore(),
            repo_slug="",
            config=_config(tmp_path),
            issue_labels=["data-class:regulated-phi"],
        )
        assert "[REDACTED:ssn_like]" in ctx.issue_body
