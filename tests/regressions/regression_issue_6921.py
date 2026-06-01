"""Regression test for issue #6921.

Bug: RepoRegistryStore.load() catches FileNotFoundError and JSONDecodeError
but not generic OSError.  A PermissionError or I/O error on repos.json
crashes server startup (_restore_registered_repos), leaving the dashboard
with no registered repos.

Similarly, save() calls atomic_write with no OSError guard, so disk-full or
permission errors propagate to callers.

Expected behaviour after fix:
  - load() returns [] and logs a warning on OSError (other than the
    FileNotFoundError that already returns [] silently).
  - save() logs an error on OSError rather than letting it propagate.

These tests assert the *correct* behaviour, so they are RED against the
current (buggy) code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from repo_store import RepoRecord, RepoRegistryStore


@pytest.fixture()
def store(tmp_path: Path) -> RepoRegistryStore:
    return RepoRegistryStore(tmp_path)


def _sample_record() -> RepoRecord:
    return RepoRecord(
        slug="acme-app",
        repo="acme/app",
        path="/tmp/acme-app",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


class TestLoadOSError:
    """Issue #6921 — load() should handle OSError gracefully."""

    @pytest.mark.xfail(reason="Regression for issue #6921 — fix not yet landed", strict=False)
    def test_permission_error_returns_empty_list(
        self, store: RepoRegistryStore
    ) -> None:
        """PermissionError on repos.json must return [] not crash."""
        # Ensure the file exists so we don't hit the FileNotFoundError branch
        store.save([_sample_record()])

        with patch.object(
            Path,
            "read_text",
            side_effect=PermissionError("Permission denied"),
        ):
            result = store.load()

        assert result == [], (
            "load() raised PermissionError instead of returning [] — "
            "this is the OSError bug from issue #6921"
        )

    @pytest.mark.xfail(reason="Regression for issue #6921 — fix not yet landed", strict=False)
    def test_io_error_returns_empty_list(self, store: RepoRegistryStore) -> None:
        """Generic OSError (I/O failure) on repos.json must return []."""
        store.save([_sample_record()])

        with patch.object(
            Path,
            "read_text",
            side_effect=OSError(5, "Input/output error"),
        ):
            result = store.load()

        assert result == [], (
            "load() raised OSError instead of returning [] — "
            "this is the OSError bug from issue #6921"
        )


class TestSaveOSError:
    """Issue #6921 — save() should handle OSError gracefully."""

    @pytest.mark.xfail(reason="Regression for issue #6921 — fix not yet landed", strict=False)
    def test_permission_error_on_save_does_not_propagate(
        self,
        store: RepoRegistryStore,
    ) -> None:
        """PermissionError during save must be caught, not propagated."""
        with patch(
            "repo_store.atomic_write",
            side_effect=PermissionError("Permission denied"),
        ):
            # After the fix, save() should catch the error and log it
            # rather than letting PermissionError propagate to callers.
            try:
                store.save([_sample_record()])
            except PermissionError:
                pytest.fail(
                    "save() raised PermissionError instead of handling it — "
                    "this is the OSError bug from issue #6921"
                )

    @pytest.mark.xfail(reason="Regression for issue #6921 — fix not yet landed", strict=False)
    def test_disk_full_on_save_does_not_propagate(
        self,
        store: RepoRegistryStore,
    ) -> None:
        """OSError (disk full) during save must be caught, not propagated."""
        with patch(
            "repo_store.atomic_write",
            side_effect=OSError(28, "No space left on device"),
        ):
            try:
                store.save([_sample_record()])
            except OSError:
                pytest.fail(
                    "save() raised OSError instead of handling it — "
                    "this is the OSError bug from issue #6921"
                )
