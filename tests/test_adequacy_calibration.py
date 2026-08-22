"""Unit tests for the test-adequacy gate calibration engine (#11593 seam 2).

Fast, pure, no I/O: exercises manifest parsing across BOTH manifest shapes
(legacy ``error``-string and the #11603 structured ``test_adequacy`` block),
the finding taxonomy (evidence grade, remit conformance), the Wilson interval
math on hand-computed expectations, demand stationarity, the reused
``judge_calibration`` accept-arm scoring, and — the load-bearing one — the
honest **under-determined** path when the reject arm has no resolvable outcome.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from adequacy_calibration import (
    JUDGE_FAMILY,
    JUDGE_ID,
    VERDICT_SOURCE_COVERAGE_DELTA,
    VERDICT_SOURCE_LLM_FAIL,
    VERDICT_SOURCE_VERIFIER_OVERRIDE,
    AdequacyRunRecord,
    EvidenceGrade,
    GateOutcome,
    IssueOutcome,
    RecordShape,
    SuspectReason,
    calibrate,
    demand_stationarity,
    finding_tokens,
    grade_finding,
    is_out_of_remit,
    parse_run_manifest,
    parse_run_timestamp,
    split_findings,
    suspect_rejections,
    to_judge_verdicts,
    wilson_interval,
)

_NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


# -- factories ------------------------------------------------------------------


def _rejection(
    issue_number: int = 9001,
    *,
    day: int = 1,
    hour: int = 0,
    verdict_source: str = VERDICT_SOURCE_LLM_FAIL,
    findings: tuple[str, ...] = ("untested error path in `_merge_base`",),
    duration_seconds: float = 1800.0,
    repair_passes_used: int = 0,
    shape: RecordShape = RecordShape.LEGACY,
) -> AdequacyRunRecord:
    """Build one gate rejection record."""
    return AdequacyRunRecord(
        issue_number=issue_number,
        recorded_at=datetime(2026, 8, day, hour, 0, 0, tzinfo=UTC),
        gate_outcome=GateOutcome.REJECTED,
        verdict_source=verdict_source,
        findings=findings,
        duration_seconds=duration_seconds,
        repair_passes_used=repair_passes_used,
        shape=shape,
    )


def _acceptance(
    issue_number: int = 9001, *, day: int = 2, duration_seconds: float = 3600.0
) -> AdequacyRunRecord:
    """Build one run that cleared the gate."""
    return AdequacyRunRecord(
        issue_number=issue_number,
        recorded_at=datetime(2026, 8, day, 0, 0, 0, tzinfo=UTC),
        gate_outcome=GateOutcome.ACCEPTED,
        duration_seconds=duration_seconds,
    )


def _legacy_manifest(
    issue_number: int = 9001,
    *,
    outcome: str = "failed",
    error: str | None = "test-adequacy failed: untested error path in `_load`",
    timestamp: str = "20260814T060442Z",
    duration_seconds: float = 1800.0,
) -> dict[str, object]:
    """Build a pre-#11603 manifest (no ``failure_class``/``test_adequacy``)."""
    return {
        "issue_number": issue_number,
        "timestamp": timestamp,
        "outcome": outcome,
        "error": error,
        "duration_seconds": duration_seconds,
        "files": ["manifest.json"],
    }


# -- timestamp parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20260814T060442Z", datetime(2026, 8, 14, 6, 4, 42, tzinfo=UTC)),
        ("2026-08-14T06:04:42+00:00", datetime(2026, 8, 14, 6, 4, 42, tzinfo=UTC)),
        ("2026-08-14T06:04:42Z", datetime(2026, 8, 14, 6, 4, 42, tzinfo=UTC)),
    ],
)
def test_parse_run_timestamp_accepts_both_manifest_formats(
    raw: str, expected: datetime
) -> None:
    assert parse_run_timestamp(raw) == expected


