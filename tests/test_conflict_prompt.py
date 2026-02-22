"""Tests for the shared conflict prompt builder."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conflict_prompt import build_conflict_prompt

ISSUE_URL = "https://github.com/test-org/test-repo/issues/42"
PR_URL = "https://github.com/test-org/test-repo/pull/101"


class TestBuildConflictPrompt:
    def test_includes_issue_and_pr_urls(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert ISSUE_URL in prompt
        assert PR_URL in prompt

    def test_includes_merge_conflict_header(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert "merge conflicts" in prompt.lower()

    def test_includes_make_quality_instruction(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert "make quality" in prompt

    def test_includes_do_not_push(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert "Do not push" in prompt

    def test_no_previous_error_on_first_attempt(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert "Previous Attempt Failed" not in prompt

    def test_no_error_section_when_error_is_none(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 2)
        assert "Previous Attempt Failed" not in prompt

    def test_includes_previous_error_on_retry(self) -> None:
        prompt = build_conflict_prompt(
            ISSUE_URL, PR_URL, "make quality failed: ruff error", 2
        )
        assert "## Previous Attempt Failed" in prompt
        assert "ruff error" in prompt
        assert "Attempt 1" in prompt

    def test_truncates_long_error(self) -> None:
        long_error = "x" * 5000
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, long_error, 3)
        assert "## Previous Attempt Failed" in prompt
        error_section = prompt.split("## Previous Attempt Failed")[1].split("##")[0]
        # The x's in the error section should be <= 3000
        assert error_section.count("x") <= 3000

    def test_includes_memory_suggestion_instructions(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert "MEMORY_SUGGESTION_START" in prompt
        assert "MEMORY_SUGGESTION_END" in prompt
        assert "## Optional: Memory Suggestion" in prompt
