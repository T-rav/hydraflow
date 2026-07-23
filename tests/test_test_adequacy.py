"""Tests for test_adequacy module — prompt builder and result parser."""

from __future__ import annotations

from test_adequacy import (
    build_test_adequacy_prompt,
    build_test_adequacy_verifier_prompt,
    finder_asserted_adequate,
    parse_test_adequacy_result,
    parse_test_adequacy_verifier_result,
)


class TestBuildTestAdequacyPrompt:
    def test_includes_issue_context(self) -> None:
        prompt = build_test_adequacy_prompt(
            issue_number=99, issue_title="Add new feature", diff="--- a/f\n+++ b/f"
        )
        assert "#99" in prompt
        assert "Add new feature" in prompt

    def test_includes_diff(self) -> None:
        diff = "+def new_func():\n+    return 42"
        prompt = build_test_adequacy_prompt(issue_number=1, issue_title="T", diff=diff)
        assert diff in prompt

    def test_includes_structured_output_markers(self) -> None:
        prompt = build_test_adequacy_prompt(issue_number=1, issue_title="T", diff="")
        assert "TEST_ADEQUACY_RESULT: OK" in prompt
        assert "TEST_ADEQUACY_RESULT: RETRY" in prompt


class TestParseTestAdequacyResult:
    def test_ok_result(self) -> None:
        transcript = (
            "TEST_ADEQUACY_RESULT: OK\n"
            "SUMMARY: All changed code has adequate test coverage"
        )
        passed, summary, gaps = parse_test_adequacy_result(transcript)
        assert passed is True
        assert "adequate" in summary
        assert gaps == []

    def test_retry_result_with_gaps(self) -> None:
        transcript = (
            "TEST_ADEQUACY_RESULT: RETRY\n"
            "SUMMARY: missing edge case tests\n"
            "GAPS:\n"
            "- src/agent.py:run — no test for empty worktree\n"
            "- src/config.py:validate — no test for invalid env var\n"
        )
        passed, summary, gaps = parse_test_adequacy_result(transcript)
        assert passed is False
        assert "missing edge case" in summary
        assert len(gaps) == 2
        assert "empty worktree" in gaps[0]

    def test_missing_marker_defaults_to_pass(self) -> None:
        passed, summary, gaps = parse_test_adequacy_result("just some output")
        assert passed is True
        assert gaps == []

    def test_retry_without_gaps_section(self) -> None:
        transcript = "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: no tests at all"
        passed, summary, gaps = parse_test_adequacy_result(transcript)
        assert passed is False
        assert summary == "no tests at all"
        assert gaps == []

    def test_case_insensitive_marker(self) -> None:
        transcript = "test_adequacy_result: ok\nsummary: covered"
        passed, summary, _ = parse_test_adequacy_result(transcript)
        assert passed is True
        assert summary == "covered"


class TestFinderAssertedAdequate:
    """Explicit-OK verifier trigger (#9546) — stricter than the parser."""

    def test_explicit_ok_triggers(self) -> None:
        assert finder_asserted_adequate("TEST_ADEQUACY_RESULT: OK\nSUMMARY: fine")

    def test_case_insensitive(self) -> None:
        assert finder_asserted_adequate("test_adequacy_result: ok")

    def test_retry_does_not_trigger(self) -> None:
        assert not finder_asserted_adequate("TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: x")

    def test_no_marker_does_not_trigger_despite_parser_default_pass(self) -> None:
        """The parser default-passes a no-marker transcript; the trigger must not.

        Empty/garbled transcripts (FakeLLM scenarios, degraded runs) rely on
        the default-pass and must never grow a verifier dispatch.
        """
        transcript = "just some output"
        passed, _, _ = parse_test_adequacy_result(transcript)
        assert passed is True
        assert not finder_asserted_adequate(transcript)

    def test_empty_transcript_does_not_trigger(self) -> None:
        assert not finder_asserted_adequate("")


class TestBuildTestAdequacyVerifierPrompt:
    def test_includes_issue_context_and_diff(self) -> None:
        diff = "+def new_func():\n+    return 42"
        prompt = build_test_adequacy_verifier_prompt(
            issue_number=99, issue_title="Add feature", diff=diff
        )
        assert "#99" in prompt
        assert "Add feature" in prompt
        assert diff in prompt

    def test_includes_structured_output_markers(self) -> None:
        prompt = build_test_adequacy_verifier_prompt(
            issue_number=1, issue_title="T", diff=""
        )
        assert "TEST_ADEQUACY_VERIFIER_RESULT: CONCUR" in prompt
        assert "TEST_ADEQUACY_VERIFIER_RESULT: OVERRIDE" in prompt

    def test_does_not_disclose_finder_verdict(self) -> None:
        """Independence: the verifier must not see the finder's markers."""
        prompt = build_test_adequacy_verifier_prompt(
            issue_number=1, issue_title="T", diff="+x = 1"
        )
        assert "TEST_ADEQUACY_RESULT: OK" not in prompt
        assert "TEST_ADEQUACY_RESULT: RETRY" not in prompt

    def test_tolerates_extra_kwargs(self) -> None:
        """_run_skill-style callers may thread extra kwargs (e.g. plan_text)."""
        prompt = build_test_adequacy_verifier_prompt(
            issue_number=1, issue_title="T", diff="", plan_text="ignored"
        )
        assert prompt


class TestParseTestAdequacyVerifierResult:
    def test_concur(self) -> None:
        confirmed, summary, gaps = parse_test_adequacy_verifier_result(
            "TEST_ADEQUACY_VERIFIER_RESULT: CONCUR\nSUMMARY: independently confirmed"
        )
        assert confirmed is True
        assert "confirmed" in summary
        assert gaps == []

    def test_override_with_gaps(self) -> None:
        transcript = (
            "TEST_ADEQUACY_VERIFIER_RESULT: OVERRIDE\n"
            "SUMMARY: error paths untested\n"
            "GAPS:\n"
            "- src/foo.py:bar — raise branch untested\n"
            "- src/baz.py:qux — no boundary test\n"
        )
        confirmed, summary, gaps = parse_test_adequacy_verifier_result(transcript)
        assert confirmed is False
        assert "error paths" in summary
        assert len(gaps) == 2
        assert "raise branch" in gaps[0]

    def test_missing_marker_defaults_to_confirmed(self) -> None:
        """Fail-soft mirror of the finder parser; caller applies fail_closed."""
        confirmed, summary, gaps = parse_test_adequacy_verifier_result("no marker")
        assert confirmed is True
        assert gaps == []
        assert "No explicit" in summary

    def test_case_insensitive(self) -> None:
        confirmed, _, _ = parse_test_adequacy_verifier_result(
            "test_adequacy_verifier_result: override\nsummary: gaps"
        )
        assert confirmed is False

    def test_finder_ok_marker_alone_does_not_read_as_verifier_concur(self) -> None:
        """The verifier parser must key on its own marker, not the finder's."""
        confirmed, summary, _ = parse_test_adequacy_verifier_result(
            "TEST_ADEQUACY_RESULT: OK\nSUMMARY: adequate"
        )
        # No VERIFIER marker present → fail-soft default, not a real CONCUR.
        assert confirmed is True
        assert "No explicit" in summary
