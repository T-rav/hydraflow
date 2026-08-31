"""Unit tests for the discover-completeness skill."""

from __future__ import annotations

import pytest

from discover_completeness import (
    build_discover_completeness_prompt,
    parse_discover_completeness_result,
)
from human_steering import fenced_steering_guidance


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

    def test_folds_fenced_human_steering_guidance(self):
        """ADR-0099 #4 — live operator guidance is folded in FENCED.

        This is the second of discover's two prompt-construction sites
        (the first being ``DiscoverRunner._build_prompt``). Guidance must
        reach the prompt only via ``fenced_steering_guidance`` — never as
        raw comment text (ADR-0092 fence invariant).
        """
        guidance = "Prioritize the enterprise SSO angle over consumer features."
        prompt = build_discover_completeness_prompt(
            issue_number=1,
            issue_title="T",
            issue_body="b",
            brief="b",
            guidance=guidance,
        )
        assert "## Human Steering Guidance" in prompt
        assert fenced_steering_guidance(guidance) in prompt

    def test_empty_guidance_produces_no_steering_section(self):
        """No guidance posted -> no steering section (unchanged behavior)."""
        prompt = build_discover_completeness_prompt(
            issue_number=1,
            issue_title="T",
            issue_body="b",
            brief="b",
            guidance="",
        )
        assert "## Human Steering Guidance" not in prompt


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

    @pytest.mark.parametrize(
        ("keyword", "summary_tail", "finding_tail"),
        [
            pytest.param(
                "shallow-section:open-questions",
                "only one bullet",
                "single bullet present",
                id="retry_keyword_shallow_section",
            ),
            pytest.param(
                "paraphrase-only",
                "brief is a rephrase of the issue body",
                "no new information added",
                id="retry_keyword_paraphrase_only",
            ),
            pytest.param(
                "vague-criterion",
                "'make it faster' is not observable",
                "'faster' lacks a metric",
                id="retry_keyword_vague_criterion",
            ),
            pytest.param(
                "hid-ambiguity",
                "issue says 'maybe' but brief claims zero opens",
                "'maybe' in issue body not reflected in questions",
                id="retry_keyword_hid_ambiguity",
            ),
        ],
    )
    def test_retry_keyword_reaches_the_summary(
        self, keyword: str, summary_tail: str, finding_tail: str
    ):
        transcript = (
            "DISCOVER_COMPLETENESS_RESULT: RETRY\n"
            f"SUMMARY: {keyword} — {summary_tail}\n"
            "FINDINGS:\n"
            f"- {keyword} — {finding_tail}\n"
        )
        passed, summary, _ = parse_discover_completeness_result(transcript)
        assert passed is False
        assert keyword in summary

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
