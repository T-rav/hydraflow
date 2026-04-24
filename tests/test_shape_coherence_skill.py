"""Unit tests for the shape-coherence skill."""

from __future__ import annotations

from shape_coherence import (
    build_shape_coherence_prompt,
    parse_shape_coherence_result,
)


class TestBuildShapeCoherencePrompt:
    def test_embeds_discover_brief_and_proposal(self):
        prompt = build_shape_coherence_prompt(
            issue_number=42,
            issue_title="Add login",
            discover_brief="## Intent\nAdd login\n## Open questions\n- What SSO?",
            proposal="## Option A: OAuth\n## Option B: SAML\n## Defer",
        )
        assert "#42" in prompt
        assert "Add login" in prompt
        assert "What SSO?" in prompt
        assert "Option A: OAuth" in prompt

    def test_empty_discover_brief_ok(self):
        """Shape can evaluate proposals even without upstream Discover."""
        prompt = build_shape_coherence_prompt(
            issue_number=1,
            issue_title="T",
            proposal="proposal text",
        )
        assert "#1" in prompt
        assert "proposal text" in prompt
        assert "SHAPE_COHERENCE_RESULT" in prompt

    def test_rubric_keywords_embedded(self):
        """All five RETRY keywords must appear in the prompt verbatim."""
        prompt = build_shape_coherence_prompt(
            issue_number=1,
            issue_title="T",
            discover_brief="b",
            proposal="p",
        )
        assert "too-few-options" in prompt
        assert "missing-defer" in prompt
        assert "options-overlap" in prompt
        assert "missing-tradeoffs" in prompt
        assert "dropped-discover-question" in prompt

    def test_accepts_unknown_kwargs(self):
        """Skill-registry dispatch passes diff=/plan_text=/etc — must tolerate."""
        prompt = build_shape_coherence_prompt(
            issue_number=1,
            issue_title="T",
            discover_brief="b",
            proposal="p",
            diff="ignored",
            plan_text="ignored",
        )
        assert prompt  # didn't raise


class TestParseShapeCoherenceResult:
    def test_ok_passes(self):
        passed, summary, findings = parse_shape_coherence_result(
            "SHAPE_COHERENCE_RESULT: OK\nSUMMARY: All five rubric criteria pass\n"
        )
        assert passed is True
        assert "All five" in summary
        assert findings == []

    def test_missing_marker_fails_open(self):
        passed, summary, _ = parse_shape_coherence_result("")
        assert passed is True
        assert "No explicit result marker" in summary

    def test_retry_keyword_too_few_options(self):
        transcript = (
            "SHAPE_COHERENCE_RESULT: RETRY\n"
            "SUMMARY: too-few-options — only one option listed\n"
            "FINDINGS:\n"
            "- too-few-options — proposal contains a single option\n"
        )
        passed, summary, findings = parse_shape_coherence_result(transcript)
        assert passed is False
        assert "too-few-options" in summary
        assert len(findings) == 1

    def test_retry_keyword_missing_defer(self):
        transcript = (
            "SHAPE_COHERENCE_RESULT: RETRY\n"
            "SUMMARY: missing-defer — no do-nothing option\n"
            "FINDINGS:\n"
            "- missing-defer — every option proposes action\n"
        )
        passed, summary, _ = parse_shape_coherence_result(transcript)
        assert passed is False
        assert "missing-defer" in summary

    def test_retry_keyword_options_overlap(self):
        transcript = (
            "SHAPE_COHERENCE_RESULT: RETRY\n"
            "SUMMARY: options-overlap — A and B both edit src/foo.py\n"
            "FINDINGS:\n"
            "- options-overlap — A and B touch identical files\n"
        )
        passed, summary, _ = parse_shape_coherence_result(transcript)
        assert passed is False
        assert "options-overlap" in summary

    def test_retry_keyword_missing_tradeoffs(self):
        transcript = (
            "SHAPE_COHERENCE_RESULT: RETRY\n"
            "SUMMARY: missing-tradeoffs — option A lists only upsides\n"
            "FINDINGS:\n"
            "- missing-tradeoffs — no cost named for option A\n"
        )
        passed, summary, _ = parse_shape_coherence_result(transcript)
        assert passed is False
        assert "missing-tradeoffs" in summary

    def test_retry_keyword_dropped_discover_question(self):
        transcript = (
            "SHAPE_COHERENCE_RESULT: RETRY\n"
            "SUMMARY: dropped-discover-question — SSO question unaddressed\n"
            "FINDINGS:\n"
            "- dropped-discover-question — 'What SSO provider?' not resolved\n"
        )
        passed, summary, _ = parse_shape_coherence_result(transcript)
        assert passed is False
        assert "dropped-discover-question" in summary

    def test_findings_block_parsed_multiline(self):
        transcript = (
            "SHAPE_COHERENCE_RESULT: RETRY\n"
            "SUMMARY: missing-tradeoffs — first of several\n"
            "FINDINGS:\n"
            "- missing-tradeoffs — option A lacks cost\n"
            "- missing-tradeoffs — option B lacks risk\n"
        )
        passed, _, findings = parse_shape_coherence_result(transcript)
        assert passed is False
        assert len(findings) == 2
