"""Unit tests for the spec intake gate (#10830)."""

from __future__ import annotations

from spec_intake_gate import (
    Contradiction,
    ContradictionKind,
    Divergence,
    DivergenceKind,
    LoadBearingAssertion,
    Severity,
    SpecReview,
    assess,
    falsifiability_report,
    is_checkable,
    max_severity,
    verdict_row,
)


class _FakeReviewer:
    def __init__(self, review: SpecReview) -> None:
        self._review = review

    def review(self, document: str, *, subject_id: str) -> SpecReview:
        return self._review


# --- max-severity aggregation (no mean) ------------------------------------


def test_max_severity_is_the_highest_not_a_mean() -> None:
    assert max_severity([Severity.LOW, Severity.HIGH, Severity.INFO]) is Severity.HIGH
    # One HIGH in a sea of trivia is not averaged away — the whole point.
    assert max_severity([Severity.INFO, Severity.INFO, Severity.HIGH]) is Severity.HIGH


def test_max_severity_of_empty_is_info() -> None:
    assert max_severity([]) is Severity.INFO


# --- falsifiability / claim-density (the required deterministic metric) -----


def test_checkable_sentences_are_detected_by_each_marker() -> None:
    assert is_checkable(
        "The loop MUST NOT retry more than 3 times."
    )  # normative + number
    assert is_checkable("It reads `finder_calibration.py` on boot.")  # code span
    assert is_checkable("The value lives in src/config.py somewhere.")  # path
    assert is_checkable("Poll every 60 seconds.")  # number
    assert is_checkable("Call config.data_root to resolve it.")  # dotted symbol


def test_vague_sentences_are_not_checkable() -> None:
    assert not is_checkable("The system should generally behave appropriately.")
    assert not is_checkable("We want a clean and robust design.")


def test_claim_density_and_mush_are_measured() -> None:
    text = (
        "The loop MUST poll every 60 seconds. "
        "It reads `state.json` on boot. "
        "The design should generally be clean and robust. "
        "Things ought to be reasonable where possible."
    )
    report = falsifiability_report(text)
    assert report.total_statements == 4
    assert report.checkable_count == 2  # the two concrete sentences
    assert report.claim_density == 0.5
    assert report.hedge_only_count == 2
    assert any("clean and robust" in s for s in report.mushiest)


def test_empty_document_is_zero_density_not_a_crash() -> None:
    report = falsifiability_report("   \n  ")
    assert report.total_statements == 0
    assert report.claim_density == 0.0
    assert report.mushiest == ()


# --- assess: deterministic-only vs injected reviewer ------------------------


def test_assess_without_a_reviewer_still_computes_falsifiability() -> None:
    verdict = assess("The loop MUST poll every 60 seconds.", subject_id="adr:0001")
    assert verdict.subject_id == "adr:0001"
    assert verdict.contradictions == ()  # no reviewer -> no model findings
    assert verdict.falsifiability.checkable_count == 1
    assert verdict.headline_severity is Severity.INFO  # no load-bearing assertions


def test_assess_threads_the_reviewers_findings_through() -> None:
    review = SpecReview(
        contradictions=(
            Contradiction(ContradictionKind.CODE, Severity.HIGH, "asserts X", "no X"),
        ),
        load_bearing_assertions=(
            LoadBearingAssertion("the queue is FIFO", Severity.HIGH),
            LoadBearingAssertion("logs are JSON", Severity.LOW),
        ),
        unstated_assumptions=("assumes a single repo",),
    )
    verdict = assess("body", subject_id="spec:x", reviewer=_FakeReviewer(review))
    assert verdict.has_contradictions
    assert verdict.headline_severity is Severity.HIGH  # max over load-bearing
    assert verdict.unstated_assumptions == ("assumes a single repo",)


# --- verdict row: fact vs practice separation + mush flag -------------------


def test_verdict_row_keeps_contradicted_by_fact_out_of_practice_count() -> None:
    review = SpecReview(
        divergences=(
            Divergence(DivergenceKind.DIVERGES_FROM_PRACTICE, "novel idea", "new"),
            Divergence(DivergenceKind.CONTRADICTED_BY_FACT, "wrong claim", "false"),
        ),
    )
    verdict = assess(
        "The loop MUST poll every 60 seconds.",
        subject_id="spec:x",
        reviewer=_FakeReviewer(review),
    )
    row = verdict_row(verdict, recorded_at="2026-08-06T00:00:00+00:00")
    # Only the diverges-from-practice one counts here — never merged with fact.
    assert row.diverges_from_practice_count == 1


def test_verdict_row_flags_mush_below_the_density_floor() -> None:
    mushy = (
        "It should generally be clean. Things ought to be reasonable. Nice and simple."
    )
    verdict = assess(mushy, subject_id="spec:mush")
    row = verdict_row(verdict, recorded_at="2026-08-06T00:00:00+00:00")
    assert row.claim_density < 0.25
    assert row.mush_flagged is True
