"""Regression test for issue #6699.

Bug: ``_save_prep_coverage_floor`` writes state to disk via bare
``write_text()`` with no ``try/except OSError``.  When the disk is full
or the parent directory is read-only, the ``OSError`` propagates unhandled
through the ``run_prep`` call chain, surfacing as a 500 or unhandled
exception rather than a logged warning.

These tests assert that ``_save_prep_coverage_floor`` catches ``OSError``
and does NOT propagate it to callers.  They will FAIL (RED) against the
current code because there is no error handling around the write.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from admin_tasks import _save_prep_coverage_floor


class TestIssue6699SavePrepCoverageFloorErrorHandling:
    """_save_prep_coverage_floor must not propagate OSError to callers."""

    @pytest.mark.xfail(reason="Regression for issue #6699 — fix not yet landed", strict=False)
    def test_oserror_on_write_does_not_propagate(self, tmp_path: Path) -> None:
        """OSError during write_text should be caught, not propagated.

        Currently FAILS because there is no try/except around write_text
        at admin_tasks.py:355-357.
        """
        # Create the parent dir so mkdir succeeds; only the write itself fails.
        state_dir = tmp_path / "prep"
        state_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(
            Path,
            "write_text",
            side_effect=OSError("No space left on device"),
        ):
            # After the fix, this should not raise — the error should be
            # caught and logged as a warning.  Current code lets it propagate.
            try:
                _save_prep_coverage_floor(tmp_path, 50.0)
            except OSError:
                pytest.fail(
                    "OSError propagated from _save_prep_coverage_floor — "
                    "expected it to be caught and logged (issue #6699)"
                )

    @pytest.mark.xfail(reason="Regression for issue #6699 — fix not yet landed", strict=False)
    def test_permission_error_on_write_does_not_propagate(self, tmp_path: Path) -> None:
        """PermissionError (subclass of OSError) should also be caught.

        Currently FAILS for the same reason as the OSError test.
        """
        state_dir = tmp_path / "prep"
        state_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(
            Path,
            "write_text",
            side_effect=PermissionError("Permission denied"),
        ):
            try:
                _save_prep_coverage_floor(tmp_path, 50.0)
            except OSError:
                pytest.fail(
                    "PermissionError propagated from _save_prep_coverage_floor — "
                    "expected it to be caught and logged (issue #6699)"
                )

    @pytest.mark.xfail(reason="Regression for issue #6699 — fix not yet landed", strict=False)
    def test_oserror_on_mkdir_does_not_propagate(self, tmp_path: Path) -> None:
        """OSError during parent mkdir should also be caught.

        Currently FAILS because there is no error handling around the
        mkdir call at admin_tasks.py:354 either.
        """
        # Use a path where the parent can't be created.
        bad_root = tmp_path / "nonexistent"

        with patch.object(
            Path,
            "mkdir",
            side_effect=OSError("Read-only file system"),
        ):
            try:
                _save_prep_coverage_floor(bad_root, 50.0)
            except OSError:
                pytest.fail(
                    "OSError from mkdir propagated from _save_prep_coverage_floor — "
                    "expected it to be caught and logged (issue #6699)"
                )
