"""Failure-class split for failed implement runs (#11593 seam 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from implement_failure_class import FAILURE_CLASSES, classify_implement_failure
from state import StateTracker


class TestClassifyImplementFailure:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            ("test-adequacy failed: missing tests", "test_adequacy"),
            (
                "test-adequacy failed: Independent verifier overrode OK: gaps",
                "test_adequacy",
            ),
            ("diff-sanity failed: debug code left in", "diff_sanity"),
            ("scope-check failed: touched unplanned files", "scope"),
            ("No commits found on branch", "zero_commit"),
            ("RuntimeError('Agent process timed out after 3600s')", "timeout"),
            ("make quality failed:\nFAILED tests/test_x.py", "quality"),
            ("`make quality-lite` failed:\nE501 line too long", "quality"),
            ("Pre-quality review loop exhausted: issues remain", "quality"),
            ("something entirely novel", "other"),
            (None, "other"),
            ("", "other"),
        ],
    )
    def test_maps_manifest_error_strings_to_classes(self, error, expected) -> None:
        assert classify_implement_failure(error) == expected

    def test_quality_gate_timeout_counts_as_quality_not_timeout(self) -> None:
        """A gate-step timeout is a quality failure, not an agent timeout."""
        assert (
            classify_implement_failure("`make quality-lite` timed out after 600s")
            == "quality"
        )

    def test_every_result_is_a_registered_class(self) -> None:
        for error in ("test-adequacy failed: x", "weird", None):
            assert classify_implement_failure(error) in FAILURE_CLASSES


class TestImplementFailureCounter:
    def test_increment_persists_the_class_count(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.increment_implement_failure("test_adequacy")
        tracker.increment_implement_failure("test_adequacy")
        reloaded = StateTracker(state_file)
        counters = reloaded.get_session_counters()
        assert counters.implement_failures == {"test_adequacy": 2}

    def test_unknown_class_is_coerced_to_other(self, tmp_path: Path) -> None:
        tracker = StateTracker(tmp_path / "state.json")
        tracker.increment_implement_failure("not-a-class")
        assert tracker.get_session_counters().implement_failures == {"other": 1}

    def test_reset_session_counters_clears_the_split(self, tmp_path: Path) -> None:
        tracker = StateTracker(tmp_path / "state.json")
        tracker.increment_implement_failure("timeout")
        tracker.reset_session_counters("2026-08-21T00:00:00+00:00")
        assert tracker.get_session_counters().implement_failures == {}
