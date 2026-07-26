"""Unit tests for the opt-in ultra deep-review tier (issue #10555).

Covers the pure surface of ``src/ultra_review.py``: the gate truth-table,
command construction (plugin-dir retention), findings parsing / degradation,
and the dispatch helper's credit-exhaustion propagation vs fail-soft.
"""

from __future__ import annotations

import pytest

import ultra_review as ur
from config import HydraFlowConfig
from subprocess_util import CreditExhaustedError


def _config(**overrides: object) -> HydraFlowConfig:
    return HydraFlowConfig(**overrides)  # type: ignore[arg-type]


# --- Config dials ------------------------------------------------------------


class TestConfigDials:
    def test_defaults_are_off(self) -> None:
        config = HydraFlowConfig()
        assert config.review_ultra_enabled is False
        assert config.review_ultra_auto_high_blast is False
        assert config.review_ultra_model == "sonnet"

    def test_env_override_flips_enabled_dial(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ULTRA_ENABLED", "true")
        assert HydraFlowConfig().review_ultra_enabled is True

    def test_env_override_flips_auto_high_blast_dial(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ULTRA_AUTO_HIGH_BLAST", "true")
        assert HydraFlowConfig().review_ultra_auto_high_blast is True


# --- Gate truth-table --------------------------------------------------------


class TestShouldUltraReview:
    def test_gate_off_when_dial_disabled_even_with_label(self) -> None:
        config = _config(review_ultra_enabled=False)
        assert (
            ur.should_ultra_review(
                config=config, issue_labels=[ur.ULTRA_REVIEW_LABEL], diff=""
            )
            is False
        )

    def test_gate_on_when_enabled_and_label_present(self) -> None:
        config = _config(review_ultra_enabled=True)
        assert (
            ur.should_ultra_review(
                config=config, issue_labels=["ready", ur.ULTRA_REVIEW_LABEL], diff=""
            )
            is True
        )

    def test_label_match_is_case_insensitive(self) -> None:
        config = _config(review_ultra_enabled=True)
        assert (
            ur.should_ultra_review(
                config=config, issue_labels=["Review:Ultra"], diff=""
            )
            is True
        )

    def test_gate_on_when_auto_high_blast_and_critical_path(self) -> None:
        config = _config(review_ultra_enabled=True, review_ultra_auto_high_blast=True)
        # A diff touching a CRITICAL_PATHS_EXACT file classifies as high blast.
        diff = "diff --git a/src/orchestrator.py b/src/orchestrator.py\n+++ b/src/orchestrator.py\n+x = 1\n"
        assert ur.should_ultra_review(config=config, issue_labels=[], diff=diff) is True

    def test_gate_off_when_auto_high_blast_but_low_blast_docs(self) -> None:
        config = _config(review_ultra_enabled=True, review_ultra_auto_high_blast=True)
        diff = "diff --git a/docs/x.md b/docs/x.md\n+++ b/docs/x.md\n+note\n"
        assert (
            ur.should_ultra_review(config=config, issue_labels=[], diff=diff) is False
        )

    def test_gate_off_when_high_blast_but_auto_dial_off(self) -> None:
        config = _config(review_ultra_enabled=True, review_ultra_auto_high_blast=False)
        diff = "diff --git a/src/orchestrator.py b/src/orchestrator.py\n+++ b/src/orchestrator.py\n+x = 1\n"
        assert (
            ur.should_ultra_review(config=config, issue_labels=[], diff=diff) is False
        )


# --- Command construction ----------------------------------------------------


class TestBuildCommand:
    def test_command_retains_plugin_resolution_not_user_isolated(self) -> None:
        """isolate_user_settings=False keeps plugin resolution.

        The load-bearing signal is the ABSENCE of the isolation flags
        (``--setting-sources project``); with them stripped, the pre-cloned
        ``--plugin-dir`` flags survive so the code-review plugin resolves.
        """
        from agent_cli import claude_isolation_flags

        cmd = ur.build_ultra_review_command(_config(review_tool="claude"))
        isolation = claude_isolation_flags()
        # None of the isolation flags should appear in the ultra command.
        assert not any(flag in cmd for flag in isolation)
        assert "bypassPermissions" in cmd

    def test_command_uses_ultra_model(self) -> None:
        cmd = ur.build_ultra_review_command(
            _config(review_tool="claude", review_ultra_model="opus")
        )
        assert "opus" in cmd


# --- Findings parsing / degradation ------------------------------------------


class TestParseFindings:
    def test_keeps_material_and_drops_low_confidence(self) -> None:
        payload = (
            'prefix {"findings": ['
            '{"description": "real bug", "confidence": 90},'
            '{"description": "style nit", "confidence": 40}]} suffix'
        )
        result = ur.parse_ultra_findings(payload)
        assert result.degraded is False
        assert len(result.findings) == 2
        assert result.has_material_findings is True
        assert [f.description for f in result.material_findings] == ["real bug"]

    def test_fenced_json_block_is_parsed(self) -> None:
        payload = 'Here:\n```json\n{"findings": [{"description": "x", "confidence": 85}]}\n```\n'
        result = ur.parse_ultra_findings(payload)
        assert result.degraded is False
        assert result.has_material_findings is True

    def test_empty_findings_is_clean_not_degraded(self) -> None:
        result = ur.parse_ultra_findings('{"findings": []}')
        assert result.degraded is False
        assert result.findings == []
        assert result.has_material_findings is False

    def test_unparseable_output_is_degraded_no_raise(self) -> None:
        result = ur.parse_ultra_findings("no json anywhere in here")
        assert result.degraded is True
        assert result.findings == []

    def test_empty_payload_is_degraded(self) -> None:
        assert ur.parse_ultra_findings("").degraded is True
        assert ur.parse_ultra_findings("   ").degraded is True

    def test_findings_without_description_are_skipped(self) -> None:
        payload = '{"findings": [{"confidence": 95}, {"description": "keep", "confidence": 95}]}'
        result = ur.parse_ultra_findings(payload)
        assert [f.description for f in result.findings] == ["keep"]

    def test_out_of_range_confidence_is_clamped(self) -> None:
        payload = '{"findings": [{"description": "x", "confidence": 250}]}'
        result = ur.parse_ultra_findings(payload)
        assert result.findings[0].confidence == 100


# --- Dispatch helper: propagate vs fail-soft ---------------------------------


class TestRunUltraReview:
    async def test_returns_parsed_result_on_success(self) -> None:
        async def fake_execute(cmd, prompt, cwd, meta) -> str:  # noqa: ANN001
            return '{"findings": [{"description": "bug", "confidence": 90}]}'

        result = await ur.run_ultra_review(
            execute=fake_execute,
            config=_config(),
            prompt="p",
            cwd="/tmp",
        )
        assert result.has_material_findings is True

    async def test_credit_exhaustion_propagates(self) -> None:
        async def fake_execute(cmd, prompt, cwd, meta) -> str:  # noqa: ANN001
            raise CreditExhaustedError("usage limit reached")

        with pytest.raises(CreditExhaustedError):
            await ur.run_ultra_review(
                execute=fake_execute,
                config=_config(),
                prompt="p",
                cwd="/tmp",
            )

    async def test_generic_failure_is_degraded_not_raised(self) -> None:
        async def fake_execute(cmd, prompt, cwd, meta) -> str:  # noqa: ANN001
            raise RuntimeError("transient spawn failure")

        result = await ur.run_ultra_review(
            execute=fake_execute,
            config=_config(),
            prompt="p",
            cwd="/tmp",
        )
        assert result.degraded is True
        assert result.findings == []