@pytest.mark.parametrize("raw", ["", "not-a-timestamp", "2026-13-99", None])
def test_parse_run_timestamp_returns_none_for_unparseable_input(raw: object) -> None:
    assert parse_run_timestamp(raw) is None


# -- manifest parsing: legacy shape ---------------------------------------------


def test_parse_run_manifest_classifies_legacy_adequacy_error_as_rejected() -> None:
    record = parse_run_manifest(_legacy_manifest())
    assert record is not None
    assert record.gate_outcome is GateOutcome.REJECTED


def test_parse_run_manifest_reads_verifier_override_from_the_legacy_prefix() -> None:
    manifest = _legacy_manifest(
        error="test-adequacy failed: Independent verifier overrode OK: untested wiring"
    )
    record = parse_run_manifest(manifest)
    assert record is not None
    assert record.verdict_source == VERDICT_SOURCE_VERIFIER_OVERRIDE


def test_parse_run_manifest_defaults_a_plain_legacy_rejection_to_llm_fail() -> None:
    record = parse_run_manifest(_legacy_manifest())
    assert record is not None
    assert record.verdict_source == VERDICT_SOURCE_LLM_FAIL


def test_parse_run_manifest_splits_the_legacy_summary_into_findings() -> None:
    manifest = _legacy_manifest(
        error="test-adequacy failed: untested boot path, untested error branch"
    )
    record = parse_run_manifest(manifest)
    assert record is not None
    assert record.findings == ("untested boot path", "untested error branch")


def test_parse_run_manifest_marks_a_legacy_manifest_with_the_legacy_shape() -> None:
    record = parse_run_manifest(_legacy_manifest())
    assert record is not None
    assert record.shape is RecordShape.LEGACY


@pytest.mark.parametrize(
    ("outcome", "error", "expected"),
    [
        ("success", None, GateOutcome.ACCEPTED),
        ("failed", "RuntimeError('Agent process timed out')", GateOutcome.NOT_REACHED),
        ("failed", "No commits found on branch", GateOutcome.NOT_REACHED),
        ("failed", "diff-sanity failed: doc-code-mismatch", GateOutcome.NOT_REACHED),
        ("stopped", None, GateOutcome.NOT_REACHED),
    ],
)
def test_parse_run_manifest_maps_non_adequacy_outcomes(
    outcome: str, error: str | None, expected: GateOutcome
) -> None:
    record = parse_run_manifest(_legacy_manifest(outcome=outcome, error=error))
    assert record is not None
    assert record.gate_outcome is expected


# -- manifest parsing: structured (#11603) shape --------------------------------


def _structured_manifest(**overrides: object) -> dict[str, object]:
    """Build a post-#11603 manifest carrying a ``test_adequacy`` block."""
    manifest: dict[str, object] = {
        "issue_number": 9002,
        "timestamp": "20260901T101010Z",
        "outcome": "failed",
        "error": "test-adequacy failed: uncovered lines in src/thing.py",
        "duration_seconds": 900.0,
        "failure_class": "test_adequacy",
        "test_adequacy": {
            "passed": False,
            "verdict_source": VERDICT_SOURCE_COVERAGE_DELTA,
            "findings": ["uncovered lines in src/thing.py"],
            "repair_passes_used": 1,
            "repair_outcomes": ["still-failing"],
        },
    }
    manifest.update(overrides)
    return manifest


def test_parse_run_manifest_prefers_the_structured_verdict_source() -> None:
    record = parse_run_manifest(_structured_manifest())
    assert record is not None
    assert record.verdict_source == VERDICT_SOURCE_COVERAGE_DELTA


def test_parse_run_manifest_reads_repair_passes_from_the_structured_block() -> None:
    record = parse_run_manifest(_structured_manifest())
    assert record is not None
    assert record.repair_passes_used == 1


