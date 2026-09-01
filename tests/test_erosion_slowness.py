"""Unit tests for the suite-time sensor (#11910).

Pure over an explicit ``{nodeid: seconds}`` mapping, the same contract
``erosion.mass.compute`` keeps — so the sensor is testable without running a
suite, a clock, or pytest.
"""

from __future__ import annotations

import json
from pathlib import Path

from erosion.slowness import DEFAULT_SLOW_TEST_SECONDS, collect_durations, compute


class TestCompute:
    def test_only_tests_at_or_above_the_threshold_are_named(self) -> None:
        finding = compute({"a": 12.0, "b": 3.0, "c": 10.0}, threshold_seconds=10.0)
        assert [t.nodeid for t in finding.slow_tests] == ["a", "c"]

    def test_the_roster_is_slowest_first(self) -> None:
        finding = compute({"a": 11.0, "b": 30.0, "c": 20.0}, threshold_seconds=10.0)
        assert [t.nodeid for t in finding.slow_tests] == ["b", "c", "a"]

    def test_ties_break_on_nodeid_so_the_roster_is_stable(self) -> None:
        """A roster that reorders between runs of the same measurement reads as
        churn in every diff that renders it."""
        finding = compute({"z": 10.0, "a": 10.0}, threshold_seconds=10.0)
        assert [t.nodeid for t in finding.slow_tests] == ["a", "z"]

    def test_totals_cover_every_test_not_only_the_slow_ones(self) -> None:
        finding = compute({"a": 12.0, "b": 3.0}, threshold_seconds=10.0)
        assert finding.total_tests == 2
        assert finding.total_seconds == 15.0
        assert finding.slow_seconds == 12.0

    def test_share_is_the_concentration_not_the_count(self) -> None:
        """The number that survives a contended host: every duration inflates
        together, so the RATIO is what still means something."""
        finding = compute({"a": 60.0, "b": 40.0}, threshold_seconds=50.0)
        assert finding.share == 0.6
        inflated = compute({"a": 120.0, "b": 80.0}, threshold_seconds=100.0)
        assert inflated.share == 0.6

    def test_an_empty_measurement_has_no_share_and_does_not_divide_by_zero(
        self,
    ) -> None:
        finding = compute({})
        assert finding.share == 0.0
        assert finding.is_empty
        assert finding.total_tests == 0

    def test_the_default_threshold_sits_under_the_conftest_gate(self) -> None:
        """The roster exists to show a test CLIMBING toward the 60s budget; a
        threshold at or above the gate could only ever re-report what already
        failed."""
        from tests.conftest import _SLOW_TEST_BUDGET_S

        assert DEFAULT_SLOW_TEST_SECONDS < _SLOW_TEST_BUDGET_S


class TestCollectDurations:
    def test_reads_the_artifact(self, tmp_path: Path) -> None:
        p = tmp_path / "d.json"
        p.write_text(json.dumps({"a::b": 1.5}), encoding="utf-8")
        assert collect_durations(p) == {"a::b": 1.5}

    def test_a_missing_artifact_is_no_measurement_not_a_fast_suite(
        self, tmp_path: Path
    ) -> None:
        """Distinguished by total_tests, because is_empty is true for both."""
        finding = compute(collect_durations(tmp_path / "absent.json"))
        assert finding.is_empty
        assert finding.total_tests == 0

    def test_a_corrupt_artifact_degrades_rather_than_raising(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "d.json"
        p.write_text("{not json", encoding="utf-8")
        assert collect_durations(p) == {}

    def test_non_numeric_entries_are_dropped_not_coerced(self, tmp_path: Path) -> None:
        p = tmp_path / "d.json"
        p.write_text(json.dumps({"ok": 2.0, "bad": "slow"}), encoding="utf-8")
        assert collect_durations(p) == {"ok": 2.0}
