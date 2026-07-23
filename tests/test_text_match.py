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

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from text_match import keyword_matches


class TestKeywordMatchesWordBoundaries:
    def test_matches_standalone_word(self) -> None:
        assert keyword_matches("test", "test") is True

    def test_matches_word_surrounded_by_spaces(self) -> None:
        assert keyword_matches("type", "type error") is True

    def test_matches_word_with_trailing_punctuation(self) -> None:
        # non-word char after the keyword is a boundary
        assert keyword_matches("type", "wrong type.") is True

    def test_does_not_match_trailing_plural(self) -> None:
        # full trailing \b means "test" does NOT match "tests"
        assert keyword_matches("test", "3 tests failed") is False

    def test_does_not_match_inside_larger_word_suffix(self) -> None:
        assert keyword_matches("test", "latest build") is False

    def test_does_not_match_inside_identifier(self) -> None:
        assert keyword_matches("type", "typeerror") is False
        assert keyword_matches("type", "prototype") is False
        assert keyword_matches("type", "typescript") is False

    def test_does_not_match_substring_of_longer_word(self) -> None:
        assert keyword_matches("format", "information") is False


class TestKeywordMatchesNonWordChars:
    def test_matches_phrase_with_literal_slash(self) -> None:
        # non-word characters inside the keyword are matched literally
        assert keyword_matches("try/except", "use a try/except block") is True

    def test_trailing_boundary_applies_to_last_word_char_of_phrase(self) -> None:
        # "try/except" must not match inside "try/exception"
        assert keyword_matches("try/except", "try/exception raised") is False

    def test_matches_multi_word_phrase(self) -> None:
        assert keyword_matches("merge conflict", "a merge conflict here") is True


class TestKeywordMatchesCaseSensitivity:
    """The matcher itself is case-sensitive; callers pre-lowercase both args."""

    def test_is_case_sensitive_uppercase_text_does_not_match_lower_keyword(
        self,
    ) -> None:
        assert keyword_matches("test", "TEST failed") is False

    def test_lowercased_inputs_match(self) -> None:
        assert keyword_matches("test".lower(), "TEST failed".lower()) is True