def test_parse_run_manifest_marks_a_structured_manifest_with_the_structured_shape() -> (
    None
):
    record = parse_run_manifest(_structured_manifest())
    assert record is not None
    assert record.shape is RecordShape.STRUCTURED


def test_parse_run_manifest_uses_structured_findings_over_the_error_string() -> None:
    manifest = _structured_manifest(
        test_adequacy={
            "passed": False,
            "verdict_source": VERDICT_SOURCE_LLM_FAIL,
            "findings": ["gap one", "gap two"],
        }
    )
    record = parse_run_manifest(manifest)
    assert record is not None
    assert record.findings == ("gap one", "gap two")


# -- manifest parsing: malformed tolerance --------------------------------------


@pytest.mark.parametrize(
    "manifest",
    [
        pytest.param({}, id="empty"),
        pytest.param({"timestamp": "20260814T060442Z"}, id="no-issue-number"),
        pytest.param({"issue_number": 9001}, id="no-timestamp"),
        pytest.param(
            {"issue_number": "nope", "timestamp": "20260814T060442Z"}, id="bad-issue"
        ),
        pytest.param({"issue_number": 9001, "timestamp": "junk"}, id="bad-timestamp"),
        pytest.param(["not", "a", "mapping"], id="not-a-mapping"),
        pytest.param(None, id="none"),
    ],
)
def test_parse_run_manifest_returns_none_for_malformed_input(manifest: object) -> None:
    assert parse_run_manifest(manifest) is None


def test_parse_run_manifest_tolerates_a_non_dict_test_adequacy_block() -> None:
    record = parse_run_manifest(_structured_manifest(test_adequacy="corrupt"))
    assert record is not None
    assert record.shape is RecordShape.LEGACY


def test_parse_run_manifest_tolerates_non_string_findings() -> None:
    manifest = _structured_manifest(
        test_adequacy={"passed": False, "findings": ["ok", 7, None]}
    )
    record = parse_run_manifest(manifest)
    assert record is not None
    assert record.findings == ("ok",)


def test_parse_run_manifest_coerces_a_negative_duration_to_zero() -> None:
    record = parse_run_manifest(_legacy_manifest(duration_seconds=-5.0))
    assert record is not None
    assert record.duration_seconds == 0.0


# -- finding splitting ----------------------------------------------------------


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ("a, b", ("a", "b")),
        ("a; b", ("a", "b")),
        (
            "untested fields (skill/desc, prompt) in x",
            ("untested fields (skill/desc, prompt) in x",),
        ),
        ("`a, b` gap", ("`a, b` gap",)),
        ("", ()),
        ("  ,  ", ()),
    ],
)
def test_split_findings_splits_only_at_top_level_separators(
    summary: str, expected: tuple[str, ...]
) -> None:
    assert split_findings(summary) == expected


# -- evidence grading -----------------------------------------------------------


@pytest.mark.parametrize(
    "finding",
    [
        "three mutants survive the full escape suite",
        "comparison-inversion mutations both survive",
        "route registration is revert-safe against the whole suite",
        "untested production DI wiring (feature silently inert if reverted)",
        "base-branch precedence untested (demonstrated silent regression)",
    ],
)
def test_grade_finding_marks_survivability_evidence_as_demonstrated(
    finding: str,
) -> None:
    assert grade_finding(finding) is EvidenceGrade.DEMONSTRATED


@pytest.mark.parametrize(
    "finding",
    [
        "untested error path in `_merge_base`",
        "boundary at exactly MIN_WINDOW_CALLS on all three gates",
        "missing branch coverage in _tally_events",
        "untested memoization in EscapeLedgerLoop",
        "untested SIGNAL fallback in clear-review-marker.sh",
        "untested env-var branch (--dry-run)",
    ],
)
def test_grade_finding_marks_a_concrete_referent_as_a_named_gap(finding: str) -> None:
    assert grade_finding(finding) is EvidenceGrade.NAMED_GAP


