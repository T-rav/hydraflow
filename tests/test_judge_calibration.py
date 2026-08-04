"""Unit tests for the judge-calibration pure core (#10836).

Fast, subprocess-free, LLM-free: exercises the proper-scoring math
(``to_forecast``, ``brier_score``, ``log_score``, ``calibration_curve``,
``calibration_error``, ``discrimination``), the verdict↔outcome join
(``resolve``), the grace-window outcome resolution (``resolve_outcomes`` /
``EscapeLedgerOutcomeResolver``), the per-judge aggregation (``score_judge`` /
``score_all``), the append-only ledger round-trip, and the fail-soft recorder.
Known distributions with hand-computed expectations so the statistics are
pinned, not merely exercised.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from judge_calibration import (
    DEFAULT_GRACE_WINDOW,
    LOG_SCORE_EPS,
    MIN_CONFIDENT_RESOLVED,
    CalibrationBin,
    EscapeLedgerOutcomeResolver,
    JudgeCalibrationLedger,
    JudgeVerdictRecord,
    Outcome,
    ResolvedForecast,
    Verdict,
    brier_score,
    calibration_curve,
    calibration_error,
    discrimination,
    escaped_subjects,
    judge_verdict_ledger_path,
    log_score,
    record_verdict,
    resolve,
    resolve_outcomes,
    score_all,
    score_judge,
    subject_for_issue,
    subject_for_pr,
    to_forecast,
)

_NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)


def _forecast(predicted: float, actual: bool, judge: str = "j") -> ResolvedForecast:
    return ResolvedForecast(
        judge_id=judge,
        judge_family="fam",
        subject_id=f"pr:{predicted}",
        predicted_good=predicted,
        actual_good=actual,
    )


def _verdict(
    subject: str,
    verdict: Verdict,
    confidence: float,
    *,
    judge: str = "post_verify",
    at: datetime = _NOW,
) -> JudgeVerdictRecord:
    return JudgeVerdictRecord(
        judge_id=judge,
        judge_family="review_advisor",
        subject_id=subject,
        verdict=verdict,
        confidence=confidence,
        recorded_at=at,
    )


# --- subject keying -----------------------------------------------------------


def test_subject_for_pr_and_issue_are_distinct_namespaces() -> None:
    assert subject_for_pr(123) == "pr:123"
    assert subject_for_issue(123) == "issue:123"
    assert subject_for_pr(123) != subject_for_issue(123)


# --- to_forecast --------------------------------------------------------------


def test_to_forecast_pass_maps_confidence_to_p_good() -> None:
    assert to_forecast(Verdict.PASS, 0.9) == pytest.approx(0.9)


def test_to_forecast_fail_maps_confidence_to_one_minus() -> None:
    # FAIL @ 0.9 = 90% sure it is bad = 10% good.
    assert to_forecast(Verdict.FAIL, 0.9) == pytest.approx(0.1)


def test_to_forecast_clamps_out_of_range_confidence() -> None:
    assert to_forecast(Verdict.PASS, 1.5) == pytest.approx(1.0)
    assert to_forecast(Verdict.PASS, -0.2) == pytest.approx(0.0)
    assert to_forecast(Verdict.FAIL, 1.5) == pytest.approx(0.0)


# --- resolve (join) -----------------------------------------------------------


def test_resolve_joins_verdict_to_outcome_by_subject() -> None:
    verdicts = [_verdict("pr:1", Verdict.PASS, 0.8)]
    outcomes = [Outcome("pr:1", good=True)]
    resolved = resolve(verdicts, outcomes)
    assert len(resolved) == 1
    assert resolved[0].predicted_good == pytest.approx(0.8)
    assert resolved[0].actual_good is True


def test_resolve_drops_verdicts_with_no_outcome() -> None:
    verdicts = [
        _verdict("pr:1", Verdict.PASS, 0.8),
        _verdict("pr:2", Verdict.FAIL, 0.7),  # no outcome for pr:2
    ]
    outcomes = [Outcome("pr:1", good=True)]
    resolved = resolve(verdicts, outcomes)
    assert [r.subject_id for r in resolved] == ["pr:1"]


# --- brier_score --------------------------------------------------------------


def test_brier_score_perfect_is_zero() -> None:
    forecasts = [_forecast(1.0, True), _forecast(0.0, False)]
    assert brier_score(forecasts) == pytest.approx(0.0)


def test_brier_score_always_half_is_quarter() -> None:
    forecasts = [_forecast(0.5, True), _forecast(0.5, False)]
    assert brier_score(forecasts) == pytest.approx(0.25)


def test_brier_score_empty_is_none() -> None:
    assert brier_score([]) is None


# --- log_score ----------------------------------------------------------------


def test_log_score_half_is_ln2() -> None:
    forecasts = [_forecast(0.5, True), _forecast(0.5, False)]
    assert log_score(forecasts) == pytest.approx(math.log(2))


def test_log_score_confident_wrong_is_large_but_finite() -> None:
    # p==0 for a good outcome would be +inf without clipping.
    score = log_score([_forecast(0.0, True)])
    assert score is not None
    assert math.isfinite(score)
    assert score == pytest.approx(-math.log(LOG_SCORE_EPS))
    assert score > 30


def test_log_score_empty_is_none() -> None:
    assert log_score([]) is None


# --- calibration_curve --------------------------------------------------------


def test_calibration_curve_bins_and_computes_rates() -> None:
    forecasts = [
        _forecast(0.9, True),
        _forecast(0.9, False),  # bin 9: mean_conf 0.9, empirical 0.5
        _forecast(0.1, False),
        _forecast(0.1, False),  # bin 1: mean_conf 0.1, empirical 0.0
    ]
    curve = calibration_curve(forecasts, bins=10)
    by_bin = {b.bin_index: b for b in curve}
    assert set(by_bin) == {1, 9}
    assert by_bin[9] == CalibrationBin(9, pytest.approx(0.9), pytest.approx(0.5), 2)
    assert by_bin[1] == CalibrationBin(1, pytest.approx(0.1), pytest.approx(0.0), 2)


def test_calibration_curve_p_one_lands_in_top_bin() -> None:
    curve = calibration_curve([_forecast(1.0, True)], bins=10)
    assert [b.bin_index for b in curve] == [9]


def test_calibration_curve_empty_is_empty() -> None:
    assert calibration_curve([]) == []


# --- calibration_error (ECE) --------------------------------------------------


def test_calibration_error_population_weighted_gap() -> None:
    forecasts = [
        _forecast(0.9, True),
        _forecast(0.9, False),  # gap 0.4, n 2
        _forecast(0.1, False),
        _forecast(0.1, False),  # gap 0.1, n 2
    ]
    # (2/4)*0.4 + (2/4)*0.1 = 0.25
    assert calibration_error(forecasts, bins=10) == pytest.approx(0.25)


def test_calibration_error_empty_is_none() -> None:
    assert calibration_error([]) is None


# --- discrimination (AUC) -----------------------------------------------------


def test_discrimination_perfect_separation_is_one() -> None:
    forecasts = [
        _forecast(0.9, True),
        _forecast(0.8, True),
        _forecast(0.2, False),
        _forecast(0.1, False),
    ]
    assert discrimination(forecasts) == pytest.approx(1.0)


def test_discrimination_inverted_is_zero() -> None:
    forecasts = [_forecast(0.1, True), _forecast(0.9, False)]
    assert discrimination(forecasts) == pytest.approx(0.0)


def test_discrimination_ties_count_half() -> None:
    forecasts = [_forecast(0.5, True), _forecast(0.5, False)]
    assert discrimination(forecasts) == pytest.approx(0.5)


def test_discrimination_all_same_outcome_is_undefined() -> None:
    assert discrimination([_forecast(0.9, True), _forecast(0.8, True)]) is None
    assert discrimination([_forecast(0.2, False)]) is None


def test_calibration_and_discrimination_are_independent_axes() -> None:
    # A judge that is sharply DISCRIMINATING (perfect ordering) but badly
    # MISCALIBRATED (numbers far from the diagonal): all goods forecast 0.55,
    # all bads 0.45. AUC is 1.0; calibration error is large.
    forecasts = [
        _forecast(0.55, True),
        _forecast(0.55, True),
        _forecast(0.45, False),
        _forecast(0.45, False),
    ]
    assert discrimination(forecasts) == pytest.approx(1.0)
    assert calibration_error(forecasts) > 0.4


# --- score_judge --------------------------------------------------------------


def test_score_judge_zero_resolved_is_all_none_low_confidence() -> None:
    score = score_judge("post_verify", "review_advisor", [])
    assert score.n_resolved == 0
    assert score.brier is None
    assert score.log_score is None
    assert score.calibration_error is None
    assert score.discrimination is None
    assert score.calibration_bins == ()
    assert score.low_confidence is True
    assert score.discrimination_undefined is True


def test_score_judge_populated_reports_both_axes() -> None:
    forecasts = [
        _forecast(0.9, True),
        _forecast(0.8, True),
        _forecast(0.2, False),
        _forecast(0.1, False),
    ]
    score = score_judge("post_verify", "review_advisor", forecasts)
    assert score.n_resolved == 4
    assert score.brier is not None
    assert score.discrimination == pytest.approx(1.0)
    assert score.discrimination_undefined is False
    # 4 < MIN_CONFIDENT_RESOLVED → thin sample flagged.
    assert score.low_confidence is True


def test_score_judge_low_confidence_clears_past_threshold() -> None:
    forecasts = [_forecast(0.9, True)] * MIN_CONFIDENT_RESOLVED
    score = score_judge("j", "fam", forecasts)
    assert score.n_resolved == MIN_CONFIDENT_RESOLVED
    assert score.low_confidence is False
    # all-good outcomes → discrimination undefined even at full n.
    assert score.discrimination_undefined is True


# --- score_all ----------------------------------------------------------------


def test_score_all_enumerates_each_judge_including_unresolved() -> None:
    verdicts = [
        _verdict("pr:1", Verdict.PASS, 0.9, judge="post_verify:correctness"),
        _verdict("pr:2", Verdict.FAIL, 0.8, judge="post_verify:security"),
    ]
    # Only pr:1 has an outcome; the security judge (pr:2) has zero resolved.
    outcomes = [Outcome("pr:1", good=True)]
    scores = {s.judge_id: s for s in score_all(verdicts, outcomes)}
    assert set(scores) == {"post_verify:correctness", "post_verify:security"}
    assert scores["post_verify:correctness"].n_resolved == 1
    assert scores["post_verify:security"].n_resolved == 0
    assert scores["post_verify:security"].brier is None


def test_score_all_stable_sorted_by_judge_id() -> None:
    verdicts = [
        _verdict("pr:2", Verdict.PASS, 0.9, judge="zeta"),
        _verdict("pr:1", Verdict.PASS, 0.9, judge="alpha"),
    ]
    scores = score_all(verdicts, [])
    assert [s.judge_id for s in scores] == ["alpha", "zeta"]


# --- outcome resolution (grace window) ----------------------------------------


def test_escaped_subjects_keys_by_pr_and_skips_none() -> None:
    class _Esc:
        def __init__(self, pr: int | None) -> None:
            self.originating_pr = pr

    subjects = escaped_subjects([_Esc(1), _Esc(None), _Esc(2)])
    assert subjects == {"pr:1", "pr:2"}


def test_resolve_outcomes_attributed_escape_is_bad_immediately() -> None:
    # Recorded 1h ago (well inside the grace window) but has an escape → bad now.
    verdicts = [_verdict("pr:1", Verdict.PASS, 0.9, at=_NOW - timedelta(hours=1))]
    outcomes = resolve_outcomes(verdicts, {"pr:1"}, now=_NOW)
    assert outcomes == [Outcome("pr:1", good=False)]


def test_resolve_outcomes_escape_free_past_grace_is_good() -> None:
    verdicts = [_verdict("pr:2", Verdict.PASS, 0.9, at=_NOW - timedelta(days=10))]
    outcomes = resolve_outcomes(verdicts, set(), now=_NOW)
    assert outcomes == [Outcome("pr:2", good=True)]


def test_resolve_outcomes_too_recent_escape_free_is_unresolved() -> None:
    verdicts = [_verdict("pr:3", Verdict.PASS, 0.9, at=_NOW - timedelta(days=1))]
    assert resolve_outcomes(verdicts, set(), now=_NOW) == []


def test_resolve_outcomes_dedupes_subject_using_latest_verdict() -> None:
    # Two verdicts on pr:4: an old one (past grace) and a fresh one (inside it).
    # The LATEST (conservative) reference wins → still unresolved.
    verdicts = [
        _verdict("pr:4", Verdict.PASS, 0.9, at=_NOW - timedelta(days=10)),
        _verdict("pr:4", Verdict.PASS, 0.9, at=_NOW - timedelta(hours=2)),
    ]
    assert resolve_outcomes(verdicts, set(), now=_NOW) == []


def test_escape_ledger_outcome_resolver_end_to_end() -> None:
    class _Esc:
        def __init__(self, pr: int | None) -> None:
            self.originating_pr = pr

    verdicts = [
        _verdict("pr:1", Verdict.PASS, 0.9, at=_NOW - timedelta(hours=1)),  # escaped
        _verdict("pr:2", Verdict.PASS, 0.9, at=_NOW - timedelta(days=10)),  # good
        _verdict("pr:3", Verdict.PASS, 0.9, at=_NOW - timedelta(days=1)),  # pending
    ]
    resolver = EscapeLedgerOutcomeResolver([_Esc(1)], now=_NOW)
    outcomes = {o.subject_id: o.good for o in resolver.resolve(verdicts)}
    assert outcomes == {"pr:1": False, "pr:2": True}


def test_default_grace_window_is_seven_days() -> None:
    assert DEFAULT_GRACE_WINDOW.days == 7
    assert DEFAULT_GRACE_WINDOW.total_seconds() == 7 * 24 * 3600


# --- ledger round-trip --------------------------------------------------------


def test_ledger_round_trip_preserves_record(tmp_path: Path) -> None:
    ledger = JudgeCalibrationLedger(judge_verdict_ledger_path(tmp_path))
    record = _verdict("pr:7", Verdict.FAIL, 0.73, judge="post_verify:security")
    ledger.record(record)

    read_back = JudgeCalibrationLedger(judge_verdict_ledger_path(tmp_path)).read_all()
    assert len(read_back) == 1
    got = read_back[0]
    assert got.judge_id == "post_verify:security"
    assert got.judge_family == "review_advisor"
    assert got.subject_id == "pr:7"
    assert got.verdict is Verdict.FAIL
    assert got.confidence == pytest.approx(0.73)
    assert got.recorded_at == _NOW


def test_ledger_missing_file_reads_empty(tmp_path: Path) -> None:
    assert JudgeCalibrationLedger(judge_verdict_ledger_path(tmp_path)).read_all() == []


def test_ledger_path_under_calibration_subdir(tmp_path: Path) -> None:
    path = judge_verdict_ledger_path(tmp_path)
    assert path == tmp_path / "calibration" / "judge_verdicts.jsonl"


# --- fail-soft recorder -------------------------------------------------------


def test_record_verdict_happy_path_writes_joinable_record(tmp_path: Path) -> None:
    path = judge_verdict_ledger_path(tmp_path)
    ok = record_verdict(
        path,
        judge_id="post_verify",
        judge_family="review_advisor",
        subject_id=subject_for_pr(42),
        verdict=Verdict.PASS,
        confidence=0.85,
        recorded_at=_NOW,
    )
    assert ok is True
    records = JudgeCalibrationLedger(path).read_all()
    assert len(records) == 1
    assert records[0].subject_id == "pr:42"


def test_record_verdict_is_fail_soft_on_write_error(tmp_path: Path) -> None:
    # A write failure must be swallowed (returns False), never propagated: the
    # recorder observes the review pipeline and can never break it.
    path = judge_verdict_ledger_path(tmp_path)
    with patch.object(
        JudgeCalibrationLedger, "record", side_effect=OSError("disk full")
    ):
        ok = record_verdict(
            path,
            judge_id="post_verify",
            judge_family="review_advisor",
            subject_id="pr:1",
            verdict=Verdict.PASS,
            confidence=0.9,
            recorded_at=_NOW,
        )
    assert ok is False
