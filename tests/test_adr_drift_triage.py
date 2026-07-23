"""Unit tests for the pure TRIAGE-step helpers (#9976).

``adr_drift_triage.py`` has no I/O and no side effects — every test here
is a plain function call against fixture strings.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adr_drift_triage import (
    RELABEL_CLASSIFICATIONS,
    DriftClassification,
    TriageVerdict,
    extract_decision_context,
    filter_diff_to_paths,
)


class TestDriftClassification:
    def test_five_values(self) -> None:
        assert {c.value for c in DriftClassification} == {
            "consistent",
            "real_drift",
            "over_citation",
            "dead_citation",
            "low_confidence",
        }

    def test_relabel_classifications_excludes_consistent_and_low_confidence(
        self,
    ) -> None:
        assert DriftClassification.CONSISTENT not in RELABEL_CLASSIFICATIONS
        assert DriftClassification.LOW_CONFIDENCE not in RELABEL_CLASSIFICATIONS
        assert {
            DriftClassification.REAL_DRIFT,
            DriftClassification.OVER_CITATION,
            DriftClassification.DEAD_CITATION,
        } == RELABEL_CLASSIFICATIONS


class TestTriageVerdict:
    def test_accepts_valid_classification(self) -> None:
        verdict = TriageVerdict(classification="consistent", rationale="fine")
        assert verdict.classification == DriftClassification.CONSISTENT
        assert verdict.section == ""

    def test_rejects_unknown_classification(self) -> None:
        with pytest.raises(ValidationError):
            TriageVerdict(classification="maybe", rationale="fine")

    def test_rejects_empty_rationale(self) -> None:
        with pytest.raises(ValidationError):
            TriageVerdict(classification="consistent", rationale="")

    def test_carries_section(self) -> None:
        verdict = TriageVerdict(
            classification="real_drift",
            rationale="the Decision text is now false",
            section="Decision",
        )
        assert verdict.section == "Decision"


class TestExtractDecisionContext:
    def test_extracts_context_and_decision(self) -> None:
        adr = (
            "# ADR-0099: Example\n\n"
            "**Status:** Accepted\n\n"
            "## Context\n\n"
            "Some background about why this decision was needed.\n\n"
            "## Decision\n\n"
            "We will do X.\n\n"
            "## Consequences\n\n"
            "Some fallout.\n"
        )
        extracted = extract_decision_context(adr)
        assert "## Context" in extracted
        assert "Some background about why this decision was needed." in extracted
        assert "## Decision" in extracted
        assert "We will do X." in extracted
        assert "Some fallout." not in extracted

    def test_falls_back_to_full_text_when_no_headings(self) -> None:
        adr = "Just some prose with no ## Context or ## Decision heading.\n"
        extracted = extract_decision_context(adr)
        assert extracted == adr

    def test_bounded_length(self) -> None:
        adr = "## Context\n\n" + ("x" * 20_000) + "\n\n## Decision\n\nshort\n"
        extracted = extract_decision_context(adr)
        assert len(extracted) <= 6_000


class TestFilterDiffToPaths:
    _DIFF = (
        "diff --git a/src/foo.py b/src/foo.py\n"
        "index 111..222 100644\n"
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old foo\n"
        "+new foo\n"
        "diff --git a/src/bar.py b/src/bar.py\n"
        "index 333..444 100644\n"
        "--- a/src/bar.py\n"
        "+++ b/src/bar.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old bar\n"
        "+new bar\n"
    )

    def test_keeps_only_matching_path(self) -> None:
        filtered = filter_diff_to_paths(self._DIFF, {"src/foo.py"})
        assert "new foo" in filtered
        assert "new bar" not in filtered

    def test_keeps_multiple_matching_paths(self) -> None:
        filtered = filter_diff_to_paths(self._DIFF, {"src/foo.py", "src/bar.py"})
        assert "new foo" in filtered
        assert "new bar" in filtered

    def test_falls_back_to_full_diff_when_no_match(self) -> None:
        filtered = filter_diff_to_paths(self._DIFF, {"src/nope.py"})
        assert filtered == self._DIFF

    def test_falls_back_when_no_paths_given(self) -> None:
        filtered = filter_diff_to_paths(self._DIFF, set())
        assert filtered == self._DIFF

    def test_falls_back_when_diff_has_no_headers(self) -> None:
        stub = "diff --git a/x b/x"
        filtered = filter_diff_to_paths(stub, {"src/foo.py"})
        assert filtered == stub

    def test_matches_rename_old_path(self) -> None:
        renamed = (
            "diff --git a/src/old_name.py b/src/new_name.py\n"
            "similarity index 100%\n"
            "rename from src/old_name.py\n"
            "rename to src/new_name.py\n"
        )
        filtered = filter_diff_to_paths(renamed, {"src/old_name.py"})
        assert "rename from" in filtered

    def test_bounded_length(self) -> None:
        huge = self._DIFF * 2000
        filtered = filter_diff_to_paths(huge, {"src/foo.py"})
        assert len(filtered) <= 8_000