@pytest.mark.parametrize(
    "finding",
    [
        "missing-error-path-coverage",
        "boundary-condition gap in truncation logic",
        "unpinned-serial-list-sync",
        "edge-case-coverage",
        "",
    ],
)
def test_grade_finding_marks_text_with_no_code_referent_as_unanchored(
    finding: str,
) -> None:
    assert grade_finding(finding) is EvidenceGrade.UNANCHORED


# -- remit conformance ----------------------------------------------------------


@pytest.mark.parametrize(
    "finding",
    ["dead new keyword parameter", "contract-mismatch", "unused import left behind"],
)
def test_is_out_of_remit_flags_a_non_test_defect_demand(finding: str) -> None:
    assert is_out_of_remit(finding) is True


@pytest.mark.parametrize(
    "finding",
    [
        "untested error path in `_merge_base`",
        "dead code path is untested",
        "contract-mismatch is unpinned by any test",
    ],
)
def test_is_out_of_remit_keeps_a_test_gap_demand_in_remit(finding: str) -> None:
    assert is_out_of_remit(finding) is False


# -- Wilson interval ------------------------------------------------------------


def test_wilson_interval_returns_none_for_an_empty_denominator() -> None:
    assert wilson_interval(0, 0) is None


def test_wilson_interval_reports_the_raw_point_estimate() -> None:
    interval = wilson_interval(3, 16)
    assert interval is not None
    assert interval.point == pytest.approx(0.1875)


def test_wilson_interval_brackets_the_point_estimate() -> None:
    interval = wilson_interval(3, 16)
    assert interval is not None
    assert interval.low < interval.point < interval.high


def test_wilson_interval_matches_the_hand_computed_bounds() -> None:
    interval = wilson_interval(2, 15)
    assert interval is not None
    assert (interval.low, interval.high) == (
        pytest.approx(0.037, abs=1e-3),
        pytest.approx(0.379, abs=1e-3),
    )


def test_wilson_interval_clamps_a_zero_count_lower_bound_to_zero() -> None:
    interval = wilson_interval(0, 10)
    assert interval is not None
    assert interval.low == 0.0


def test_wilson_interval_never_exceeds_one_at_a_saturated_count() -> None:
    interval = wilson_interval(10, 10)
    assert interval is not None
    assert interval.high <= 1.0


def test_wilson_interval_widens_as_the_sample_shrinks() -> None:
    narrow = wilson_interval(50, 100)
    wide = wilson_interval(5, 10)
    assert narrow is not None and wide is not None
    assert (wide.high - wide.low) > (narrow.high - narrow.low)


# -- demand stationarity --------------------------------------------------------


def test_finding_tokens_keeps_the_discriminating_words() -> None:
    assert finding_tokens("the error path in a `_merge_base`") == frozenset(
        {"error", "path", "merge", "base"}
    )


@pytest.mark.parametrize(
    "filler", ["the", "in", "a", "with", "untested", "missing", "coverage", "tests"]
)
def test_finding_tokens_drops_filler_and_gate_vocabulary(filler: str) -> None:
    assert filler not in finding_tokens(f"{filler} error path")


def test_demand_stationarity_counts_no_pairs_for_single_rejection_issues() -> None:
    result = demand_stationarity([_rejection(9001), _rejection(9002, day=3)])
    assert result.n_repeat_pairs == 0


def test_demand_stationarity_pairs_consecutive_rejections_of_one_issue() -> None:
    result = demand_stationarity(
        [
            _rejection(9001, day=1, findings=("untested error path",)),
            _rejection(9001, day=2, findings=("untested error path",)),
            _rejection(9001, day=3, findings=("untested error path",)),
        ]
    )
    assert result.n_repeat_pairs == 2


def test_demand_stationarity_scores_a_repeated_demand_as_fully_overlapping() -> None:
    result = demand_stationarity(
        [
            _rejection(9001, day=1, findings=("untested error path",)),
            _rejection(9001, day=2, findings=("untested error path",)),
        ]
    )
    assert result.mean_jaccard == pytest.approx(1.0)


