"""Tests for traceability.py — requirement-ID threading helpers (CH-5).

NOTE: requirement IDs used here live only in string literals, never in
docstrings — the traceability-matrix generator treats *docstring* Req-ID
references in tests/ as test evidence, and synthetic IDs must not leak
into the generated matrix.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from traceability import (
    REQ_LABEL_PREFIX,
    append_req_trailer,
    extract_req_id,
    is_regulated,
    missing_required_req_id,
    normalize_req_id,
    req_trailer,
)

# ---------------------------------------------------------------------------
# normalize_req_id
# ---------------------------------------------------------------------------


class TestNormalizeReqId:
    def test_valid_id_passes_through(self) -> None:
        assert normalize_req_id("REQ-042") == "REQ-042"

    def test_surrounding_whitespace_stripped(self) -> None:
        assert normalize_req_id("  SYS-9 ") == "SYS-9"

    def test_dotted_and_slashed_ids_accepted(self) -> None:
        assert normalize_req_id("FDA/820.30-a") == "FDA/820.30-a"

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "REQ 42",
            "-REQ42",
            "R" * 65,
        ],
        ids=[
            "empty_rejected",
            "whitespace_only_rejected",
            "embedded_space_rejected",
            "leading_punctuation_rejected",
            "overlong_id_rejected",
        ],
    )
    def test_malformed_id_rejected(self, value: str) -> None:
        assert normalize_req_id(value) is None

    def test_max_length_id_accepted(self) -> None:
        assert normalize_req_id("R" * 64) == "R" * 64


# ---------------------------------------------------------------------------
# extract_req_id
# ---------------------------------------------------------------------------


class TestExtractReqId:
    def test_from_req_label(self) -> None:
        assert extract_req_id(labels=["bug", "req:REQ-042"]) == "REQ-042"

    def test_label_prefix_is_case_insensitive(self) -> None:
        assert extract_req_id(labels=["Req:SYS-1"]) == "SYS-1"

    def test_from_body_field(self) -> None:
        body = "Some intro.\n\nReq-ID: SYS-9\n\nMore prose."
        assert extract_req_id(labels=[], body=body) == "SYS-9"

    def test_body_field_key_is_case_insensitive(self) -> None:
        assert extract_req_id(labels=[], body="req-id: ABC-1") == "ABC-1"

    def test_label_wins_over_body(self) -> None:
        body = "Req-ID: FROM-BODY"
        assert extract_req_id(labels=["req:FROM-LABEL"], body=body) == "FROM-LABEL"

    def test_invalid_label_value_falls_back_to_body(self) -> None:
        assert extract_req_id(labels=["req:"], body="Req-ID: SYS-2") == "SYS-2"

    def test_no_sources_returns_none(self) -> None:
        assert extract_req_id(labels=["bug"], body="plain prose") is None

    def test_empty_inputs_return_none(self) -> None:
        assert extract_req_id(labels=[], body="") is None

    def test_body_field_must_start_its_line(self) -> None:
        assert extract_req_id(labels=[], body="see the Req-ID: SYS-3 field") is None

    def test_prefix_constant_is_req_colon(self) -> None:
        assert REQ_LABEL_PREFIX == "req:"


# ---------------------------------------------------------------------------
# req_trailer / append_req_trailer
# ---------------------------------------------------------------------------


class TestReqTrailer:
    def test_trailer_format(self) -> None:
        assert req_trailer("REQ-042") == "Req-ID: REQ-042"

    def test_append_adds_trailer_after_blank_line(self) -> None:
        out = append_req_trailer("feat: do thing", "REQ-042")
        assert out == "feat: do thing\n\nReq-ID: REQ-042"

    def test_append_none_req_id_is_noop(self) -> None:
        assert append_req_trailer("feat: do thing", None) == "feat: do thing"

    def test_append_is_idempotent(self) -> None:
        once = append_req_trailer("body text", "REQ-042")
        assert append_req_trailer(once, "REQ-042") == once

    def test_append_strips_trailing_newlines_before_trailer(self) -> None:
        out = append_req_trailer("body text\n\n", "SYS-9")
        assert out == "body text\n\nReq-ID: SYS-9"

    def test_append_to_empty_text_is_just_trailer(self) -> None:
        assert append_req_trailer("", "SYS-9") == "Req-ID: SYS-9"


# ---------------------------------------------------------------------------
# is_regulated / missing_required_req_id
# ---------------------------------------------------------------------------


class TestRegulatedClass:
    def test_empty_regulated_set_matches_nothing(self) -> None:
        assert is_regulated(["safety-critical"], []) is False

    def test_matching_label_is_regulated(self) -> None:
        assert is_regulated(["bug", "safety-critical"], ["safety-critical"]) is True

    def test_match_is_case_insensitive(self) -> None:
        assert is_regulated(["Safety-Critical"], ["safety-critical"]) is True

    def test_non_matching_label_is_not_regulated(self) -> None:
        assert is_regulated(["bug"], ["safety-critical"]) is False

    def test_missing_required_when_regulated_and_no_id(self) -> None:
        assert (
            missing_required_req_id(
                labels=["safety-critical"],
                body="",
                regulated_labels=["safety-critical"],
            )
            is True
        )

    def test_not_missing_when_regulated_and_label_id(self) -> None:
        assert (
            missing_required_req_id(
                labels=["safety-critical", "req:REQ-1"],
                body="",
                regulated_labels=["safety-critical"],
            )
            is False
        )

    def test_not_missing_when_regulated_and_body_id(self) -> None:
        assert (
            missing_required_req_id(
                labels=["safety-critical"],
                body="Req-ID: REQ-1",
                regulated_labels=["safety-critical"],
            )
            is False
        )

    def test_not_missing_when_unregulated(self) -> None:
        assert (
            missing_required_req_id(
                labels=["bug"], body="", regulated_labels=["safety-critical"]
            )
            is False
        )
