"""Tests for prompt_utils.py — shared prompt-building utilities."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from prompt_utils import (
    build_comments_section,
    summarize_for_prompt,
    truncate_comment,
    truncate_text,
)

# ---------------------------------------------------------------------------
# truncate_text
# ---------------------------------------------------------------------------


class TestTruncateText:
    """Tests for the truncate_text utility."""

    def test_short_text_unchanged(self) -> None:
        text = "hello world"
        assert truncate_text(text, 100, 500) == text

    def test_truncates_at_char_limit(self) -> None:
        text = "line1\nline2\nline3\nline4"
        result = truncate_text(text, 12, 500)
        assert "line1" in result
        assert "\u2026(truncated)" in result

    def test_truncates_long_lines(self) -> None:
        text = "a" * 20
        result = truncate_text(text, 100, 5)
        assert result.startswith("aaaaa\u2026")

    def test_empty_text(self) -> None:
        assert truncate_text("", 100, 500) == ""

    def test_single_line_within_limit(self) -> None:
        text = "short line"
        assert truncate_text(text, 100, 500) == text

    def test_multiline_within_limit(self) -> None:
        # Each line is 5 chars + 1 newline = 6 chars per line
        text = "aaaaa\nbbbbb"
        result = truncate_text(text, 12, 500)
        # 12 chars allows "aaaaa" (5) + newline (1) + "bbbbb" (5) + newline (1) = 12
        assert "aaaaa" in result
        assert "bbbbb" in result

    def test_multiline_at_boundary_truncates(self) -> None:
        text = "aaaaa\nbbbbb"
        result = truncate_text(text, 11, 500)
        assert "aaaaa" in result
        # 11 chars: "aaaaa" (5) + newline (1) = 6; next line "bbbbb" (5+1=6) → 12 > 11
        assert "bbbbb" not in result
        assert "\u2026(truncated)" in result


# ---------------------------------------------------------------------------
# summarize_for_prompt
# ---------------------------------------------------------------------------


class TestSummarizeForPrompt:
    """Tests for the summarize_for_prompt utility."""

    def test_short_text_unchanged(self) -> None:
        text = "short text"
        assert summarize_for_prompt(text, 100, "label") == text

    def test_long_text_summarized(self) -> None:
        text = "\n".join(f"- item {i}" for i in range(50))
        result = summarize_for_prompt(text, 50, "Test")
        assert "[Test summarized from" in result

    def test_cue_lines_preferred(self) -> None:
        text = "paragraph text\n- bullet one\n- bullet two\n## Header\nmore text\n" * 5
        result = summarize_for_prompt(text, 50, "label")
        # Should pick bullet/heading lines
        assert "bullet" in result or "Header" in result

    def test_fallback_to_first_lines(self) -> None:
        text = "no bullets here\n" * 50
        result = summarize_for_prompt(text, 50, "label")
        assert "no bullets here" in result

    def test_empty_text(self) -> None:
        assert summarize_for_prompt("", 100, "label") == ""


# ---------------------------------------------------------------------------
# truncate_comment
# ---------------------------------------------------------------------------


class TestTruncateComment:
    """Tests for the truncate_comment utility."""

    def test_short_comment_unchanged(self) -> None:
        assert truncate_comment("hello", 100) == "hello"

    def test_long_comment_truncated(self) -> None:
        text = "a" * 200
        result = truncate_comment(text, 50)
        assert len(result.splitlines()[0]) == 50
        assert "Comment truncated from 200 chars" in result

    def test_none_input(self) -> None:
        assert truncate_comment(None, 100) == ""

    def test_empty_input(self) -> None:
        assert truncate_comment("", 100) == ""

    def test_whitespace_stripped(self) -> None:
        assert truncate_comment("  hello  ", 100) == "hello"


# ---------------------------------------------------------------------------
# build_comments_section
# ---------------------------------------------------------------------------


class TestBuildCommentsSection:
    """Tests for the build_comments_section utility."""

    def test_empty_comments(self) -> None:
        section, before, after = build_comments_section([], 6, 500)
        assert section == ""
        assert before == 0
        assert after == 0

    def test_builds_section_with_comments(self) -> None:
        comments = ["comment one", "comment two"]
        section, before, after = build_comments_section(comments, 6, 500)
        assert "## Discussion" in section
        assert "comment one" in section
        assert "comment two" in section
        assert before == len("comment one") + len("comment two")

    def test_limits_to_max_comments(self) -> None:
        comments = [f"comment {i}" for i in range(10)]
        section, _before, _after = build_comments_section(comments, 3, 500)
        assert "comment 0" in section
        assert "comment 2" in section
        assert "7 more comments omitted" in section

    def test_custom_truncate_fn(self) -> None:
        comments = ["hello world"]
        section, _before, _after = build_comments_section(
            comments, 6, 500, truncate_fn=lambda c: c.upper()
        )
        assert "HELLO WORLD" in section

    def test_chars_before_after_tracked(self) -> None:
        comments = ["a" * 100, "b" * 100]
        _section, before, after = build_comments_section(comments, 6, 50)
        assert before == 200
        # After truncation, should be smaller
        assert after <= before
