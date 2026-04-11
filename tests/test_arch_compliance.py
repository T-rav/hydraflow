"""Tests for arch_compliance module — prompt builder and result parser."""

from __future__ import annotations

from arch_compliance import build_arch_compliance_prompt, parse_arch_compliance_result


class TestBuildArchCompliancePrompt:
    def test_includes_issue_context(self) -> None:
        prompt = build_arch_compliance_prompt(
            issue_number=42, issue_title="Fix the widget", diff="--- a/f\n+++ b/f"
        )
        assert "#42" in prompt
        assert "Fix the widget" in prompt

    def test_includes_diff(self) -> None:
        diff = "+import os\n-import sys"
        prompt = build_arch_compliance_prompt(
            issue_number=1, issue_title="T", diff=diff
        )
        assert diff in prompt

    def test_includes_structured_output_markers(self) -> None:
        prompt = build_arch_compliance_prompt(issue_number=1, issue_title="T", diff="")
        assert "ARCH_COMPLIANCE_RESULT: OK" in prompt
        assert "ARCH_COMPLIANCE_RESULT: RETRY" in prompt

    def test_includes_layer_model(self) -> None:
        prompt = build_arch_compliance_prompt(issue_number=1, issue_title="T", diff="")
        assert "Layer 1" in prompt
        assert "Layer 2" in prompt
        assert "Layer 3" in prompt
        assert "Layer 4" in prompt
        # Key modules must be assigned to layers
        assert "models.py" in prompt
        assert "config.py" in prompt
        assert "orchestrator.py" in prompt
        assert "base_runner.py" in prompt
        assert "pr_manager.py" in prompt
        assert "service_registry.py" in prompt

    def test_checks_five_violation_categories(self) -> None:
        prompt = build_arch_compliance_prompt(issue_number=1, issue_title="T", diff="")
        # All five categories from the issue spec
        assert "layer boundary" in prompt.lower() or "Layer boundary" in prompt
        assert "coupling" in prompt.lower()
        assert "pollution" in prompt.lower()
        assert "abstraction" in prompt.lower()
        assert "bypass" in prompt.lower() or "Bypass" in prompt

    def test_accepts_extra_kwargs(self) -> None:
        """Prompt builder should accept **_kwargs for forward compatibility."""
        prompt = build_arch_compliance_prompt(
            issue_number=1, issue_title="T", diff="", plan_text="some plan"
        )
        assert isinstance(prompt, str)

    def test_mentions_service_registry_exemption(self) -> None:
        """service_registry.py is the composition root and exempt from layer checks."""
        prompt = build_arch_compliance_prompt(issue_number=1, issue_title="T", diff="")
        assert "service_registry" in prompt
        assert "composition root" in prompt.lower() or "exempt" in prompt.lower()

    def test_conservative_language(self) -> None:
        """Prompt should include conservative guidance to avoid false positives."""
        prompt = build_arch_compliance_prompt(issue_number=1, issue_title="T", diff="")
        assert "clear violation" in prompt.lower() or "only flag" in prompt.lower()


class TestParseArchComplianceResult:
    def test_ok_result(self) -> None:
        transcript = "ARCH_COMPLIANCE_RESULT: OK\nSUMMARY: No violations found"
        passed, summary, findings = parse_arch_compliance_result(transcript)
        assert passed is True
        assert summary == "No violations found"
        assert findings == []

    def test_retry_result_with_violations(self) -> None:
        transcript = (
            "ARCH_COMPLIANCE_RESULT: RETRY\n"
            "SUMMARY: layer boundary violation, bypass detection\n"
            "VIOLATIONS:\n"
            "- [HIGH] src/planner.py:15 - imports pr_manager (Layer 3→4) - use port instead\n"
            "- [MEDIUM] src/review_phase.py:42 - direct subprocess.run - use runner adapter\n"
        )
        passed, summary, findings = parse_arch_compliance_result(transcript)
        assert passed is False
        assert "layer boundary" in summary
        assert len(findings) == 2
        assert "planner.py" in findings[0]

    def test_missing_marker_defaults_to_pass(self) -> None:
        passed, summary, findings = parse_arch_compliance_result("no markers here")
        assert passed is True
        assert findings == []

    def test_retry_without_violations_section(self) -> None:
        transcript = "ARCH_COMPLIANCE_RESULT: RETRY\nSUMMARY: coupling detected"
        passed, summary, findings = parse_arch_compliance_result(transcript)
        assert passed is False
        assert summary == "coupling detected"
        assert findings == []

    def test_case_insensitive_marker(self) -> None:
        transcript = "arch_compliance_result: ok\nsummary: all clean"
        passed, summary, _ = parse_arch_compliance_result(transcript)
        assert passed is True
        assert summary == "all clean"

    def test_empty_transcript(self) -> None:
        passed, summary, findings = parse_arch_compliance_result("")
        assert passed is True
        assert findings == []
