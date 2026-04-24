"""Unit tests for the discover-completeness skill."""

from __future__ import annotations

from discover_completeness import (
    build_discover_completeness_prompt,
    parse_discover_completeness_result,
)


class TestBuildDiscoverCompletenessPrompt:
    def test_embeds_issue_body_and_brief(self):
        prompt = build_discover_completeness_prompt(
            issue_number=42,
            issue_title="Add login",
            issue_body="Maybe we add a login form? Not sure.",
            brief="## Intent\nAdd login\n## Affected area\nweb",
        )
        assert "#42" in prompt
        assert "Add login" in prompt
        assert "Maybe we add a login form?" in prompt
        assert "## Intent\nAdd login" in prompt

    def test_missing_issue_body_still_produces_valid_prompt(self):
        prompt = build_discover_completeness_prompt(
            issue_number=1,
            issue_title="T",
            brief="brief text",
        )
        assert "#1" in prompt
        assert "brief text" in prompt
        assert "DISCOVER_COMPLETENESS_RESULT" in prompt

    def test_rubric_headings_embedded(self):
        """The five-criterion rubric must be in the prompt verbatim."""
        prompt = build_discover_completeness_prompt(
            issue_number=1, issue_title="T", issue_body="b", brief="b"
        )
        assert "Structure." in prompt
        assert "Non-trivial content." in prompt
        assert "No paraphrase-only." in prompt
        assert "Concrete acceptance criteria." in prompt
        assert "Open questions when ambiguous." in prompt

    def test_accepts_unknown_kwargs(self):
        """Skill-registry dispatch passes diff=/plan_text=/etc — must tolerate."""
        prompt = build_discover_completeness_prompt(
            issue_number=1,
            issue_title="T",
            issue_body="b",
            brief="b",
            diff="ignored",
            plan_text="ignored",
        )
        assert prompt  # didn't raise


class TestParseDiscoverCompletenessResult:
    def test_ok_passes(self):
        passed, summary, findings = parse_discover_completeness_result(
            "DISCOVER_COMPLETENESS_RESULT: OK\nSUMMARY: All five rubric criteria pass\n"
        )
        assert passed is True
        assert "All five" in summary
        assert findings == []

    def test_missing_marker_fails_open(self):
        passed, summary, _ = parse_discover_completeness_result("")
        assert passed is True
        assert "No explicit result marker" in summary

    def test_retry_keyword_missing_section(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: missing-section:acceptance-criteria — no such section\n"
            "FINDINGS:\n"
            "- missing-section:acceptance-criteria — section is absent\n"
        )
        passed, summary, findings = parse_discover_completeness_result(transcript)
        assert passed is False
        assert "missing-section:acceptance-criteria" in summary
        assert len(findings) == 1
        assert "acceptance-criteria" in findings[0]

    def test_retry_keyword_shallow_section(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: shallow-section:open-questions — only one bullet\n"
            "FINDINGS:\n"
            "- shallow-section:open-questions — single bullet present\n"
        )
        passed, summary, _ = parse_discover_completeness_result(transcript)
        assert passed is False
        assert "shallow-section:open-questions" in summary

    def test_retry_keyword_paraphrase_only(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: paraphrase-only — brief is a rephrase of the issue body\n"
            "FINDINGS:\n"
            "- paraphrase-only — no new information added\n"
        )
        passed, summary, _ = parse_discover_completeness_result(transcript)
        assert passed is False
        assert "paraphrase-only" in summary

    def test_retry_keyword_vague_criterion(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: vague-criterion — 'make it faster' is not observable\n"
            "FINDINGS:\n"
            "- vague-criterion — 'faster' lacks a metric\n"
        )
        passed, summary, _ = parse_discover_completeness_result(transcript)
        assert passed is False
        assert "vague-criterion" in summary

    def test_retry_keyword_hid_ambiguity(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: hid-ambiguity — issue says 'maybe' but brief claims zero opens\n"
            "FINDINGS:\n"
            "- hid-ambiguity — 'maybe' in issue body not reflected in questions\n"
        )
        passed, summary, _ = parse_discover_completeness_result(transcript)
        assert passed is False
        assert "hid-ambiguity" in summary

    def test_findings_block_parsed_multiline(self):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            "SUMMARY: missing-section:intent — first of several\n"
            "FINDINGS:\n"
            "- missing-section:intent — no Intent heading\n"
            "- missing-section:known-unknowns — no Known Unknowns heading\n"
        )
        passed, _, findings = parse_discover_completeness_result(transcript)
        assert passed is False
        assert len(findings) == 2
