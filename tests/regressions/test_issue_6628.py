"""Regression test for issue #6628.

Bug: HindsightWAL.replay() catches ``except Exception`` on ``client.retain``,
so programming errors (TypeError, AttributeError) are treated identically to
transient network failures.  They burn through max_retries and silently drop
the WAL entry instead of propagating immediately.

These tests will FAIL (RED) against the current code because replay() does
not distinguish programming errors from transient failures.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hindsight_wal import HindsightWAL, WALEntry


class TestIssue6628ProgrammingErrorsNotRetried:
    """Programming errors in client.retain must propagate, not be retried."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6628 — fix not yet landed", strict=False)
    async def test_type_error_propagates_immediately(self, tmp_path: Path) -> None:
        """TypeError from client.retain should not be caught and retried.

        Currently FAILS because line 140 catches all Exception subclasses,
        so TypeError is swallowed and the entry is retried/dropped silently.
        """
        wal = HindsightWAL(tmp_path / "wal.jsonl", max_retries=3)
        wal.append(WALEntry(bank="test", content="hello"))

        client = MagicMock()
        client.retain = AsyncMock(
            side_effect=TypeError("retain() got unexpected keyword argument 'foo'")
        )

        # A programming error should propagate — not be silently retried.
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            await wal.replay(client)

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6628 — fix not yet landed", strict=False)
    async def test_attribute_error_propagates_immediately(self, tmp_path: Path) -> None:
        """AttributeError from client.retain should not be caught and retried.

        Currently FAILS because line 140 catches all Exception subclasses,
        so AttributeError is swallowed and the entry is retried/dropped.
        """
        wal = HindsightWAL(tmp_path / "wal.jsonl", max_retries=3)
        wal.append(WALEntry(bank="test", content="hello"))

        client = MagicMock()
        client.retain = AsyncMock(
            side_effect=AttributeError("'NoneType' object has no attribute 'post'")
        )

        with pytest.raises(AttributeError, match="has no attribute"):
            await wal.replay(client)

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6628 — fix not yet landed", strict=False)
    async def test_assertion_error_propagates_immediately(self, tmp_path: Path) -> None:
        """AssertionError from client.retain should not be caught and retried."""
        wal = HindsightWAL(tmp_path / "wal.jsonl", max_retries=3)
        wal.append(WALEntry(bank="test", content="hello"))

        client = MagicMock()
        client.retain = AsyncMock(side_effect=AssertionError("invariant violated"))

        with pytest.raises(AssertionError, match="invariant violated"):
            await wal.replay(client)

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6628 — fix not yet landed", strict=False)
    async def test_programming_error_does_not_increment_retries(
        self, tmp_path: Path
    ) -> None:
        """A TypeError should not increment the retry count on WAL entries.

        Currently FAILS because the except block increments retries for ALL
        exceptions before the retry check can distinguish error categories.
        """
        wal = HindsightWAL(tmp_path / "wal.jsonl", max_retries=3)
        wal.append(WALEntry(bank="test", content="important"))

        client = MagicMock()
        client.retain = AsyncMock(side_effect=TypeError("wrong argument type"))

        # The programming error should propagate; the WAL entry should remain
        # untouched (retries == 0) so it can be replayed after the code fix.
        with pytest.raises(TypeError):
            await wal.replay(client)

        entries = wal.load()
        assert len(entries) == 1, "WAL entry should not have been dropped"
        assert entries[0].retries == 0, (
            "Programming errors should not increment the retry counter"
        )

    @pytest.mark.asyncio
    async def test_transient_errors_still_retried(self, tmp_path: Path) -> None:
        """Network errors (OSError, ConnectionError, TimeoutError) should
        still be retried — the fix must not break transient-failure handling.

        This test should PASS both before and after the fix.
        """
        wal = HindsightWAL(tmp_path / "wal.jsonl", max_retries=3)
        wal.append(WALEntry(bank="test", content="flaky"))

        client = MagicMock()
        client.retain = AsyncMock(side_effect=ConnectionError("refused"))

        result = await wal.replay(client)
        assert result["replayed"] == 0
        assert result["failed"] == 1

        entries = wal.load()
        assert len(entries) == 1
        assert entries[0].retries == 1


class TestIssue6628ClearHandlesDiskError:
    """WAL clear() should handle disk errors gracefully."""

    @pytest.mark.xfail(reason="Regression for issue #6628 — fix not yet landed", strict=False)
    def test_clear_does_not_raise_on_disk_error(self, tmp_path: Path) -> None:
        """clear() calls write_text("") unguarded — an OSError will crash the
        replay loop.

        Currently FAILS because clear() at line 100 does not catch OSError.
        """
        wal = HindsightWAL(tmp_path / "wal.jsonl")
        wal.append(WALEntry(bank="test", content="data"))

        # Make the file read-only so write_text raises PermissionError (OSError)
        wal_file = tmp_path / "wal.jsonl"
        wal_file.chmod(0o444)

        try:
            # clear() should handle the error gracefully, not raise
            wal.clear()  # Currently raises PermissionError
        finally:
            # Restore permissions for cleanup
            wal_file.chmod(0o644)
