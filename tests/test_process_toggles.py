"""Tests for TriageResult parsing (issue_type normalisation)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from triage import TriageRunner

# ---------------------------------------------------------------------------
# TriageResult parsing tests
# ---------------------------------------------------------------------------


class TestTriageResultParsing:
    """Test _result_from_dict parses issue_type correctly."""

    @pytest.mark.parametrize(
        ("raw_issue_type", "expected"),
        [
            pytest.param("feature", "feature", id="test_parses_issue_type_feature"),
            pytest.param("bug", "bug", id="test_parses_issue_type_bug"),
            pytest.param("epic", "epic", id="test_parses_issue_type_epic"),
            # An unrecognised type normalises down to the "feature" default.
            pytest.param("task", "feature", id="test_normalises_unknown_to_feature"),
            # Normalisation is case-insensitive.
            pytest.param("BUG", "bug", id="test_normalises_case_insensitive"),
        ],
    )
    def test_parses_issue_type(self, raw_issue_type: str, expected: str) -> None:
        result = TriageRunner._result_from_dict(
            {"ready": True, "issue_type": raw_issue_type}, 1
        )
        assert result.issue_type == expected

    def test_defaults_to_feature_when_missing(self) -> None:
        result = TriageRunner._result_from_dict({"ready": True}, 1)
        assert result.issue_type == "feature"

    def test_normalises_none_to_feature(self) -> None:
        result = TriageRunner._result_from_dict({"ready": True, "issue_type": None}, 1)
        assert result.issue_type == "feature"
