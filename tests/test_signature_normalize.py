"""Shared log/error signature normalization.

`normalize_signature` was private to `log_ingest_loop`; the retrospective's
signal extraction needs the same clustering. Extracted rather than copied — a
second copy drifts, and two normalizers would cluster the same error two ways.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import log_ingest_loop  # noqa: E402
from signature_normalize import normalize_signature  # noqa: E402


class TestOneIdentityNotTwoCopies:
    def test_log_ingest_loop_reuses_the_shared_function(self):
        assert log_ingest_loop.normalize_signature is normalize_signature


class TestNormalization:
    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("failed on #1234", "failed on #99"),
            ("error in src/foo/bar.py", "error in src/other/baz.py"),
            ('cannot open "a.txt"', 'cannot open "b.txt"'),
        ],
        ids=["issue_numbers", "paths", "quoted_strings"],
    )
    def test_variable_parts_collapse_to_one_signature(self, left, right):
        assert normalize_signature(left) == normalize_signature(right)

    def test_different_errors_stay_distinct(self):
        assert normalize_signature("connection refused") != normalize_signature(
            "permission denied"
        )

    def test_whitespace_is_flattened(self):
        assert normalize_signature("a   b\n c") == "a b c"
