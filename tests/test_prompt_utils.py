"""Tests for prompt_utils — shared prompt text utilities."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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
    """Tests for the truncate_text function."""

    def test_short_text_unchanged(self) -> None:
        """Text within limits should be returned unchanged."""
        result = truncate_text("hello world", char_limit=100, line_limit=200)
        assert result == "hello world"

    def test_truncates_at_char_limit(self) -> None:
        """Text exceeding char_limit should be truncated with marker."""
        text = "line one\nline two\nline three\nline four"
        result = truncate_text(text, char_limit=20, line_limit=200)
        assert "\u2026(truncated)" in result
        assert "line one" in result

    def test_truncates_long_lines(self) -> None:
        """Lines exceeding line_limit should be hard-truncated with ellipsis."""
        text = "a" * 200
        result = truncate_text(text, char_limit=10000, line_limit=50)
        assert len(result.splitlines()[0]) == 51  # 50 chars + ellipsis char

    def test_empty_text(self) -> None:
        """Empty text should be returned unchanged."""
        result = truncate_text("", char_limit=100, line_limit=200)
        assert result == ""

    def test_multiline_respects_char_limit(self) -> None:
        """Should stop adding lines when char_limit would be exceeded."""
        lines = [f"line {i}" for i in range(100)]
        text = "\n".join(lines)
        result = truncate_text(text, char_limit=50, line_limit=200)
        assert "\u2026(truncated)" in result
        assert len(result) < len(text)


# ---------------------------------------------------------------------------
# summarize_for_prompt
# ---------------------------------------------------------------------------


class TestSummarizeForPrompt:
    """Tests for the summarize_for_prompt function."""

    def test_short_text_unchanged(self) -> None:
        """Text within max_chars should be returned unchanged."""
        result = summarize_for_prompt("short text", max_chars=100, label="Test")
        assert result == "short text"

    def test_long_text_summarized(self) -> None:
        """Text exceeding max_chars should be summarized with label."""
        text = "## Header\n" + "\n".join(f"- item {i}" for i in range(50))
        result = summarize_for_prompt(text, max_chars=50, label="Plan")
        assert "[Plan summarized from" in result
        assert "chars to reduce prompt size]" in result

    def test_prefers_cue_lines(self) -> None:
        """Summarization should prefer bullet/header lines."""
        text = "plain text\n- bullet one\n- bullet two\n" + "x" * 1000
        result = summarize_for_prompt(text, max_chars=50, label="Test")
        assert "bullet one" in result

    def test_fallback_to_first_lines(self) -> None:
        """When no cue lines, should use first non-empty lines."""
        text = "\n".join(f"paragraph {i}" for i in range(50))
        result = summarize_for_prompt(text, max_chars=50, label="Test")
        assert "paragraph 0" in result

    def test_fallback_to_raw_slice(self) -> None:
        """When no lines at all, should slice the raw text."""
        text = "x" * 1000  # single line, no cue markers
        result = summarize_for_prompt(text, max_chars=50, label="Test")
        assert "[Test summarized from" in result


# ---------------------------------------------------------------------------
# truncate_comment
# ---------------------------------------------------------------------------


class TestTruncateComment:
    """Tests for the truncate_comment function."""

    def test_short_comment_unchanged(self) -> None:
        """Comment within limit should be returned stripped."""
        result = truncate_comment("  hello  ", limit=100)
        assert result == "hello"

    def test_long_comment_truncated(self) -> None:
        """Comment exceeding limit should be truncated with marker."""
        text = "a" * 200
        result = truncate_comment(text, limit=50)
        assert "[Comment truncated from 200 chars]" in result
        assert len(result.split("\n")[0]) == 50

    def test_none_input(self) -> None:
        """None should be treated as empty string."""
        result = truncate_comment(None, limit=100)  # type: ignore[arg-type]
        assert result == ""

    def test_empty_input(self) -> None:
        """Empty string should be returned as-is."""
        result = truncate_comment("", limit=100)
        assert result == ""


# ---------------------------------------------------------------------------
# build_comments_section
# ---------------------------------------------------------------------------


class TestBuildCommentsSection:
    """Tests for the build_comments_section function."""

    def test_empty_comments(self) -> None:
        """Empty list should return empty strings."""
        section, raw, formatted = build_comments_section([])
        assert section == ""
        assert raw == ""
        assert formatted == ""

    def test_basic_comments(self) -> None:
        """Should format comments as bullet list in Discussion section."""
        comments = ["comment one", "comment two"]
        section, raw, formatted = build_comments_section(comments)
        assert "## Discussion" in section
        assert "- comment one" in section
        assert "- comment two" in section
        assert raw == "comment onecomment two"

    def test_max_comments_limit(self) -> None:
        """Should only include up to max_comments entries."""
        comments = [f"c{i}" for i in range(10)]
        section, _, _ = build_comments_section(comments, max_comments=3)
        assert "7 more comments omitted" in section
        assert "- c0" in section
        assert "- c2" in section
        assert "- c3" not in section

    def test_truncate_fn_applied(self) -> None:
        """Custom truncation function should be applied to each comment."""
        comments = ["long comment text"]
        section, _, _ = build_comments_section(comments, truncate_fn=lambda c: c[:4])
        assert "- long" in section
        assert "comment text" not in section

    def test_no_truncate_fn_strips(self) -> None:
        """Without truncate_fn, comments should be stripped."""
        comments = ["  spaced  "]
        section, _, _ = build_comments_section(comments)
        assert "- spaced" in section