def test_demand_stationarity_counts_a_moved_target_as_a_disjoint_pair() -> None:
    result = demand_stationarity(
        [
            _rejection(9001, day=1, findings=("untested error path",)),
            _rejection(9001, day=2, findings=("missing boundary assertion",)),
        ]
    )
    assert result.n_disjoint_pairs == 1


def test_demand_stationarity_reports_no_mean_without_any_pair() -> None:
    assert demand_stationarity([]).mean_jaccard is None


def test_demand_stationarity_bounds_the_disjoint_rate() -> None:
    result = demand_stationarity(
        [
            _rejection(9001, day=1, findings=("untested error path",)),
            _rejection(9001, day=2, findings=("boundary assertion absent",)),
        ]
    )
    assert result.disjoint_rate is not None
    assert result.disjoint_rate.point == pytest.approx(1.0)


def test_demand_stationarity_reports_no_disjoint_rate_without_any_pair() -> None:
    assert demand_stationarity([]).disjoint_rate is None


# -- suspect rejections ---------------------------------------------------------


def test_suspect_rejections_flags_an_entirely_unanchored_demand() -> None:
    suspects = suspect_rejections([_rejection(findings=("edge-case-coverage",))])
    assert suspects[0].reasons == (SuspectReason.ALL_FINDINGS_UNANCHORED,)


def test_suspect_rejections_flags_a_moved_target_on_a_repeat() -> None:
    suspects = suspect_rejections(
        [
            _rejection(9001, day=1, findings=("untested error path in `_load`",)),
            _rejection(9001, day=2, findings=("missing boundary case in `_save`",)),
        ]
    )
    assert SuspectReason.DEMAND_NOT_STATIONARY in suspects[0].reasons


def test_suspect_rejections_flags_a_self_declared_covered_change() -> None:
    suspects = suspect_rejections(
        [
            _rejection(
                findings=("untested wiring `_boot` — the fix itself is fully covered",)
            )
        ]
    )
    assert SuspectReason.SELF_DECLARED_CORE_COVERED in suspects[0].reasons


def test_suspect_rejections_flags_an_out_of_remit_demand() -> None:
    suspects = suspect_rejections(
        [
            _rejection(
                findings=("dead new keyword parameter", "untested `_merge_base` path")
            )
        ]
    )
    assert SuspectReason.REMIT_DRIFT in suspects[0].reasons


def test_suspect_rejections_leaves_a_well_evidenced_rejection_alone() -> None:
    assert (
        suspect_rejections(
            [_rejection(findings=("three mutants survive `_merge_base` coverage",))]
        )
        == ()
    )


def test_suspect_rejections_ignores_accepted_runs() -> None:
    assert suspect_rejections([_acceptance()]) == ()


# -- judge-verdict bridge (reuses judge_calibration) ----------------------------


def test_to_judge_verdicts_keys_an_acceptance_to_its_closing_pr() -> None:
    verdicts = to_judge_verdicts(
        [_acceptance(9001)], [IssueOutcome(9001, closing_prs=(1234,), escaped=False)]
    )
    assert [v.subject_id for v in verdicts] == ["pr:1234"]


def test_to_judge_verdicts_keys_a_rejection_to_its_unjoinable_issue_subject() -> None:
    verdicts = to_judge_verdicts(
        [_rejection(9001)], [IssueOutcome(9001, closing_prs=(1234,), escaped=False)]
    )
    assert [v.subject_id for v in verdicts] == ["issue:9001"]


def test_to_judge_verdicts_tags_every_row_with_the_gate_judge_identity() -> None:
    verdicts = to_judge_verdicts([_acceptance(9001)], [])
    assert (verdicts[0].judge_id, verdicts[0].judge_family) == (JUDGE_ID, JUDGE_FAMILY)


