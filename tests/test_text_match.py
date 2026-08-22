"""Tests for text_match.py — the shared whole-word keyword matcher (#9659).

These pin the exact behavior the two insight classifiers
(``review_insights.extract_categories`` and
``harness_insights.extract_subcategories``) relied on before their duplicated
``_keyword_matches`` helpers were consolidated here. The extraction must be
behavior-preserving, so every case below reflects the original regex
(``\\b`` on both sides of the escaped keyword) exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from text_match import keyword_matches


class TestKeywordMatchesWordBoundaries:
    @pytest.mark.parametrize(
        ("keyword", "text", "expected"),
        [
            pytest.param("test", "test", True, id="matches_standalone_word"),
            pytest.param(
                "type", "type error", True, id="matches_word_surrounded_by_spaces"
            ),
            # A non-word char after the keyword is a boundary.
            pytest.param(
                "type", "wrong type.", True, id="matches_word_with_trailing_punctuation"
            ),
            # The full trailing \b means "test" does NOT match "tests".
            pytest.param(
                "test", "3 tests failed", False, id="does_not_match_trailing_plural"
            ),
            pytest.param(
                "test",
                "latest build",
                False,
                id="does_not_match_inside_larger_word_suffix",
            ),
            pytest.param(
                "format",
                "information",
                False,
                id="does_not_match_substring_of_longer_word",
            ),
        ],
    )
    def test_word_boundary(self, keyword: str, text: str, expected: bool) -> None:
        assert keyword_matches(keyword, text) is expected

    def test_does_not_match_inside_identifier(self) -> None:
        assert keyword_matches("type", "typeerror") is False
        assert keyword_matches("type", "prototype") is False
        assert keyword_matches("type", "typescript") is False


class TestKeywordMatchesNonWordChars:
    @pytest.mark.parametrize(
        ("keyword", "text", "expected"),
        [
            # Non-word characters inside the keyword are matched literally.
            pytest.param(
                "try/except",
                "use a try/except block",
                True,
                id="matches_phrase_with_literal_slash",
            ),
            # "try/except" must not match inside "try/exception".
            pytest.param(
                "try/except",
                "try/exception raised",
                False,
                id="trailing_boundary_applies_to_last_word_char_of_phrase",
            ),
            pytest.param(
                "merge conflict",
                "a merge conflict here",
                True,
                id="matches_multi_word_phrase",
            ),
        ],
    )
    def test_non_word_chars(self, keyword: str, text: str, expected: bool) -> None:
        assert keyword_matches(keyword, text) is expected


class TestKeywordMatchesCaseSensitivity:
    """The matcher itself is case-sensitive; callers pre-lowercase both args."""

    def test_is_case_sensitive_uppercase_text_does_not_match_lower_keyword(
        self,
    ) -> None:
        assert keyword_matches("test", "TEST failed") is False

    def test_lowercased_inputs_match(self) -> None:
        assert keyword_matches("test".lower(), "TEST failed".lower()) is True
