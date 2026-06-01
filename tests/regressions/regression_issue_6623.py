"""Regression test for issue #6623.

Bug: ``append_jsonl`` in ``file_util.py`` does not handle ``OSError`` from
``write``/``flush``/``fsync``.  When disk-full or similar I/O failures occur,
the ``OSError`` propagates unhandled to the caller, silently crashing the
state-write path.  The expected behaviour (after fix) is to catch and log the
error so callers are not surprised by an unhandled exception from a
"best-effort durability" helper.

Additionally, ``append_jsonl`` provides no concurrency protection — concurrent
callers can interleave partial JSON lines, corrupting the file.

These tests assert the *correct* post-fix behaviour and are therefore RED
against the current (buggy) code.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure source modules are importable from src/ layout.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from file_util import append_jsonl  # noqa: E402


class TestAppendJsonlOSErrorHandling:
    """append_jsonl must catch OSError from fsync and log it, not propagate."""

    @pytest.mark.xfail(reason="Regression for issue #6623 — fix not yet landed", strict=False)
    def test_fsync_oserror_is_caught_not_propagated(self, tmp_path: Path) -> None:
        """When os.fsync raises OSError (e.g. disk full), append_jsonl should
        catch it and log rather than letting the exception propagate.

        Current behaviour (bug): OSError propagates to the caller.
        Expected behaviour (fix): OSError is caught and logged.
        """
        target = tmp_path / "log.jsonl"
        with patch(
            "file_util.os.fsync", side_effect=OSError("No space left on device")
        ):
            # After fix, this should NOT raise — it should catch and log.
            # The bug is that it DOES raise, so this test is RED.
            append_jsonl(target, '{"event":"test"}')

    @pytest.mark.xfail(reason="Regression for issue #6623 — fix not yet landed", strict=False)
    def test_fsync_oserror_is_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When os.fsync raises OSError, the error must appear in logs."""
        target = tmp_path / "log.jsonl"
        with (
            patch("file_util.os.fsync", side_effect=OSError("I/O error")),
            caplog.at_level(logging.WARNING, logger="hydraflow.file_util"),
        ):
            # After fix this should not raise; it should log.
            append_jsonl(target, '{"event":"logged"}')

        assert any("I/O error" in rec.message for rec in caplog.records), (
            "Expected a log record mentioning the OSError, but none found"
        )

    @pytest.mark.xfail(reason="Regression for issue #6623 — fix not yet landed", strict=False)
    def test_write_oserror_is_caught_not_propagated(self, tmp_path: Path) -> None:
        """When the write() call itself raises OSError, append_jsonl should
        catch it rather than propagating."""
        target = tmp_path / "log.jsonl"
        # Patch builtins open to return a file whose write() raises
        real_open = open

        def _broken_open(path, mode="r", **kw):  # noqa: ANN001, ANN003
            f = real_open(path, mode, **kw)

            def _bad_write(data: str) -> int:
                raise OSError("disk full")

            f.write = _bad_write  # type: ignore[method-assign]
            return f

        with patch("builtins.open", side_effect=_broken_open):
            # After fix, should not raise. Currently raises.
            append_jsonl(target, '{"event":"boom"}')

    @pytest.mark.xfail(reason="Regression for issue #6623 — fix not yet landed", strict=False)
    def test_data_written_before_fsync_failure_is_preserved(
        self, tmp_path: Path
    ) -> None:
        """Even when fsync fails, the data should have been flushed to the
        kernel buffer and the file should contain the line (best effort)."""
        target = tmp_path / "log.jsonl"
        with patch("file_util.os.fsync", side_effect=OSError("fsync failed")):
            # After fix this should not raise
            append_jsonl(target, '{"survived":true}')

        # The data was written before fsync was called, so it should exist
        assert target.exists()
        assert '{"survived":true}' in target.read_text()
