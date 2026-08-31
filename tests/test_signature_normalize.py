"""Shared log/error signature normalization.

`normalize_signature` was private to `log_ingest_loop`; the retrospective's
signal extraction needs the same clustering. Extracted rather than copied — a
second copy drifts, and two normalizers would cluster the same error two ways.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import log_ingest_loop  # noqa: E402
from signature_normalize import normalize_signature  # noqa: E402


class TestOneIdentityNotTwoCopies:
    def test_log_ingest_loop_reuses_the_shared_function(self):
        assert log_ingest_loop.normalize_signature is normalize_signature


class TestNormalization:
    def test_issue_numbers_collapse(self):
        assert normalize_signature("failed on #1234") == normalize_signature(
            "failed on #99"
        )

    def test_paths_collapse(self):
        assert normalize_signature("error in src/foo/bar.py") == normalize_signature(
            "error in src/other/baz.py"
        )

    def test_quoted_strings_collapse(self):
        assert normalize_signature('cannot open "a.txt"') == normalize_signature(
            'cannot open "b.txt"'
        )

    def test_different_errors_stay_distinct(self):
        assert normalize_signature("connection refused") != normalize_signature(
            "permission denied"
        )

    def test_whitespace_is_flattened(self):
        assert normalize_signature("a   b\n c") == "a b c"
