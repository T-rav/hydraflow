"""Regression test for issue #6443.

DoltBackend.save_state has no error handling on the disk write at line 145.
When ``sql_file.write_text(sql)`` raises an ``OSError`` (disk full, permission
denied), the exception propagates with no ``logger.error`` call, so the state
persistence failure is invisible in logs.

This test confirms that an OSError during the temp-file write is logged at
ERROR level with exc_info before the exception propagates.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from dolt_backend import DoltBackend  # noqa: E402


def _make_backend(tmp_path: Path) -> DoltBackend:
    """Build a DoltBackend without requiring the real dolt CLI."""
    with (
        patch("shutil.which", return_value="/usr/local/bin/dolt"),
        patch.object(DoltBackend, "_ensure_repo"),
    ):
        backend = DoltBackend(tmp_path)
    return backend


class TestIssue6443SaveStateDiskWriteErrorLogged:
    """save_state must log an error when the temp SQL file write fails."""

    def test_oserror_on_write_text_is_logged_before_propagating(
        self, tmp_path: Path
    ) -> None:
        """When write_text raises OSError (disk full / permission denied),
        save_state must emit a logger.error with exc_info before the
        exception propagates.

        BUG: Currently no except block exists, so the OSError propagates
        with zero log output — the state loss is invisible to operators.
        """
        backend = _make_backend(tmp_path)

        # Arrange — make write_text raise OSError
        disk_error = OSError(28, "No space left on device")
        original_write_text = Path.write_text

        def _failing_write_text(self_path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self_path.name == ".tmp_state.sql":
                raise disk_error
            return original_write_text(self_path, *args, **kwargs)

        # Act — call save_state with the failing write
        logger = logging.getLogger("hydraflow.dolt")
        records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = records.append  # type: ignore[assignment]
        logger.addHandler(handler)
        original_level = logger.level
        logger.setLevel(logging.DEBUG)

        try:
            with patch.object(Path, "write_text", _failing_write_text):
                with pytest.raises(OSError, match="No space left on device"):
                    backend.save_state('{"test": true}')
        finally:
            logger.removeHandler(handler)
            logger.setLevel(original_level)

        # Assert — an ERROR log was emitted for the disk write failure
        errors = [r for r in records if r.levelno >= logging.ERROR]
        assert len(errors) >= 1, (
            "Expected at least 1 ERROR log for the OSError during state write, "
            f"but got {len(errors)}. The disk write failure is silently lost — "
            "operators have no log evidence that state persistence failed."
        )

        # Assert — the log includes exc_info so the traceback is visible
        err_record = errors[0]
        assert err_record.exc_info is not None, (
            "ERROR log for state write failure must include exc_info "
            "so the full traceback is visible in production logs."
        )
        assert isinstance(err_record.exc_info[1], OSError), (
            "exc_info must contain the original OSError instance"
        )
