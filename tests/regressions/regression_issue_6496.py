"""Regression test for issue #6496.

Bug: broad ``except Exception`` blocks in ``trace_collector.py`` and
``trace_rollup.py`` silently swallow programming errors (AttributeError,
TypeError in trace serialisation logic) and omit diagnostic information.

1. ``TraceCollector.record()`` catches all exceptions including
   ``AttributeError`` / ``AssertionError`` — programming bugs that should
   propagate so they are caught by tests and fixed.

2. ``TraceCollector.finalize()`` catches all exceptions — a disk-full
   or programming error returns ``None``, indistinguishable from an
   empty trace.  No Sentry breadcrumb is emitted.

3. ``trace_rollup.write_phase_rollup()`` logs a warning when skipping a
   malformed subprocess trace, but omits ``exc_info=True`` so the root
   cause is invisible in logs.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from trace_collector import TraceCollector  # noqa: E402
from trace_rollup import write_phase_rollup  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(data_root: Path) -> MagicMock:
    config = MagicMock()
    config.data_root = data_root
    config.factory_metrics_path = data_root / "factory_metrics.jsonl"
    return config


def _make_collector(tmp_path: Path, **overrides) -> TraceCollector:
    defaults = {
        "issue_number": 42,
        "phase": "implement",
        "source": "implementer",
        "subprocess_idx": 0,
        "run_id": 1,
        "config": _make_config(tmp_path),
        "event_bus": None,
    }
    defaults.update(overrides)
    return TraceCollector(**defaults)


# ---------------------------------------------------------------------------
# 1. record() must not swallow programming errors (AttributeError)
# ---------------------------------------------------------------------------


class TestRecordDoesNotMaskProgrammingErrors:
    """record() should let AttributeError and AssertionError propagate.

    The current code catches ``Exception`` at line 85, masking programming
    bugs in the trace parse logic.  The fix narrows the except clause to
    ``(ValueError, KeyError, TypeError)`` so that structural errors in
    incoming JSON are handled gracefully while true bugs surface.
    """

    @pytest.mark.xfail(reason="Regression for issue #6496 — fix not yet landed", strict=False)
    def test_record_propagates_attribute_error(self, tmp_path: Path) -> None:
        """AttributeError inside _record_inner must not be silently caught."""
        c = _make_collector(tmp_path)

        def buggy_record_inner(raw_line: str) -> None:
            # Simulate a programming bug inside the trace parse logic
            raise AttributeError("obj has no attribute 'nonexistent_field'")

        c._record_inner = buggy_record_inner  # type: ignore[assignment]

        with pytest.raises(AttributeError, match="nonexistent_field"):
            c.record('{"type": "assistant"}')

    @pytest.mark.xfail(reason="Regression for issue #6496 — fix not yet landed", strict=False)
    def test_record_propagates_assertion_error(self, tmp_path: Path) -> None:
        """AssertionError inside _record_inner must not be silently caught."""
        c = _make_collector(tmp_path)

        def buggy_record_inner(raw_line: str) -> None:
            raise AssertionError("invariant violated")

        c._record_inner = buggy_record_inner  # type: ignore[assignment]

        with pytest.raises(AssertionError, match="invariant violated"):
            c.record('{"type": "assistant"}')

    def test_record_still_handles_value_error(self, tmp_path: Path) -> None:
        """ValueError from malformed data should still be caught gracefully."""
        c = _make_collector(tmp_path)

        def bad_data_record_inner(raw_line: str) -> None:
            raise ValueError("unexpected value in trace data")

        c._record_inner = bad_data_record_inner  # type: ignore[assignment]

        # Should NOT raise — ValueError is expected from bad input data
        c.record('{"type": "assistant"}')


# ---------------------------------------------------------------------------
# 2. finalize() must not swallow programming errors
# ---------------------------------------------------------------------------


class TestFinalizeDoesNotMaskProgrammingErrors:
    """finalize() should let AttributeError propagate rather than returning
    None (which is indistinguishable from an empty trace).

    The current code catches ``Exception`` at line 313.  When finalize()
    fails silently, factory_metrics sees a missing data point.
    """

    @pytest.mark.xfail(reason="Regression for issue #6496 — fix not yet landed", strict=False)
    def test_finalize_propagates_attribute_error(self, tmp_path: Path) -> None:
        """AttributeError in _finalize_inner must propagate, not return None."""
        c = _make_collector(tmp_path)
        # Ensure collector has data so _finalize_inner would normally run
        c.inference_count = 1

        def buggy_finalize_inner(*, success: bool) -> None:
            raise AttributeError("bug in trace serialisation")

        c._finalize_inner = buggy_finalize_inner  # type: ignore[assignment]

        with pytest.raises(AttributeError, match="bug in trace serialisation"):
            c.finalize(success=True)


# ---------------------------------------------------------------------------
# 3. trace_rollup skipped-trace warning must include exc_info
# ---------------------------------------------------------------------------


class TestTraceRollupExcInfo:
    """write_phase_rollup() must include exc_info=True when logging a
    skipped malformed trace, so operators can diagnose the root cause.

    The current code at line 51-52 logs the filename but not the exception.
    """

    @pytest.mark.xfail(reason="Regression for issue #6496 — fix not yet landed", strict=False)
    def test_skipped_trace_warning_includes_exc_info(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Malformed-trace warning must carry exc_info so the parse error is visible."""
        run_dir = tmp_path / "traces" / "42" / "implement" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "subprocess-0.json").write_text(
            "this is not valid json at all", encoding="utf-8"
        )

        config = _make_config(tmp_path)

        with caplog.at_level(logging.WARNING, logger="hydraflow.trace_rollup"):
            write_phase_rollup(
                config=config, issue_number=42, phase="implement", run_id=1
            )

        skip_records = [
            r for r in caplog.records if "Skipping malformed" in r.getMessage()
        ]
        assert len(skip_records) == 1, (
            f"Expected exactly 1 'Skipping malformed' warning, got {len(skip_records)}"
        )
        record = skip_records[0]
        # exc_info must be a 3-tuple with a real exception type, not None
        assert record.exc_info is not None, (
            "Warning for skipped trace must include exc_info=True "
            "so the root cause is visible in logs"
        )
        assert record.exc_info[0] is not None, (
            "exc_info tuple must contain a real exception type, not (None, None, None)"
        )
