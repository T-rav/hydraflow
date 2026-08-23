"""Unit tests for the sampled-audit machine adjudication (ADR-0115).

Pins the fail-soft parser (a malformed / ambiguous response collapses to
``inconclusive`` → a human, never a fabricated upheld/refuted) and the prompt
shape (the adjudicator IS shown the auditor's finding — unlike the re-audit
prompt, which withholds all prior verdicts).
"""

from __future__ import annotations

import pytest

from audit.adjudicate import (
    ADJUDICATION_VERDICTS,
    build_adjudication_prompt,
    parse_adjudication,
)
from audit.models import AUDIT_INPUT_SOURCES, AuditSample


def _sample(
    findings: str = "unchecked index into a possibly-empty list",
) -> AuditSample:
    return AuditSample(
        id="55:abc123def456",
        audited_at="2026-01-01T00:00:00+00:00",
        pr_number=55,
        merge_sha="abc123def456",
        blast_radius_class="structural",
        verdict="disagree",
        findings=findings,
        input_sources=AUDIT_INPUT_SOURCES,
        auditor_model="sonnet",
        sample_rate=0.1,
        disposition="pending",
        find_issue=901,
    )


class TestParseAdjudication:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            pytest.param(
                '{"verdict": "upheld", "rationale": "real off-by-one"}',
                ("upheld", "real off-by-one"),
                id="test_upheld",
            ),
            pytest.param(
                '{"verdict": "refuted", "rationale": "guarded above"}',
                ("refuted", "guarded above"),
                id="test_refuted",
            ),
            pytest.param(
                '{"verdict": "inconclusive", "rationale": "need runtime context"}',
                ("inconclusive", "need runtime context"),
                id="test_explicit_inconclusive",
            ),
            pytest.param(
                'Here is my call:\n{"verdict": "upheld", "rationale": "x"}\nDone.',
                ("upheld", "x"),
                id="test_json_embedded_in_prose",
            ),
            pytest.param(
                '{"verdict": "maybe", "rationale": "hedging"}',
                ("inconclusive", "hedging"),
                id="test_unknown_verdict_token_is_inconclusive",
            ),
        ],
    )
    def test_parses_verdict_and_rationale(
        self, raw: str, expected: tuple[str, str]
    ) -> None:
        assert parse_adjudication(raw) == expected

    def test_unparseable_is_inconclusive_not_upheld(self) -> None:
        # Fail-soft toward a HUMAN: a malformed response must never fabricate an
        # upheld (a false escape cross-link) or a refuted (a suppressed escape).
        verdict, rationale = parse_adjudication("total garbage, no json here")
        assert verdict == "inconclusive"
        assert "garbage" in rationale

    def test_empty_is_inconclusive(self) -> None:
        assert parse_adjudication("")[0] == "inconclusive"

    def test_verdicts_constant(self) -> None:
        assert set(ADJUDICATION_VERDICTS) == {"upheld", "refuted", "inconclusive"}


class TestBuildAdjudicationPrompt:
    def test_prompt_shows_the_auditor_finding(self) -> None:
        prompt = build_adjudication_prompt(_sample(), diff="@@ -1 +1 @@\n-a\n+b\n")
        # Adjudication is the step that JUDGES the auditor's claim, so unlike the
        # re-audit prompt it MUST include the finding.
        assert "unchecked index" in prompt
        assert "#55" in prompt
        assert "STRICT JSON" in prompt
        # It must offer all three verdicts, inconclusive included.
        for verdict in ("upheld", "refuted", "inconclusive"):
            assert verdict in prompt

    def test_prompt_truncates_a_huge_diff(self) -> None:
        prompt = build_adjudication_prompt(_sample(), diff="x" * 1_000_000)
        assert len(prompt) < 200_000
