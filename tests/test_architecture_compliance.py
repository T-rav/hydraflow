"""Tests for the architecture_compliance skill — prompt builder and result parser."""

from __future__ import annotations

from architecture_compliance import (
    build_architecture_compliance_prompt,
    parse_architecture_compliance_result,
)


class TestBuildArchitectureCompliancePrompt:
    def test_includes_issue_number(self) -> None:
        prompt = build_architecture_compliance_prompt(
            issue_number=42, issue_title="Fix auth", diff="+ new line"
        )
        assert "#42" in prompt

    def test_includes_issue_title(self) -> None:
        prompt = build_architecture_compliance_prompt(
            issue_number=42, issue_title="Fix auth", diff="+ new line"
        )
        assert "Fix auth" in prompt

    def test_includes_diff(self) -> None:
        prompt = build_architecture_compliance_prompt(
            issue_number=42, issue_title="Fix auth", diff="+ added code"
        )
        assert "+ added code" in prompt

    def test_mentions_layer_model(self) -> None:
        prompt = build_architecture_compliance_prompt(
            issue_number=1, issue_title="Test", diff="diff"
        )
        assert "L1" in prompt
        assert "L4" in prompt

    def test_mentions_result_markers(self) -> None:
        prompt = build_architecture_compliance_prompt(
            issue_number=1, issue_title="Test", diff="diff"
        )
        assert "ARCHITECTURE_COMPLIANCE_RESULT: OK" in prompt
        assert "ARCHITECTURE_COMPLIANCE_RESULT: RETRY" in prompt

    def test_accepts_extra_kwargs(self) -> None:
        """Extra kwargs are accepted and ignored (forward compat)."""
        prompt = build_architecture_compliance_prompt(
            issue_number=1, issue_title="Test", diff="diff", plan_text="plan"
        )
        assert "#1" in prompt


class TestParseArchitectureComplianceResult:
    def test_ok_result(self) -> None:
        passed, summary, violations = parse_architecture_compliance_result(
            "ARCHITECTURE_COMPLIANCE_RESULT: OK\nSUMMARY: No architecture violations found"
        )
        assert passed is True
        assert "No architecture violations" in summary
        assert violations == []

    def test_retry_result_with_violations(self) -> None:
        transcript = (
            "ARCHITECTURE_COMPLIANCE_RESULT: RETRY\n"
            "SUMMARY: upward imports\n"
            "VIOLATIONS:\n"
            "- src/config.py:10 — imports from orchestrator (L1 importing L4)\n"
            "- src/models.py:5 — circular import with agent.py\n"
        )
        passed, summary, violations = parse_architecture_compliance_result(transcript)
        assert passed is False
        assert "upward imports" in summary
        assert len(violations) == 2

    def test_no_marker_defaults_to_pass(self) -> None:
        passed, summary, violations = parse_architecture_compliance_result(
            "Some random output with no markers"
        )
        assert passed is True
        assert violations == []

    def test_case_insensitive(self) -> None:
        passed, summary, violations = parse_architecture_compliance_result(
            "architecture_compliance_result: ok\nsummary: all good"
        )
        assert passed is True

    def test_retry_without_violations_section(self) -> None:
        passed, summary, violations = parse_architecture_compliance_result(
            "ARCHITECTURE_COMPLIANCE_RESULT: RETRY\nSUMMARY: issues found"
        )
        assert passed is False
        assert violations == []

    def test_empty_transcript(self) -> None:
        passed, summary, violations = parse_architecture_compliance_result("")
        assert passed is True
        assert violations == []