def test_to_judge_verdicts_skips_runs_that_never_reached_the_gate() -> None:
    record = AdequacyRunRecord(
        issue_number=9001,
        recorded_at=_NOW,
        gate_outcome=GateOutcome.NOT_REACHED,
    )
    assert to_judge_verdicts([record], []) == []


# -- calibrate: the report ------------------------------------------------------


def _corpus() -> list[AdequacyRunRecord]:
    """Small mixed corpus: 2 override + 2 plain rejections, 2 acceptances."""
    return [
        _rejection(9001, day=1, verdict_source=VERDICT_SOURCE_VERIFIER_OVERRIDE),
        _rejection(
            9002,
            day=2,
            verdict_source=VERDICT_SOURCE_VERIFIER_OVERRIDE,
            findings=("edge-case-coverage",),
        ),
        _rejection(9003, day=3),
        _rejection(9004, day=4),
        _acceptance(9001, day=5),
        _acceptance(9005, day=6),
    ]


def test_calibrate_counts_every_gate_decision_in_the_corpus() -> None:
    report = calibrate(_corpus(), [], now=_NOW)
    assert (report.n_rejected, report.n_accepted) == (4, 2)


def test_calibrate_splits_rejections_by_verdict_source() -> None:
    report = calibrate(_corpus(), [], now=_NOW)
    counts = {s.verdict_source: s.n_rejections for s in report.by_verdict_source}
    assert counts == {VERDICT_SOURCE_VERIFIER_OVERRIDE: 2, VERDICT_SOURCE_LLM_FAIL: 2}


def test_calibrate_scores_recovery_from_a_later_acceptance_of_the_same_issue() -> None:
    report = calibrate(_corpus(), [], now=_NOW)
    override = next(
        s
        for s in report.by_verdict_source
        if s.verdict_source == VERDICT_SOURCE_VERIFIER_OVERRIDE
    )
    assert override.recovery is not None
    assert override.recovery.point == pytest.approx(0.5)


def test_calibrate_reports_the_median_cost_of_a_rejection() -> None:
    report = calibrate(_corpus(), [], now=_NOW)
    assert report.median_rejection_minutes == pytest.approx(30.0)


def test_calibrate_reports_under_determined_when_no_rejection_resolves() -> None:
    report = calibrate(_corpus(), [], now=_NOW)
    assert report.identifiability.under_determined is True


def test_calibrate_names_the_censoring_reason_for_the_reject_arm() -> None:
    report = calibrate(_corpus(), [], now=_NOW)
    assert any("never merges" in reason for reason in report.identifiability.reasons)


def test_calibrate_never_resolves_a_rejection_outcome_even_with_full_outcomes() -> None:
    outcomes = [
        IssueOutcome(n, closing_prs=(n + 100,), escaped=False)
        for n in range(9001, 9006)
    ]
    report = calibrate(_corpus(), outcomes, now=_NOW)
    assert report.identifiability.n_rejections_resolved == 0


def test_calibrate_resolves_the_accept_arm_against_the_escape_ledger() -> None:
    outcomes = [
        IssueOutcome(9001, closing_prs=(1101,), escaped=False),
        IssueOutcome(9005, closing_prs=(1105,), escaped=True),
    ]
    report = calibrate(_corpus(), outcomes, now=_NOW)
    assert report.identifiability.n_acceptances_resolved == 2


def test_calibrate_scores_the_accept_arm_with_the_reused_judge_engine() -> None:
    outcomes = [
        IssueOutcome(9001, closing_prs=(1101,), escaped=False),
        IssueOutcome(9005, closing_prs=(1105,), escaped=True),
    ]
    report = calibrate(_corpus(), outcomes, now=_NOW)
    assert report.accept_arm_score.brier == pytest.approx(0.5)


