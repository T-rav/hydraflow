"""Tests for harness insight auto-filing (auto_file_suggestions)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from harness_insights import (
    FailureCategory,
    FailureRecord,
    HarnessInsightStore,
    ImprovementSuggestion,
    auto_file_suggestions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> HarnessInsightStore:
    memory_dir = tmp_path / ".hydraflow" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return HarnessInsightStore(memory_dir)


def _make_prs(issue_number: int = 101) -> AsyncMock:
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=issue_number)
    return prs


def _dummy_record() -> FailureRecord:
    return FailureRecord(
        issue_number=1,
        category=FailureCategory.QUALITY_GATE,
        details="ruff error",
    )


def _suggestion(
    category: str = "quality_gate",
    subcategory: str = "",
    description: str = "Quality gate failure during implementation",
    occurrence_count: int = 4,
) -> ImprovementSuggestion:
    return ImprovementSuggestion(
        category=category,
        subcategory=subcategory,
        occurrence_count=occurrence_count,
        window_size=10,
        description=description,
        suggestion="Add pre-implementation quality checks.",
        evidence=[],
    )


# ---------------------------------------------------------------------------
# auto_file_suggestions — happy path
# ---------------------------------------------------------------------------


class TestAutoFileSuggestions:
    """Tests for harness_insights.auto_file_suggestions."""

    @pytest.mark.asyncio
    async def test_no_records_returns_early(self, config: HydraFlowConfig) -> None:
        """When there are no records, no issue should be filed."""
        store = _make_store(config.repo_root)
        prs = _make_prs()

        await auto_file_suggestions(store, prs, config)

        prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_files_issue_for_recurring_pattern(
        self, config: HydraFlowConfig
    ) -> None:
        """When a pattern exceeds the threshold, an issue is filed."""
        store = _make_store(config.repo_root)
        store.append_failure(_dummy_record())
        prs = _make_prs(issue_number=42)

        suggestions = [_suggestion()]

        with patch(
            "harness_insights.generate_suggestions",
            return_value=suggestions,
        ):
            await auto_file_suggestions(store, prs, config)

        prs.create_issue.assert_called_once()
        call_args = prs.create_issue.call_args
        title = call_args[0][0]
        assert title.startswith("[Harness Insight]")
        assert "Quality gate" in title

    @pytest.mark.asyncio
    async def test_marks_pattern_proposed_after_filing(
        self, config: HydraFlowConfig
    ) -> None:
        """After filing, the key should be in the proposed set."""
        store = _make_store(config.repo_root)
        store.append_failure(_dummy_record())
        prs = _make_prs(issue_number=55)

        with patch(
            "harness_insights.generate_suggestions",
            return_value=[
                _suggestion(category="ci_failure", description="CI pipeline failure")
            ],
        ):
            await auto_file_suggestions(store, prs, config)

        proposed = store.get_proposed_patterns()
        assert "category:ci_failure" in proposed

    @pytest.mark.asyncio
    async def test_does_not_refile_already_proposed_pattern(
        self, config: HydraFlowConfig
    ) -> None:
        """A pattern that is already proposed should not generate a new issue."""
        store = _make_store(config.repo_root)
        store.append_failure(_dummy_record())
        store.mark_pattern_proposed("category:quality_gate")
        prs = _make_prs()

        # generate_suggestions receives the already-proposed set and returns nothing
        with patch(
            "harness_insights.generate_suggestions",
            return_value=[],
        ):
            await auto_file_suggestions(store, prs, config)

        prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_subcategory_key_used_for_subcategory_suggestions(
        self, config: HydraFlowConfig
    ) -> None:
        """Subcategory suggestions use 'subcategory:<name>' as the dedup key."""
        store = _make_store(config.repo_root)
        store.append_failure(_dummy_record())
        prs = _make_prs(issue_number=77)

        with patch(
            "harness_insights.generate_suggestions",
            return_value=[
                _suggestion(
                    category="quality_gate",
                    subcategory="lint_error",
                    description="Recurring lint_error failures",
                )
            ],
        ):
            await auto_file_suggestions(store, prs, config)

        proposed = store.get_proposed_patterns()
        assert "subcategory:lint_error" in proposed

    @pytest.mark.asyncio
    async def test_uses_improve_label_from_config(
        self, config: HydraFlowConfig
    ) -> None:
        """Issues should be filed with the config's improve_label."""
        store = _make_store(config.repo_root)
        store.append_failure(_dummy_record())
        prs = _make_prs(issue_number=88)

        with patch(
            "harness_insights.generate_suggestions",
            return_value=[
                _suggestion(
                    category="review_rejection", description="PR rejected by reviewer"
                )
            ],
        ):
            await auto_file_suggestions(store, prs, config)

        call_args = prs.create_issue.call_args
        labels_arg = call_args[0][2]
        assert list(config.improve_label) == labels_arg

    @pytest.mark.asyncio
    async def test_create_issue_failure_does_not_raise(
        self, config: HydraFlowConfig
    ) -> None:
        """A failure in create_issue should be swallowed without crashing."""
        store = _make_store(config.repo_root)
        store.append_failure(_dummy_record())
        prs = AsyncMock()
        prs.create_issue = AsyncMock(side_effect=RuntimeError("network error"))

        with patch(
            "harness_insights.generate_suggestions",
            return_value=[
                _suggestion(category="hitl_escalation", description="Escalated to HITL")
            ],
        ):
            # Should not raise
            await auto_file_suggestions(store, prs, config)

    @pytest.mark.asyncio
    async def test_does_not_mark_proposed_when_create_issue_returns_none(
        self, config: HydraFlowConfig
    ) -> None:
        """When create_issue returns None (dry-run / failure), key must not be proposed."""
        store = _make_store(config.repo_root)
        store.append_failure(_dummy_record())
        prs = AsyncMock()
        prs.create_issue = AsyncMock(return_value=None)

        with patch(
            "harness_insights.generate_suggestions",
            return_value=[
                _suggestion(
                    category="plan_validation", description="Plan validation failed"
                )
            ],
        ):
            await auto_file_suggestions(store, prs, config)

        # Key should NOT be in proposed because create_issue returned None
        assert "category:plan_validation" not in store.get_proposed_patterns()
