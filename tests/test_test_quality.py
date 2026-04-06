"""Tests for the test_quality skill — prompt builder and result parser."""

from __future__ import annotations

from test_quality import build_test_quality_prompt, parse_test_quality_result


class TestBuildTestQualityPrompt:
    def test_includes_issue_number(self) -> None:
        prompt = build_test_quality_prompt(
            issue_number=99, issue_title="Add tests", diff="+ test code"
        )
        assert "#99" in prompt

    def test_includes_issue_title(self) -> None:
        prompt = build_test_quality_prompt(
            issue_number=99, issue_title="Add tests", diff="+ test code"
        )
        assert "Add tests" in prompt

    def test_includes_diff(self) -> None:
        prompt = build_test_quality_prompt(
            issue_number=99, issue_title="Add tests", diff="+ test_helper()"
        )
        assert "+ test_helper()" in prompt

    def test_mentions_duplicate_helpers(self) -> None:
        prompt = build_test_quality_prompt(
            issue_number=1, issue_title="Test", diff="diff"
        )
        assert "Duplicate test helpers" in prompt or "duplicate" in prompt.lower()

    def test_mentions_result_markers(self) -> None:
        prompt = build_test_quality_prompt(
            issue_number=1, issue_title="Test", diff="diff"
        )
        assert "TEST_QUALITY_RESULT: OK" in prompt
        assert "TEST_QUALITY_RESULT: RETRY" in prompt

    def test_accepts_extra_kwargs(self) -> None:
        """Extra kwargs are accepted and ignored (forward compat)."""
        prompt = build_test_quality_prompt(
            issue_number=1, issue_title="Test", diff="diff", plan_text="plan"
        )
        assert "#1" in prompt


class TestParseTestQualityResult:
    def test_ok_result(self) -> None:
        passed, summary, issues = parse_test_quality_result(
            "TEST_QUALITY_RESULT: OK\nSUMMARY: Test quality is acceptable"
        )
        assert passed is True
        assert "acceptable" in summary
        assert issues == []

    def test_retry_result_with_issues(self) -> None:
        transcript = (
            "TEST_QUALITY_RESULT: RETRY\n"
            "SUMMARY: duplicate helpers, naming\n"
            "ISSUES:\n"
            "- tests/test_foo.py:make_config — duplicates tests/helpers.py:ConfigFactory\n"
            "- tests/test_bar.py:test_it — non-descriptive test name\n"
        )
        passed, summary, issues = parse_test_quality_result(transcript)
        assert passed is False
        assert "duplicate" in summary
        assert len(issues) == 2

    def test_no_marker_defaults_to_pass(self) -> None:
        passed, summary, issues = parse_test_quality_result(
            "Some random output with no markers"
        )
        assert passed is True
        assert issues == []

    def test_case_insensitive(self) -> None:
        passed, summary, issues = parse_test_quality_result(
            "test_quality_result: ok\nsummary: all good"
        )
        assert passed is True

    def test_retry_without_issues_section(self) -> None:
        passed, summary, issues = parse_test_quality_result(
            "TEST_QUALITY_RESULT: RETRY\nSUMMARY: problems found"
        )
        assert passed is False
        assert issues == []

    def test_empty_transcript(self) -> None:
        passed, summary, issues = parse_test_quality_result("")
        assert passed is True
        assert issues == []