def test_calibrate_flags_a_thin_accept_arm_as_low_confidence() -> None:
    outcomes = [IssueOutcome(9001, closing_prs=(1101,), escaped=False)]
    report = calibrate(_corpus(), outcomes, now=_NOW)
    assert report.accept_arm_score.low_confidence is True


def test_calibrate_reports_the_post_rework_escape_rate_of_gated_issues() -> None:
    outcomes = [
        IssueOutcome(9001, closing_prs=(1101,), escaped=True),
        IssueOutcome(9002, closing_prs=(1102,), escaped=False),
    ]
    report = calibrate(_corpus(), outcomes, now=_NOW)
    override = next(
        s
        for s in report.by_verdict_source
        if s.verdict_source == VERDICT_SOURCE_VERIFIER_OVERRIDE
    )
    assert override.post_rework_escape is not None
    assert override.post_rework_escape.point == pytest.approx(0.5)


def test_calibrate_collects_the_suspect_rejections() -> None:
    report = calibrate(_corpus(), [], now=_NOW)
    assert [s.issue_number for s in report.suspect_rejections] == [9002]


def test_calibrate_summarises_the_evidence_mix_per_verdict_source() -> None:
    report = calibrate(_corpus(), [], now=_NOW)
    override = next(
        s
        for s in report.by_verdict_source
        if s.verdict_source == VERDICT_SOURCE_VERIFIER_OVERRIDE
    )
    assert override.evidence_mix[EvidenceGrade.UNANCHORED] == 1


def test_calibrate_reports_the_demonstrated_share_per_verdict_source() -> None:
    report = calibrate(_corpus(), [], now=_NOW)
    plain = next(
        s
        for s in report.by_verdict_source
        if s.verdict_source == VERDICT_SOURCE_LLM_FAIL
    )
    assert plain.demonstrated_share is not None
    assert plain.demonstrated_share.point == pytest.approx(0.0)


def test_calibrate_carries_the_demand_stationarity_measurement() -> None:
    records = [
        _rejection(9001, day=1, findings=("untested error path in `_load`",)),
        _rejection(9001, day=2, findings=("missing boundary case in `_save`",)),
    ]
    report = calibrate(records, [], now=_NOW)
    assert report.stationarity.n_disjoint_pairs == 1


def test_calibrate_counts_structured_manifests_separately() -> None:
    records = [*_corpus(), _rejection(9006, day=7, shape=RecordShape.STRUCTURED)]
    assert calibrate(records, [], now=_NOW).n_structured == 1


def test_calibrate_reports_the_corpus_window() -> None:
    report = calibrate(_corpus(), [], now=_NOW)
    assert (report.window_start, report.window_end) == (
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 8, 6, tzinfo=UTC),
    )


# -- calibrate: degenerate inputs -----------------------------------------------


def test_calibrate_returns_an_empty_report_for_an_empty_corpus() -> None:
    report = calibrate([], [], now=_NOW)
    assert (report.n_rejected, report.n_accepted, report.by_verdict_source) == (
        0,
        0,
        (),
    )


def test_calibrate_marks_an_empty_corpus_under_determined() -> None:
    assert calibrate([], [], now=_NOW).identifiability.under_determined is True


def test_calibrate_reports_no_window_for_an_empty_corpus() -> None:
    assert calibrate([], [], now=_NOW).window_start is None


def test_calibrate_reports_no_median_cost_without_rejections() -> None:
    assert calibrate([_acceptance()], [], now=_NOW).median_rejection_minutes is None


def test_calibrate_omits_an_unresolvable_outcome_from_the_accept_arm() -> None:
    outcomes = [IssueOutcome(9001, closing_prs=(), escaped=None)]
    report = calibrate(_corpus(), outcomes, now=_NOW)
    assert report.identifiability.n_acceptances_resolved == 0


def test_calibrate_report_round_trips_to_json() -> None:
    report = calibrate(_corpus(), [], now=_NOW)
    assert report.to_json_dict()["identifiability"]["under_determined"] is True
