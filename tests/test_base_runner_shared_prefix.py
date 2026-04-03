"""Tests for BaseRunner.hindsight property and shared_prefix mode (#5938)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from base_runner import BaseRunner  # noqa: E402


class _TestRunner(BaseRunner):
    """Minimal concrete subclass that satisfies the ClassVar requirement."""

    _log = logging.getLogger("hydraflow.test_runner_shared_prefix")


class TestBaseRunnerHindsightProperty:
    """Tests for the BaseRunner.hindsight read-only property."""

    def _make_runner(self, hindsight=None):
        """Construct a _TestRunner with minimal dependencies."""
        config = MagicMock()
        config.model = "claude-3-5-sonnet-latest"
        config.implementation_tool = "claude"
        event_bus = MagicMock()
        runner = MagicMock()
        return _TestRunner(config, event_bus, runner, hindsight=hindsight)

    def test_hindsight_property_returns_none_by_default(self) -> None:
        """hindsight defaults to None when not provided."""
        r = self._make_runner()
        assert r.hindsight is None

    def test_hindsight_property_returns_client_when_set(self) -> None:
        """hindsight returns the exact client object that was injected."""
        mock_client = MagicMock()
        r = self._make_runner(hindsight=mock_client)
        assert r.hindsight is mock_client

    def test_hindsight_property_is_read_only(self) -> None:
        """hindsight cannot be set — it is a read-only property."""
        r = self._make_runner()
        try:
            r.hindsight = MagicMock()  # type: ignore[misc]
            # If no exception, fall through and fail the test
            assert False, "Expected AttributeError when setting read-only property"
        except AttributeError:
            pass  # Expected — property has no setter

    def test_hindsight_is_same_object_as_internal_attribute(self) -> None:
        """hindsight property reflects _hindsight without copying."""
        mock_client = MagicMock()
        r = self._make_runner(hindsight=mock_client)
        assert r.hindsight is r._hindsight


class TestInjectManifestAndMemorySharedPrefix:
    """Tests for the shared_prefix fast-path in _inject_manifest_and_memory."""

    def _make_runner(self, hindsight=None, max_memory_prompt_chars=4000):
        """Construct a _TestRunner with minimal dependencies."""
        config = MagicMock()
        config.model = "claude-3-5-sonnet-latest"
        config.implementation_tool = "claude"
        config.max_memory_prompt_chars = max_memory_prompt_chars
        event_bus = MagicMock()
        runner = MagicMock()
        return _TestRunner(config, event_bus, runner, hindsight=hindsight)

    @pytest.mark.asyncio
    async def test_shared_prefix_skips_full_recall(self) -> None:
        """When shared_prefix is provided, only LEARNINGS is recalled (not all 5 banks)."""
        mock_hindsight = MagicMock()
        r = self._make_runner(hindsight=mock_hindsight)

        mock_recall = AsyncMock(return_value=[])
        with (
            patch("hindsight.recall_safe", mock_recall),
            patch(
                "hindsight.format_memories_as_markdown", return_value="- memory item"
            ),
            patch("hindsight.Bank") as mock_bank,
        ):
            mock_bank.LEARNINGS = "LEARNINGS"
            prefix_section, topup_section = await r._inject_manifest_and_memory(
                query_context="auth issue", shared_prefix="SHARED"
            )

        assert prefix_section == "SHARED"
        assert "Issue-Specific Context" in topup_section
        # recall_safe called exactly once (LEARNINGS only, not 5 banks)
        assert mock_recall.call_count == 1

    @pytest.mark.asyncio
    async def test_shared_prefix_none_uses_existing_behavior(self) -> None:
        """When shared_prefix is None, full existing behavior runs (no hindsight → empty)."""
        r = self._make_runner(hindsight=None)

        prefix_section, memory_section = await r._inject_manifest_and_memory(
            query_context="some issue", shared_prefix=None
        )

        # No hindsight configured → both sections empty
        assert prefix_section == ""
        assert memory_section == ""

    @pytest.mark.asyncio
    async def test_shared_prefix_topup_capped(self) -> None:
        """Top-up memory is capped at max_memory_prompt_chars // 4."""
        mock_hindsight = MagicMock()
        # cap = 400 // 4 = 100
        r = self._make_runner(hindsight=mock_hindsight, max_memory_prompt_chars=400)

        long_memory = "- " + "x" * 500  # 502 chars, well over the 100-char cap

        mock_recall = AsyncMock(return_value=[])
        with (
            patch("hindsight.recall_safe", mock_recall),
            patch("hindsight.format_memories_as_markdown", return_value=long_memory),
            patch("hindsight.Bank") as mock_bank,
        ):
            mock_bank.LEARNINGS = "LEARNINGS"
            _, topup_section = await r._inject_manifest_and_memory(
                query_context="auth issue", shared_prefix="PREFIX"
            )

        # The raw memory content in the topup section must be <= topup_cap (100)
        # The section includes the header "## Issue-Specific Context\n\n" + capped raw
        assert "Issue-Specific Context" in topup_section
        # Content after the header must be at most 100 chars
        header = "\n\n## Issue-Specific Context\n\n"
        content_after_header = topup_section[len(header) :]
        assert len(content_after_header) <= 100
