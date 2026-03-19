"""Tests for prompt_utils.py — shared text truncation and prompt-building utilities."""

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
    """Tests for truncate_text()."""

    def test_short_text_returned_unchanged(self) -> None:
        text = "hello\nworld"
        assert truncate_text(text, char_limit=1000, line_limit=500) == text

    def test_truncates_at_char_limit(self) -> None:
        text = "aaa\nbbb\nccc\nddd"
        result = truncate_text(text, char_limit=8, line_limit=500)
        assert "aaa" in result
        assert "bbb" in result
        assert "ccc" not in result

    def test_long_lines_capped_at_line_limit(self) -> None:
        text = "a" * 200
        result = truncate_text(text, char_limit=5000, line_limit=50)
        assert len(result.splitlines()[0]) <= 52  # 50 + "…"

    def test_appends_truncated_marker(self) -> None:
        text = "line1\nline2\nline3\nline4\nline5"
        result = truncate_text(text, char_limit=12, line_limit=500)
        assert "…(truncated)" in result

    def test_no_truncated_marker_when_no_truncation(self) -> None:
        text = "short"
        result = truncate_text(text, char_limit=1000, line_limit=500)
        assert "truncated" not in result


# ---------------------------------------------------------------------------
# summarize_for_prompt
# ---------------------------------------------------------------------------


class TestSummarizeForPrompt:
    """Tests for summarize_for_prompt()."""

    def test_short_text_returned_unchanged(self) -> None:
        text = "short text"
        assert summarize_for_prompt(text, max_chars=1000, label="test") == text

    def test_extracts_bullet_lines(self) -> None:
        lines = ["- bullet one", "- bullet two", "plain line", "- bullet three"]
        text = "\n".join(lines)
        result = summarize_for_prompt(text, max_chars=5, label="Bullets")
        assert "bullet one" in result
        assert "bullet two" in result
        assert "[Bullets summarized from" in result

    def test_extracts_heading_lines(self) -> None:
        text = "## Heading\nplain text\n## Another"
        result = summarize_for_prompt(text, max_chars=5, label="Heads")
        assert "Heading" in result
        assert "[Heads summarized from" in result

    def test_falls_back_to_first_lines_when_no_cues(self) -> None:
        text = "\n".join(f"plain line {i}" for i in range(20))
        result = summarize_for_prompt(text, max_chars=5, label="Plain")
        assert "plain line 0" in result
        assert "[Plain summarized from" in result

    def test_falls_back_to_raw_slice_when_empty_lines(self) -> None:
        text = "   \n  \n  "
        result = summarize_for_prompt(text, max_chars=2, label="Empty")
        # Should return raw slice since no non-empty lines
        assert len(result) > 0


# ---------------------------------------------------------------------------
# truncate_comment
# ---------------------------------------------------------------------------


class TestTruncateComment:
    """Tests for truncate_comment()."""

    def test_short_comment_returned_unchanged(self) -> None:
        assert truncate_comment("hello", 100) == "hello"

    def test_long_comment_truncated_with_marker(self) -> None:
        text = "a" * 200
        result = truncate_comment(text, 50)
        assert len(result.splitlines()[0]) == 50
        assert "[Comment truncated from 200 chars]" in result

    def test_none_input_returns_empty(self) -> None:
        assert truncate_comment(None, 100) == ""

    def test_whitespace_stripped(self) -> None:
        assert truncate_comment("  hello  ", 100) == "hello"


# ---------------------------------------------------------------------------
# build_comments_section
# ---------------------------------------------------------------------------


class TestBuildCommentsSection:
    """Tests for build_comments_section()."""

    def test_empty_comments_returns_empty_tuple(self) -> None:
        section, raw, fmt = build_comments_section([], lambda c: c)
        assert section == ""
        assert raw == ""
        assert fmt == ""

    def test_formats_comments_as_discussion(self) -> None:
        comments = ["Comment A", "Comment B"]
        section, raw, fmt = build_comments_section(comments, lambda c: c)
        assert "## Discussion" in section
        assert "- Comment A" in section
        assert "- Comment B" in section
        assert raw == "Comment AComment B"
        assert "Comment A" in fmt

    def test_limits_to_max_comments(self) -> None:
        comments = [f"Comment {i}" for i in range(10)]
        section, raw, fmt = build_comments_section(
            comments, lambda c: c, max_comments=3
        )
        assert "Comment 0" in section
        assert "Comment 2" in section
        assert "7 more comments omitted" in section

    def test_applies_truncate_fn(self) -> None:
        comments = ["long " * 100]
        section, raw, fmt = build_comments_section(comments, lambda c: c[:10] + "...")
        assert "long long ..." in section
