"""Regression test for issue #6717.

``RunRecorder.get_storage_stats()`` iterates run directories and calls
``f.stat()`` on each file inside a triple-nested loop with no ``OSError``
handling.  If any file is deleted mid-iteration (by the GC background loop
or an NFS hiccup), the unguarded ``f.stat()`` raises ``FileNotFoundError``
that propagates to the dashboard API handler and returns a 500.

These tests will fail (RED) until ``get_storage_stats()`` wraps
``f.stat().st_size`` in a ``try/except OSError: continue`` guard, and
``purge_expired()`` guards its iteration against concurrent directory
removal.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from run_recorder import RunRecorder


def _make_recorder(tmp_path: Path) -> RunRecorder:
    """Create a RunRecorder pointing at a temporary runs directory."""
    config = MagicMock()
    config.data_path.return_value = tmp_path / "runs"
    return RunRecorder(config)


def _populate_run(
    runs_dir: Path, issue: int, timestamp: str, files: dict[str, bytes]
) -> Path:
    """Create a run directory with the given files and return the run dir."""
    run_dir = runs_dir / str(issue) / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (run_dir / name).write_bytes(content)
    return run_dir


# ---------------------------------------------------------------------------
# Test 1 — get_storage_stats raises FileNotFoundError on concurrent deletion
# ---------------------------------------------------------------------------


class TestGetStorageStatsConcurrentDeletion:
    """get_storage_stats must not crash when a file vanishes mid-iteration."""

    @pytest.mark.xfail(reason="Regression for issue #6717 — fix not yet landed", strict=False)
    def test_stat_raises_file_not_found_mid_iteration(self, tmp_path: Path) -> None:
        """Simulate a file being deleted by GC between rglob enumeration and
        the stat() call.  The current code has no OSError guard, so this
        raises FileNotFoundError.

        After the fix, get_storage_stats should return partial totals
        (skipping the missing file) instead of propagating the exception.
        """
        recorder = _make_recorder(tmp_path)
        runs_dir = tmp_path / "runs"

        # Create two runs with files
        _populate_run(
            runs_dir,
            42,
            "20260410T120000Z",
            {
                "plan.txt": b"x" * 100,
                "transcript.txt": b"y" * 200,
            },
        )
        _populate_run(
            runs_dir,
            42,
            "20260410T130000Z",
            {
                "plan.txt": b"z" * 150,
            },
        )

        # Delete one file after the directory listing has been built but
        # before stat() is called — simulating concurrent GC deletion.
        vanishing_file = runs_dir / "42" / "20260410T120000Z" / "transcript.txt"
        assert vanishing_file.exists(), "setup error: file should exist initially"

        original_stat = Path.stat
        # Track calls to stat() for the vanishing file.
        # The first call comes from is_file() — let it succeed so the code
        # enters the ``total_bytes += f.stat().st_size`` branch.
        # Delete the file before the second call (the explicit .stat()) so
        # it raises FileNotFoundError — exactly the race condition from the bug.
        call_count = 0

        def stat_that_deletes_on_second_call(self_path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            if self_path == vanishing_file:
                call_count += 1
                if call_count == 2:
                    # Delete between is_file() and .stat().st_size
                    vanishing_file.unlink()
            return original_stat(self_path, *args, **kwargs)

        # Patch Path.stat to simulate the race condition
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "stat", stat_that_deletes_on_second_call)

            # BUG: this raises FileNotFoundError instead of returning partial results
            result = recorder.get_storage_stats()

        # After the fix, we should get partial totals for the surviving files
        assert isinstance(result, dict), "get_storage_stats should return a dict"
        assert result["total_runs"] == 2
        # The surviving files are plan.txt (100 bytes) + plan.txt (150 bytes) = 250
        assert result["total_bytes"] == 250, (
            f"Expected 250 bytes from surviving files, got {result['total_bytes']}"
        )


# ---------------------------------------------------------------------------
# Test 2 — get_storage_stats handles PermissionError on stat()
# ---------------------------------------------------------------------------


class TestGetStorageStatsPermissionError:
    """get_storage_stats must not crash on PermissionError (e.g. NFS)."""

    @pytest.mark.xfail(reason="Regression for issue #6717 — fix not yet landed", strict=False)
    def test_stat_permission_error_is_skipped(self, tmp_path: Path) -> None:
        """If stat() raises PermissionError for a file, get_storage_stats
        should skip that file and continue, not propagate the exception.
        """
        recorder = _make_recorder(tmp_path)
        runs_dir = tmp_path / "runs"

        run_dir = _populate_run(
            runs_dir,
            10,
            "20260410T100000Z",
            {
                "plan.txt": b"a" * 50,
                "locked.bin": b"b" * 300,
            },
        )

        original_stat = Path.stat
        locked_path = run_dir / "locked.bin"

        def stat_with_permission_error(self_path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self_path == locked_path:
                raise PermissionError(13, "Permission denied", str(locked_path))
            return original_stat(self_path, *args, **kwargs)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "stat", stat_with_permission_error)

            # BUG: this raises PermissionError instead of skipping
            result = recorder.get_storage_stats()

        assert isinstance(result, dict)
        assert result["total_bytes"] == 50, (
            f"Expected 50 bytes (only plan.txt counted), got {result['total_bytes']}"
        )


# ---------------------------------------------------------------------------
# Test 3 — purge_expired handles OSError when issue_dir vanishes
# ---------------------------------------------------------------------------


class TestPurgeExpiredConcurrentDeletion:
    """purge_expired must not crash when a directory vanishes mid-iteration."""

    @pytest.mark.xfail(reason="Regression for issue #6717 — fix not yet landed", strict=False)
    def test_iterdir_raises_when_issue_dir_removed_concurrently(
        self, tmp_path: Path
    ) -> None:
        """If an issue directory is removed by another process between the
        ``list(self._runs_dir.iterdir())`` snapshot and the
        ``issue_dir.is_dir()`` check, the function should handle the race
        gracefully.

        We simulate this by removing the issue dir right when is_dir() is
        called on it, causing the subsequent iterdir() to raise.
        """
        recorder = _make_recorder(tmp_path)
        runs_dir = tmp_path / "runs"

        # Create an old run that qualifies for purging (> 30 days old)
        _populate_run(
            runs_dir,
            99,
            "20250101T000000Z",
            {
                "plan.txt": b"old",
            },
        )
        # Also create a dir that will vanish
        vanishing_issue = runs_dir / "88"
        vanishing_run = vanishing_issue / "20250101T000000Z"
        vanishing_run.mkdir(parents=True)
        (vanishing_run / "data.txt").write_bytes(b"gone")

        original_iterdir = Path.iterdir

        def iterdir_that_removes(self_path: Path):  # type: ignore[no-untyped-def]
            """When iterdir is called on the vanishing issue dir, delete it
            first to simulate concurrent removal."""
            if self_path == vanishing_issue and vanishing_issue.exists():
                import shutil

                shutil.rmtree(vanishing_issue)
            return original_iterdir(self_path)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "iterdir", iterdir_that_removes)

            # BUG: this raises FileNotFoundError from iterdir on deleted dir
            removed = recorder.purge_expired(retention_days=30)

        # The non-vanishing old run should still be purged successfully
        assert removed >= 1, f"Expected at least 1 purged run, got {removed}"
