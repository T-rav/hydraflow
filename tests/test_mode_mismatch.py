"""Unit tests for the mode-mismatch ledger (#11055, five-modes rung 0)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from mode_mismatch import (
    MIN_DECISIVE_SAMPLE,
    IssueTrace,
    MismatchReport,
    Mode,
    classify,
    decision,
    render_report,
    summarize,
    verdict_row,
    write_ledger,
)


def _trace(issue_number: int = 1, **over: bool | int) -> IssueTrace:
    return replace(IssueTrace(issue_number=issue_number, work_started=True), **over)


class TestClassify:
    def test_clean_merge_is_build(self) -> None:
        verdict = classify(_trace(merged=True))
        assert verdict is not None
        assert verdict.needed is Mode.BUILD
        assert not verdict.wrong_dag

    def test_give_up_needed_probe(self) -> None:
        verdict = classify(_trace(gave_up=True))
        assert verdict is not None
        assert verdict.needed is Mode.PROBE
        assert verdict.wrong_dag

    def test_closed_unmerged_after_work_needed_oracle(self) -> None:
        verdict = classify(_trace(closed_unmerged=True))
        assert verdict is not None
        assert verdict.needed is Mode.ORACLE

    def test_late_decomposition_needed_decompose_earlier(self) -> None:
        verdict = classify(_trace(merged=True, decomposed_after_attempt=True))
        assert verdict is not None
        assert verdict.needed is Mode.DECOMPOSE_EARLIER

    def test_hitl_before_merge_needed_clarify(self) -> None:
        verdict = classify(_trace(merged=True, hitl_escalations=2))
        assert verdict is not None
        assert verdict.needed is Mode.CLARIFY

    def test_churny_merge_needed_collaborate(self) -> None:
        verdict = classify(_trace(merged=True, route_backs=3))
        assert verdict is not None
        assert verdict.needed is Mode.COLLABORATE

    def test_churn_threshold_is_configurable(self) -> None:
        verdict = classify(_trace(merged=True, route_backs=2), churn_threshold=2)
        assert verdict is not None
        assert verdict.needed is Mode.COLLABORATE

    def test_light_route_backs_stay_build(self) -> None:
        verdict = classify(_trace(merged=True, route_backs=2))
        assert verdict is not None
        assert verdict.needed is Mode.BUILD

    def test_rule_precedence_give_up_beats_everything(self) -> None:
        verdict = classify(
            _trace(
                gave_up=True,
                closed_unmerged=True,
                hitl_escalations=5,
                route_backs=9,
                decomposed_after_attempt=True,
            )
        )
        assert verdict is not None
        assert verdict.needed is Mode.PROBE

    def test_non_terminal_is_not_classified(self) -> None:
        assert classify(_trace()) is None  # open, in flight

    def test_never_worked_issue_is_triage_noise_not_mismatch(self) -> None:
        assert classify(_trace(closed_unmerged=True, work_started=False)) is None


class TestSummarizeAndDecision:
    def _verdicts(self, build: int, probe: int) -> list:
        traces = [_trace(issue_number=i, merged=True) for i in range(build)] + [
            _trace(issue_number=100 + i, gave_up=True) for i in range(probe)
        ]
        return [v for v in (classify(t) for t in traces) if v is not None]

    def test_summarize_counts_and_rate(self) -> None:
        report = summarize(self._verdicts(build=8, probe=2))
        assert report.total == 10
        assert report.wrong == 2
        assert report.rate == 0.2
        assert report.by_mode[Mode.BUILD] == 8
        assert report.by_mode[Mode.PROBE] == 2

    def test_empty_population_rate_is_zero_but_not_vindication(self) -> None:
        report = summarize([])
        assert report.rate == 0.0
        assert "INSUFFICIENT EVIDENCE" in decision(report)

    def test_small_sample_is_insufficient_regardless_of_rate(self) -> None:
        report = summarize(self._verdicts(build=1, probe=9))  # 90% wrong, n=10
        assert "INSUFFICIENT EVIDENCE" in decision(report)

    def test_low_rate_at_sample_vindicates_fixed_dag(self) -> None:
        report = summarize(self._verdicts(build=MIN_DECISIVE_SAMPLE, probe=1))
        assert "FIXED DAG VINDICATED" in decision(report)

    def test_high_rate_at_sample_proceeds_to_rung_1(self) -> None:
        report = summarize(self._verdicts(build=24, probe=6))  # 20%, n=30
        assert "PROCEED TO RUNG 1" in decision(report)

    def test_borderline_band_keeps_measuring(self) -> None:
        # 4/32 = 12.5% — between the 10% floor and 15% ceiling.
        report = summarize(self._verdicts(build=28, probe=4))
        assert "BORDERLINE" in decision(report)


class TestReportAndLedger:
    def test_render_carries_headline_decision_and_honesty(self) -> None:
        report = summarize(self._sample())
        out = render_report(report)
        assert "Wrong-DAG rate" in out
        assert "Decision:" in out
        assert "Honesty notes" in out
        assert "| build |" in out

    def test_ledger_rows_round_trip(self, tmp_path: Path) -> None:
        verdicts = self._sample()
        path = tmp_path / "mode_mismatch.jsonl"
        assert write_ledger(path, verdicts) == len(verdicts)
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert rows[0]["issue"] == verdicts[0].issue_number
        assert {"issue", "needed", "wrong_dag", "signals"} <= set(rows[0])

    def test_ledger_is_append_only(self, tmp_path: Path) -> None:
        path = tmp_path / "mode_mismatch.jsonl"
        write_ledger(path, self._sample())
        first = path.read_text()
        write_ledger(path, self._sample())
        assert path.read_text().startswith(first)  # prior rows untouched

    def _sample(self) -> list:
        traces = [
            _trace(issue_number=1, merged=True),
            _trace(issue_number=2, gave_up=True),
            _trace(issue_number=3, merged=True, hitl_escalations=1),
        ]
        return [v for v in (classify(t) for t in traces) if v is not None]


def test_report_dataclass_rate_guard() -> None:
    assert MismatchReport(total=0, wrong=0, by_mode={}).rate == 0.0


def test_verdict_row_carries_the_full_record() -> None:
    verdict = classify(_trace(merged=True, hitl_escalations=1))
    assert verdict is not None
    assert verdict_row(verdict) == {
        "issue": 1,
        "needed": "clarify",
        "wrong_dag": True,
        "signals": ["1 HITL escalation(s) before merge"],
    }
