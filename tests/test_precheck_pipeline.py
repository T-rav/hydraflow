"""Tests for precheck_pipeline.py — shared precheck pipeline functions."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import PrecheckResult
from precheck_pipeline import (
    build_debug_command,
    build_subskill_command,
    parse_precheck_transcript,
    run_precheck_pipeline,
)
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# parse_precheck_transcript
# ---------------------------------------------------------------------------


class TestParsePrecheckTranscript:
    """Tests for parse_precheck_transcript."""

    def test_all_fields_present(self) -> None:
        transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.95\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: All looks good.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert isinstance(result, PrecheckResult)
        assert result.risk == "low"
        assert result.confidence == 0.95
        assert result.escalate is False
        assert result.summary == "All looks good."
        assert result.parse_failed is False

    def test_missing_risk_defaults_to_medium(self) -> None:
        transcript = (
            "PRECHECK_CONFIDENCE: 0.8\nPRECHECK_ESCALATE: no\nPRECHECK_SUMMARY: Fine.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.risk == "medium"
        assert result.parse_failed is True

    def test_missing_confidence_defaults_to_zero(self) -> None:
        transcript = (
            "PRECHECK_RISK: high\nPRECHECK_ESCALATE: yes\nPRECHECK_SUMMARY: Risky.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.confidence == 0.0
        assert result.parse_failed is True

    def test_escalate_yes(self) -> None:
        transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Needs debug.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.escalate is True

    def test_escalate_no(self) -> None:
        transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.9\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: OK.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.escalate is False

    def test_case_insensitive_parsing(self) -> None:
        transcript = (
            "precheck_risk: HIGH\n"
            "precheck_confidence: 0.42\n"
            "precheck_escalate: YES\n"
            "precheck_summary: Mixed case.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.risk == "high"
        assert result.confidence == 0.42
        assert result.escalate is True
        assert result.summary == "Mixed case."
        assert result.parse_failed is False

    def test_empty_string_returns_defaults(self) -> None:
        result = parse_precheck_transcript("")
        assert result.risk == "medium"
        assert result.confidence == 0.0
        assert result.escalate is False
        assert result.summary == ""
        assert result.parse_failed is True

    def test_missing_summary_only(self) -> None:
        transcript = (
            "PRECHECK_RISK: low\nPRECHECK_CONFIDENCE: 0.8\nPRECHECK_ESCALATE: no\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.risk == "low"
        assert result.confidence == 0.8
        assert result.escalate is False
        assert result.summary == ""
        assert result.parse_failed is True

    def test_missing_escalate_only(self) -> None:
        transcript = (
            "PRECHECK_RISK: medium\n"
            "PRECHECK_CONFIDENCE: 0.5\n"
            "PRECHECK_SUMMARY: Partial.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.escalate is False
        assert result.parse_failed is True

    def test_preamble_before_fields(self) -> None:
        transcript = (
            "Some preamble.\n"
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.95\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: All looks good.\n"
        )
        result = parse_precheck_transcript(transcript)
        assert result.risk == "low"
        assert result.confidence == 0.95
        assert result.escalate is False
        assert result.summary == "All looks good."
        assert result.parse_failed is False


# ---------------------------------------------------------------------------
# build_subskill_command / build_debug_command
# ---------------------------------------------------------------------------


class TestBuildSubskillCommand:
    """Tests for build_subskill_command."""

    def test_uses_config_tool_and_model(self) -> None:
        cfg = ConfigFactory.create()
        cmd = build_subskill_command(cfg)
        assert "claude" in cmd
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "haiku"

    def test_codex_backend(self) -> None:
        cfg = ConfigFactory.create(subskill_tool="codex", subskill_model="gpt-4")
        cmd = build_subskill_command(cfg)
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert cmd[cmd.index("--model") + 1] == "gpt-4"


class TestBuildDebugCommand:
    """Tests for build_debug_command."""

    def test_uses_config_tool_and_model(self) -> None:
        cfg = ConfigFactory.create()
        cmd = build_debug_command(cfg)
        assert "claude" in cmd
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "opus"

    def test_codex_backend(self) -> None:
        cfg = ConfigFactory.create(debug_tool="codex", debug_model="gpt-5")
        cmd = build_debug_command(cfg)
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert cmd[cmd.index("--model") + 1] == "gpt-5"


# ---------------------------------------------------------------------------
# run_precheck_pipeline
# ---------------------------------------------------------------------------


class TestRunPrecheckPipeline:
    """Tests for run_precheck_pipeline."""

    @pytest.mark.asyncio
    async def test_disabled_when_max_subskill_zero(self) -> None:
        cfg = ConfigFactory.create(max_subskill_attempts=0)
        execute = AsyncMock()
        result = await run_precheck_pipeline(
            cfg, "prompt", "diff", execute, debug_suffix="\nDEBUG"
        )
        assert result == "Low-tier precheck disabled."
        execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_no_escalation(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            subskill_confidence_threshold=0.7,
            debug_escalation_enabled=False,
            repo_root=tmp_path / "repo",
        )
        valid_transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.95\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: All clear.\n"
        )
        execute = AsyncMock(return_value=valid_transcript)
        result = await run_precheck_pipeline(
            cfg, "prompt", "diff", execute, debug_suffix="\nDEBUG"
        )
        assert "Precheck risk: low" in result
        assert "Precheck confidence: 0.95" in result
        assert "Precheck summary: All clear." in result
        assert "Debug escalation: no" in result
        execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_on_parse_failure(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=3,
            debug_escalation_enabled=False,
            repo_root=tmp_path / "repo",
        )
        garbage = "No parseable fields here."
        valid_transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.9\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: Finally parsed.\n"
        )
        execute = AsyncMock(side_effect=[garbage, garbage, valid_transcript])
        result = await run_precheck_pipeline(
            cfg, "prompt", "diff", execute, debug_suffix="\nDEBUG"
        )
        assert execute.call_count == 3
        assert "Precheck risk: low" in result
        assert "Precheck summary: Finally parsed." in result

    @pytest.mark.asyncio
    async def test_escalates_to_debug(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            debug_escalation_enabled=True,
            max_debug_attempts=1,
            subskill_confidence_threshold=0.7,
            repo_root=tmp_path / "repo",
        )
        high_risk_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Risky change.\n"
        )
        debug_transcript = "Debug: found critical issues."
        execute = AsyncMock(side_effect=[high_risk_transcript, debug_transcript])
        result = await run_precheck_pipeline(
            cfg, "prompt", "diff", execute, debug_suffix="\nDEBUG"
        )
        assert execute.call_count == 2
        # Verify first call used subskill command with the original prompt
        first_cmd, first_prompt = execute.call_args_list[0][0]
        assert first_cmd == build_subskill_command(cfg)
        assert first_prompt == "prompt"
        # Verify second call used debug command with the suffixed prompt
        second_cmd, second_prompt = execute.call_args_list[1][0]
        assert second_cmd == build_debug_command(cfg)
        assert second_prompt == "prompt\nDEBUG"
        assert "Precheck risk: high" in result
        assert "Debug escalation: yes" in result
        assert "Debug precheck transcript:" in result
        assert "Debug: found critical issues." in result
        assert "Escalation reasons:" in result

    @pytest.mark.asyncio
    async def test_no_debug_when_max_debug_zero(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            debug_escalation_enabled=True,
            max_debug_attempts=0,
            subskill_confidence_threshold=0.7,
            repo_root=tmp_path / "repo",
        )
        high_risk_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Risky.\n"
        )
        execute = AsyncMock(return_value=high_risk_transcript)
        result = await run_precheck_pipeline(
            cfg, "prompt", "diff", execute, debug_suffix="\nDEBUG"
        )
        assert execute.call_count == 1
        assert "Debug escalation: yes" in result
        assert "Debug precheck transcript:" not in result

    @pytest.mark.asyncio
    async def test_exception_returns_fallback(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            repo_root=tmp_path / "repo",
        )
        execute = AsyncMock(side_effect=RuntimeError("subprocess crashed"))
        result = await run_precheck_pipeline(
            cfg, "prompt", "diff", execute, debug_suffix="\nDEBUG"
        )
        assert (
            result == "Low-tier precheck failed; continuing without precheck context."
        )

    @pytest.mark.asyncio
    async def test_debug_transcript_truncated_to_1000_chars(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            debug_escalation_enabled=True,
            max_debug_attempts=1,
            subskill_confidence_threshold=0.7,
            repo_root=tmp_path / "repo",
        )
        high_risk_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Risky.\n"
        )
        long_debug = "D" * 2000
        execute = AsyncMock(side_effect=[high_risk_transcript, long_debug])
        result = await run_precheck_pipeline(
            cfg, "prompt", "diff", execute, debug_suffix="\nDEBUG"
        )
        assert "D" * 1000 in result
        assert "D" * 1001 not in result

    @pytest.mark.asyncio
    async def test_high_risk_diff_passes_true(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            repo_root=tmp_path / "repo",
        )
        precheck_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.5\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: risky auth change\n"
        )
        auth_diff = "diff --git a/src/auth/login.py b/src/auth/login.py\n+pass"
        execute = AsyncMock(return_value=precheck_transcript)

        with patch(
            "precheck_pipeline.should_escalate_debug",
            wraps=__import__("escalation_gate").should_escalate_debug,
        ) as mock_escalate:
            await run_precheck_pipeline(
                cfg, "prompt", auth_diff, execute, debug_suffix="\nDEBUG"
            )

        mock_escalate.assert_called_once()
        assert mock_escalate.call_args[1]["high_risk_files_touched"] is True

    @pytest.mark.asyncio
    async def test_safe_diff_passes_false(self, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            repo_root=tmp_path / "repo",
        )
        precheck_transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.9\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: safe change\n"
        )
        safe_diff = "diff --git a/src/utils.py b/src/utils.py\n+def helper(): pass"
        execute = AsyncMock(return_value=precheck_transcript)

        with patch(
            "precheck_pipeline.should_escalate_debug",
            wraps=__import__("escalation_gate").should_escalate_debug,
        ) as mock_escalate:
            await run_precheck_pipeline(
                cfg, "prompt", safe_diff, execute, debug_suffix="\nDEBUG"
            )

        mock_escalate.assert_called_once()
        assert mock_escalate.call_args[1]["high_risk_files_touched"] is False
