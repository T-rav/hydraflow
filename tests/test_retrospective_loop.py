"""Tests for the RetrospectiveLoop background worker."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestRetrospectiveIntervalConfig:
    def test_default_interval(self) -> None:
        from config import HydraFlowConfig

        cfg = HydraFlowConfig()
        assert cfg.retrospective_interval == 1800

    def test_rejects_below_minimum(self) -> None:
        from config import HydraFlowConfig

        with pytest.raises(ValidationError):
            HydraFlowConfig(retrospective_interval=10)

    def test_accepts_valid_value(self) -> None:
        from config import HydraFlowConfig

        cfg = HydraFlowConfig(retrospective_interval=3600)
        assert cfg.retrospective_interval == 3600


# ---------------------------------------------------------------------------
# RetrospectiveLoop tests
# ---------------------------------------------------------------------------

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from events import EventType
from retrospective_loop import RetrospectiveLoop
from retrospective_queue import QueueItem, QueueKind
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
) -> tuple[RetrospectiveLoop, MagicMock, MagicMock, MagicMock]:
    """Build loop with mocks. Returns (loop, retro_mock, insights_mock, queue_mock)."""
    deps = make_bg_loop_deps(tmp_path, enabled=True)

    retro = MagicMock()
    retro._load_recent = MagicMock(return_value=[])
    retro._detect_patterns = AsyncMock()

    insights = MagicMock()
    insights.load_recent = MagicMock(return_value=[])

    queue = MagicMock()
    queue.load = MagicMock(return_value=[])
    queue.acknowledge = MagicMock()

    loop = RetrospectiveLoop(
        config=deps.config,
        deps=deps.loop_deps,
        retrospective=retro,
        insights=insights,
        queue=queue,
    )
    return loop, retro, insights, queue


class TestDoWorkEmptyQueue:
    @pytest.mark.asyncio
    async def test_returns_zero_counts(self, tmp_path: Path) -> None:
        loop, _, _, queue = _make_loop(tmp_path)
        queue.load.return_value = []

        result = await loop._do_work()

        assert result == {"processed": 0, "patterns_filed": 0, "stale_proposals": 0}

    @pytest.mark.asyncio
    async def test_does_not_acknowledge_anything(self, tmp_path: Path) -> None:
        loop, _, _, queue = _make_loop(tmp_path)
        queue.load.return_value = []

        await loop._do_work()

        queue.acknowledge.assert_not_called()


class TestDoWorkProcessesItems:
    @pytest.mark.asyncio
    async def test_processes_retro_pattern_item(self, tmp_path: Path) -> None:
        loop, retro, _, queue = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=42)
        queue.load.return_value = [item]

        await loop._do_work()

        retro._detect_patterns.assert_awaited_once()
        queue.acknowledge.assert_called_once_with([item.id])

    @pytest.mark.asyncio
    async def test_processes_review_pattern_item(self, tmp_path: Path) -> None:
        loop, _, insights, queue = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.REVIEW_PATTERNS, pr_number=99)
        queue.load.return_value = [item]

        await loop._do_work()

        insights.load_recent.assert_called()
        queue.acknowledge.assert_called_once_with([item.id])

    @pytest.mark.asyncio
    async def test_processes_verify_proposals_item(self, tmp_path: Path) -> None:
        loop, _, insights, queue = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.VERIFY_PROPOSALS)
        queue.load.return_value = [item]

        await loop._do_work()

        queue.acknowledge.assert_called_once_with([item.id])

    @pytest.mark.asyncio
    async def test_publishes_event_per_item(self, tmp_path: Path) -> None:
        loop, _, _, queue = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=42)
        queue.load.return_value = [item]

        await loop._do_work()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.RETROSPECTIVE_UPDATE
        ]
        assert len(events) >= 1
        assert events[0].data.get("status") == "processed"


class TestDoWorkErrorHandling:
    @pytest.mark.asyncio
    async def test_failed_item_not_acknowledged(self, tmp_path: Path) -> None:
        loop, retro, _, queue = _make_loop(tmp_path)
        item = QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=42)
        queue.load.return_value = [item]
        retro._detect_patterns.side_effect = RuntimeError("boom")

        result = await loop._do_work()

        queue.acknowledge.assert_not_called()
        assert result is not None
        assert result["processed"] == 0
