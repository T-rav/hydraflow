"""Regression test for issue #6608.

Bug: ``HindsightWAL.replay`` calls ``self.write_all(remaining)`` after
replaying entries, but ``write_all`` catches ``OSError`` internally and
swallows it (line 94).  If the disk write fails (full disk, permission
denied), ``replay()`` returns success stats as if everything worked, but
the WAL file is **not** shrunk.  On the next replay cycle the same entries
are replayed again — leading to duplicate retains and unbounded WAL growth.

Additionally, ``run_wal_replay_loop`` catches ``Exception`` broadly at
line 195, so even if ``replay`` did propagate the error it would be
swallowed at the loop level.

These tests are RED against the current buggy code.
"""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hindsight_wal import HindsightWAL, WALEntry, run_wal_replay_loop


class TestWriteAllFailureSilentlySwallowed:
    """Issue #6608 — ``write_all`` failure during ``replay`` is silently
    swallowed, leaving the WAL un-shrunk despite reporting success.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6608 — fix not yet landed", strict=False)
    async def test_replay_wal_shrunk_after_successful_replay(
        self, tmp_path: Path
    ) -> None:
        """When all entries replay successfully, the WAL must be empty
        afterward — even when the underlying disk write fails.

        Currently FAILS (RED) because ``write_all`` catches ``OSError``
        silently: ``replay()`` reports ``replayed: 2`` but the WAL file
        still contains both entries.
        """
        wal_path = tmp_path / "wal.jsonl"
        wal = HindsightWAL(wal_path)
        wal.append(WALEntry(bank="a", content="entry-1"))
        wal.append(WALEntry(bank="b", content="entry-2"))
        assert wal.count == 2

        client = MagicMock()
        client.retain = AsyncMock()  # all retains succeed

        # Make the WAL file read-only to simulate disk-write failure
        # (e.g. disk full, permission denied).  write_all will catch the
        # resulting PermissionError (subclass of OSError) and swallow it.
        os.chmod(wal_path, stat.S_IRUSR)

        try:
            result = await wal.replay(client)

            # replay() claims both entries were replayed successfully
            assert result["replayed"] == 2
            assert result["failed"] == 0

            # BUG: After a "successful" replay the WAL must be empty.
            # Because write_all silently swallowed the OSError, the WAL
            # still has 2 entries — they will be replayed again next cycle.
            assert wal.count == 0, (
                f"replay reported {result['replayed']} entries replayed but WAL "
                f"still has {wal.count} entries — write_all failure was silently "
                f"swallowed (issue #6608)"
            )
        finally:
            # Restore write permission so tmp_path cleanup succeeds
            os.chmod(wal_path, stat.S_IRUSR | stat.S_IWUSR)

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6608 — fix not yet landed", strict=False)
    async def test_duplicate_retains_on_next_replay_cycle(self, tmp_path: Path) -> None:
        """When write_all fails, the next replay cycle re-replays entries
        that were already successfully sent to Hindsight — causing
        duplicate retains.

        Currently FAILS (RED): client.retain is called 4 times (2 entries
        x 2 cycles) instead of the expected 2.
        """
        wal_path = tmp_path / "wal.jsonl"
        wal = HindsightWAL(wal_path)
        wal.append(WALEntry(bank="a", content="entry-1"))
        wal.append(WALEntry(bank="b", content="entry-2"))

        client = MagicMock()
        client.retain = AsyncMock()  # all retains succeed

        # Make WAL read-only so write_all silently fails
        os.chmod(wal_path, stat.S_IRUSR)

        try:
            # First replay cycle — entries replayed but WAL not shrunk
            await wal.replay(client)
            first_cycle_calls = client.retain.await_count

            # Second replay cycle — same entries replayed AGAIN
            await wal.replay(client)
            total_calls = client.retain.await_count

            # BUG: Each entry should only be retained once.  Because
            # write_all silently failed, the second cycle re-replays
            # the same 2 entries → 4 total calls instead of 2.
            assert total_calls == first_cycle_calls, (
                f"client.retain was called {total_calls} times across 2 replay "
                f"cycles but entries should only be replayed once — "
                f"write_all failure caused duplicate retains (issue #6608)"
            )
        finally:
            os.chmod(wal_path, stat.S_IRUSR | stat.S_IWUSR)


class TestReplayLoopDoesNotSwallowWriteErrors:
    """Issue #6608 — ``run_wal_replay_loop`` catches ``Exception`` too
    broadly, masking ``write_all`` failures at the loop level.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6608 — fix not yet landed", strict=False)
    async def test_loop_does_not_grow_wal_on_write_failure(
        self, tmp_path: Path
    ) -> None:
        """When write_all fails inside the replay loop, the WAL must not
        accumulate duplicate entries across iterations.

        Currently FAILS (RED): the loop swallows all exceptions, so the
        WAL is never shrunk and entries pile up.
        """
        wal_path = tmp_path / "wal.jsonl"
        wal = HindsightWAL(wal_path)
        wal.append(WALEntry(bank="a", content="entry-1"))

        client = MagicMock()
        client.retain = AsyncMock()

        stop = asyncio.Event()

        # Make WAL read-only so write_all silently fails
        os.chmod(wal_path, stat.S_IRUSR)

        try:
            # Let the loop run one iteration then stop
            async def run_and_stop() -> None:
                await asyncio.sleep(0.15)
                stop.set()

            await asyncio.gather(
                run_wal_replay_loop(wal, client, stop, interval=1),
                run_and_stop(),
            )

            # After the loop, the WAL should be drained (entry was replayed)
            # BUG: WAL still has the entry because write_all failed silently
            assert wal.count == 0, (
                f"WAL still has {wal.count} entries after replay loop — "
                f"write_all failure was swallowed by broad except "
                f"(issue #6608)"
            )
        finally:
            os.chmod(wal_path, stat.S_IRUSR | stat.S_IWUSR)
