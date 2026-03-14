"""Tests for prompt budget configuration fields (issue #2578).

Verifies that hardcoded prompt truncation limits have been extracted to
HydraFlowConfig fields and are consumed by the respective runners.
"""

from __future__ import annotations

import pytest

from agent import AgentRunner
from events import EventBus
from models import JudgeResult, PRInfo, Task
from planner import PlannerRunner
from tests.helpers import ConfigFactory
from verification import (
    _DEFAULT_MAX_INSTRUCTIONS_CHARS,
    format_verification_issue_body,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


def _make_task(**kwargs) -> Task:
    defaults = {
        "id": 1,
        "title": "t",
        "body": "b",
        "tags": [],
        "comments": [],
        "source_url": "https://github.com/o/r/issues/1",
    }
    defaults.update(kwargs)
    return Task(**defaults)


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestPromptBudgetConfigDefaults:
    """Each new config field should have the correct default value."""

    _EXPECTED_DEFAULTS: list[tuple[str, int]] = [
        ("max_discussion_comment_chars", 500),
        ("max_common_feedback_chars", 2_000),
        ("max_impl_plan_chars", 6_000),
        ("max_review_feedback_chars", 2_000),
        ("max_planner_comment_chars", 1_000),
        ("max_planner_line_chars", 500),
        ("max_hitl_correction_chars", 4_000),
        ("max_hitl_cause_chars", 2_000),
        ("max_ci_log_prompt_chars", 6_000),
        ("max_unsticker_cause_chars", 3_000),
        ("max_verification_instructions_chars", 50_000),
    ]

    @pytest.mark.parametrize(
        ("field", "expected"),
        _EXPECTED_DEFAULTS,
        ids=[e[0] for e in _EXPECTED_DEFAULTS],
    )
    def test_default_value(self, field: str, expected: int) -> None:
        cfg = ConfigFactory.create()
        assert getattr(cfg, field) == expected

    @pytest.mark.parametrize(
        ("field", "expected"),
        _EXPECTED_DEFAULTS,
        ids=[e[0] for e in _EXPECTED_DEFAULTS],
    )
    def test_custom_value_persists(self, field: str, expected: int) -> None:
        custom = expected + 100
        cfg = ConfigFactory.create(**{field: custom})
        assert getattr(cfg, field) == custom


# ---------------------------------------------------------------------------
# AgentRunner reads from config
# ---------------------------------------------------------------------------


class TestAgentRunnerPromptBudgets:
    """AgentRunner should use config fields instead of class constants."""

    def test_truncate_comment_uses_config(self, event_bus: EventBus) -> None:
        cfg = ConfigFactory.create(max_discussion_comment_chars=100)
        runner = AgentRunner(cfg, event_bus)
        short = "hello"
        assert runner._truncate_comment_for_prompt(short) == short

        long_text = "a" * 200
        result = runner._truncate_comment_for_prompt(long_text)
        assert result.startswith("a" * 100)
        assert "truncated" in result.lower()

    def test_truncate_comment_exact_boundary(self, event_bus: EventBus) -> None:
        cfg = ConfigFactory.create(max_discussion_comment_chars=100)
        runner = AgentRunner(cfg, event_bus)
        exact = "a" * 100
        assert runner._truncate_comment_for_prompt(exact) == exact

    def test_truncate_comment_empty_input(self, event_bus: EventBus) -> None:
        cfg = ConfigFactory.create(max_discussion_comment_chars=100)
        runner = AgentRunner(cfg, event_bus)
        assert runner._truncate_comment_for_prompt("") == ""
        assert runner._truncate_comment_for_prompt(None) == ""

    def test_no_class_level_constants(self) -> None:
        """Class should no longer have the old hardcoded constants."""
        for attr in (
            "_MAX_DISCUSSION_COMMENT_CHARS",
            "_MAX_COMMON_FEEDBACK_CHARS",
            "_MAX_IMPL_PLAN_CHARS",
            "_MAX_REVIEW_FEEDBACK_CHARS",
        ):
            assert not hasattr(AgentRunner, attr), f"{attr} should be removed"


# ---------------------------------------------------------------------------
# PlannerRunner reads from config
# ---------------------------------------------------------------------------


class TestPlannerRunnerPromptBudgets:
    """PlannerRunner should use config fields instead of class constants."""

    def test_truncate_text_uses_config(self, event_bus: EventBus) -> None:
        cfg = ConfigFactory.create(
            max_planner_comment_chars=200,
            max_planner_line_chars=100,
        )
        runner = PlannerRunner(cfg, event_bus)
        text = "short line\nanother line"
        truncated = runner._truncate_text(
            text, runner._max_comment_chars, runner._max_line_chars
        )
        assert truncated == text  # Under limit, no truncation
        assert runner._max_comment_chars == 200
        assert runner._max_line_chars == 100

    def test_max_line_chars_property(self, event_bus: EventBus) -> None:
        cfg = ConfigFactory.create(max_planner_line_chars=142)
        runner = PlannerRunner(cfg, event_bus)
        assert runner._max_line_chars == 142

    def test_max_comment_chars_property(self, event_bus: EventBus) -> None:
        cfg = ConfigFactory.create(max_planner_comment_chars=321)
        runner = PlannerRunner(cfg, event_bus)
        assert runner._max_comment_chars == 321

    def test_no_class_level_constants(self) -> None:
        for attr in ("_MAX_COMMENT_CHARS", "_MAX_LINE_CHARS"):
            assert not hasattr(PlannerRunner, attr), f"{attr} should be removed"


# ---------------------------------------------------------------------------
# Verification uses configurable limit
# ---------------------------------------------------------------------------


class TestVerificationPromptBudget:
    """format_verification_issue_body should respect max_instructions_chars."""

    def test_default_constant_unchanged(self) -> None:
        assert _DEFAULT_MAX_INSTRUCTIONS_CHARS == 50_000

    def test_truncation_with_custom_limit(self) -> None:
        judge = JudgeResult(
            issue_number=1,
            pr_number=10,
            criteria=[],
            verification_instructions="x" * 200,
        )
        task = _make_task()
        pr = PRInfo(
            number=10, issue_number=1, url="https://github.com/o/r/pull/10", branch="b"
        )
        body = format_verification_issue_body(
            judge, task, pr, max_instructions_chars=50
        )
        assert "*...truncated*" in body
        # The instructions section should be present but truncated
        assert "x" * 50 in body
        assert "x" * 200 not in body

    def test_no_truncation_when_under_limit(self) -> None:
        instructions = "Check the thing"
        judge = JudgeResult(
            issue_number=1,
            pr_number=10,
            criteria=[],
            verification_instructions=instructions,
        )
        task = _make_task()
        pr = PRInfo(
            number=10, issue_number=1, url="https://github.com/o/r/pull/10", branch="b"
        )
        body = format_verification_issue_body(
            judge, task, pr, max_instructions_chars=1000
        )
        assert instructions in body
        assert "truncated" not in body

    def test_empty_instructions_no_crash(self) -> None:
        judge = JudgeResult(
            issue_number=1, pr_number=10, criteria=[], verification_instructions=""
        )
        task = _make_task()
        pr = PRInfo(
            number=10, issue_number=1, url="https://github.com/o/r/pull/10", branch="b"
        )
        body = format_verification_issue_body(
            judge, task, pr, max_instructions_chars=100
        )
        assert "Verification Instructions" not in body


# ---------------------------------------------------------------------------
# Config validation boundaries
# ---------------------------------------------------------------------------


class TestPromptBudgetValidation:
    """Fields should reject values outside their allowed range."""

    def test_discussion_comment_chars_too_low(self) -> None:
        with pytest.raises(ValueError):
            ConfigFactory.create(max_discussion_comment_chars=1)

    def test_planner_line_chars_too_low(self) -> None:
        with pytest.raises(ValueError):
            ConfigFactory.create(max_planner_line_chars=1)

    def test_verification_instructions_too_high(self) -> None:
        with pytest.raises(ValueError):
            ConfigFactory.create(max_verification_instructions_chars=100_000)
