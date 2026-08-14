"""Unit tests for the model-backed SpecReviewer (#10830 phase 2)."""

from __future__ import annotations

import sys
from pathlib import Path

from spec_intake_gate import (
    ContradictionKind,
    DivergenceKind,
    Severity,
    SpecReview,
    assess,
)
from spec_reviewer import (
    CLISpecReviewer,
    build_spec_review_prompt,
    parse_spec_review,
)

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from spec_intake_review import render_verdict  # noqa: E402

_FULL_PAYLOAD = """
Reasoning first, as instructed...

{"contradictions":[{"kind":"code","severity":"high",
"quote":"the loop retries forever","explanation":"base_runner caps attempts"}],
"divergences":[{"kind":"diverges_from_practice",
"quote":"the optimizer edits code","explanation":"ADR-0120 forbids plant edits"}],
"load_bearing_assertions":[{"claim":"unsigned setpoints are inert",
"severity":"high"}],
"unstated_assumptions":["a calibration ledger exists"]}
"""


class TestPrompt:
    def test_prompt_carries_the_three_checks_and_reason_first(self) -> None:
        prompt = build_spec_review_prompt("Doc body", subject_id="spec:foo")
        assert '"internal"' in prompt
        assert '"corpus"' in prompt
        assert '"code"' in prompt
        assert "Reason first" in prompt
        assert "diverges_from_practice" in prompt
        assert "VERBATIM" in prompt
        assert "Doc body" in prompt

    def test_document_is_bounded(self) -> None:
        prompt = build_spec_review_prompt("x" * 100_000, subject_id="s")
        assert len(prompt) < 60_000


class TestParse:
    def test_full_payload_parses_all_four_categories(self) -> None:
        review = parse_spec_review(_FULL_PAYLOAD)
        assert review.contradictions[0].kind is ContradictionKind.CODE
        assert review.contradictions[0].severity is Severity.HIGH
        assert review.divergences[0].kind is DivergenceKind.DIVERGES_FROM_PRACTICE
        assert review.load_bearing_assertions[0].severity is Severity.HIGH
        assert review.unstated_assumptions == ("a calibration ledger exists",)

    def test_no_json_degrades_to_empty_review(self) -> None:
        assert parse_spec_review("no json here") == SpecReview()

    def test_malformed_json_degrades_to_empty_review(self) -> None:
        assert parse_spec_review("{not json") == SpecReview()

    def test_malformed_findings_dropped_individually(self) -> None:
        payload = (
            '{"contradictions":[{"kind":"nonsense","severity":"high",'
            '"quote":"q","explanation":"e"},'
            '{"kind":"internal","severity":"low","quote":"q2","explanation":"e2"}],'
            '"divergences":[{"kind":"also-nonsense","quote":"q","explanation":"e"}],'
            '"load_bearing_assertions":[{"claim":"","severity":"high"}],'
            '"unstated_assumptions":["  ", "real one"]}'
        )
        review = parse_spec_review(payload)
        assert len(review.contradictions) == 1
        assert review.contradictions[0].kind is ContradictionKind.INTERNAL
        assert review.divergences == ()
        assert review.load_bearing_assertions == ()
        assert review.unstated_assumptions == ("real one",)


class TestCLISpecReviewer:
    def test_happy_path_through_assess(self) -> None:
        reviewer = CLISpecReviewer(lambda _prompt: _FULL_PAYLOAD)
        verdict = assess("doc", subject_id="spec:foo", reviewer=reviewer)
        assert verdict.headline_severity is Severity.HIGH
        assert len(verdict.contradictions) == 1

    def test_completion_failure_degrades_to_deterministic_floor(self) -> None:
        def _boom(_prompt: str) -> str:
            raise RuntimeError("spawn failed")

        reviewer = CLISpecReviewer(_boom)
        verdict = assess(
            "The gate MUST record 1 row.", subject_id="s", reviewer=reviewer
        )
        # Reviewer findings empty, but the deterministic metric still landed.
        assert verdict.contradictions == ()
        assert verdict.falsifiability.total_statements > 0


class TestRenderVerdict:
    def test_renders_headline_and_findings(self) -> None:
        reviewer = CLISpecReviewer(lambda _prompt: _FULL_PAYLOAD)
        verdict = assess("doc", subject_id="spec:foo", reviewer=reviewer)
        out = render_verdict(verdict)
        assert "headline severity: high" in out
        assert "CONTRADICTION [code/high]" in out
        assert "DIVERGENCE [diverges_from_practice]" in out
        assert "UNSTATED ASSUMPTION: a calibration ledger exists" in out

    def test_deterministic_only_render_is_calm(self) -> None:
        verdict = assess("The gate MUST record 1 row.", subject_id="s")
        out = render_verdict(verdict)
        assert "no reviewer findings" in out
