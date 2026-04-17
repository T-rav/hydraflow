"""Regression test for issue #6556.

Bug: ``write_phase_rollup`` writes ``summary.json`` and an atomic ``latest``
pointer (via ``latest.tmp`` + ``Path.replace``) with no surrounding
``try/except``.  When ``Path.replace`` raises ``OSError`` (e.g. disk full,
permissions), the error propagates to the caller and ``latest.tmp`` is left
orphaned on disk.  Repeated failures accumulate these orphan files.

Expected behaviour after fix:
  - ``write_phase_rollup`` catches ``OSError`` during the write/rename,
    logs it, and ensures ``latest.tmp`` is deleted in the cleanup path.
  - The function returns ``None`` on such failures rather than propagating.

These tests assert the *correct* behaviour, so they are RED against the
current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from models import SubprocessTrace, TraceTokenStats, TraceToolProfile  # noqa: E402
from trace_rollup import write_phase_rollup  # noqa: E402


def _make_subprocess_trace(
    *, issue_number: int = 1, phase: str = "plan", run_id: int = 1
) -> SubprocessTrace:
    """Build a minimal valid SubprocessTrace for testing."""
    return SubprocessTrace(
        issue_number=issue_number,
        phase=phase,
        source="test",
        run_id=run_id,
        subprocess_idx=0,
        backend="claude",
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:01:00+00:00",
        success=True,
        tokens=TraceTokenStats(
            prompt_tokens=100,
            completion_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            cache_hit_rate=0.0,
        ),
        tools=TraceToolProfile(
            tool_counts={"Read": 1},
            tool_errors={},
            total_invocations=1,
        ),
    )


def _setup_trace_dir(
    tmp_path: Path, *, issue_number: int = 1, phase: str = "plan", run_id: int = 1
) -> Path:
    """Create the run directory with a valid subprocess trace file."""
    run_dir = tmp_path / "traces" / str(issue_number) / phase / f"run-{run_id}"
    run_dir.mkdir(parents=True)
    trace = _make_subprocess_trace(
        issue_number=issue_number, phase=phase, run_id=run_id
    )
    (run_dir / "subprocess-0.json").write_text(
        trace.model_dump_json(indent=2), encoding="utf-8"
    )
    return run_dir


def _make_config(tmp_path: Path) -> MagicMock:
    """Create a mock config whose data_root points at tmp_path."""
    config = MagicMock()
    config.data_root = tmp_path
    config.factory_metrics_path = tmp_path / "diagnostics" / "factory_metrics.jsonl"
    return config


class TestLatestTmpOrphanOnReplaceFailure:
    """Issue #6556 — ``latest.tmp`` must not be left on disk when
    ``Path.replace`` raises ``OSError``.
    """

    def test_latest_tmp_cleaned_up_when_replace_raises(self, tmp_path: Path) -> None:
        """When ``latest_tmp.replace(latest_path)`` raises ``OSError``,
        ``latest.tmp`` must be deleted and the function should return
        ``None`` (not propagate the error).

        Currently FAILS (RED) because:
        1. The ``OSError`` propagates uncaught from ``write_phase_rollup``.
        2. ``latest.tmp`` remains on disk as an orphan.
        """
        # Arrange
        run_dir = _setup_trace_dir(tmp_path)
        config = _make_config(tmp_path)
        phase_dir = run_dir.parent  # .../traces/1/plan/

        original_replace = Path.replace

        def _failing_replace(self: Path, target: object) -> Path:
            if self.name == "latest.tmp":
                raise OSError("Simulated disk error on atomic rename")
            return original_replace(self, target)  # type: ignore[arg-type]

        # Act
        with patch.object(Path, "replace", _failing_replace):
            # After the fix, write_phase_rollup should catch the OSError
            # and return None.  Before the fix, it propagates.
            try:
                write_phase_rollup(
                    config=config,
                    issue_number=1,
                    phase="plan",
                    run_id=1,
                )
            except OSError:
                # Before the fix the error propagates — set result to
                # sentinel so assertions below still run.
                pass  # type: ignore[assignment]

        # Assert — latest.tmp must not be left as an orphan
        latest_tmp = phase_dir / "latest.tmp"
        assert not latest_tmp.exists(), (
            f"latest.tmp was left orphaned at {latest_tmp} — "
            "write_phase_rollup must clean up on OSError"
        )

    def test_returns_none_when_replace_raises(self, tmp_path: Path) -> None:
        """After the fix, ``write_phase_rollup`` should return ``None``
        when the atomic rename fails, rather than propagating ``OSError``.

        Currently FAILS (RED) because the ``OSError`` propagates.
        """
        # Arrange
        _setup_trace_dir(tmp_path)
        config = _make_config(tmp_path)

        original_replace = Path.replace

        def _failing_replace(self: Path, target: object) -> Path:
            if self.name == "latest.tmp":
                raise OSError("Simulated disk error on atomic rename")
            return original_replace(self, target)  # type: ignore[arg-type]

        # Act & Assert — should NOT raise
        with patch.object(Path, "replace", _failing_replace):
            result = write_phase_rollup(
                config=config,
                issue_number=1,
                phase="plan",
                run_id=1,
            )

        assert result is None, (
            f"Expected None when atomic rename fails, got {type(result).__name__}"
        )


class TestLatestTmpOrphanOnWriteFailure:
    """Issue #6556 — ``latest.tmp`` must not be left on disk when
    ``write_text`` for the tmp file raises ``OSError``.
    """

    def test_summary_write_failure_returns_none(self, tmp_path: Path) -> None:
        """When ``summary_path.write_text`` raises ``OSError``,
        ``write_phase_rollup`` should catch it and return ``None``.

        Currently FAILS (RED) because the ``OSError`` propagates.
        """
        # Arrange
        _setup_trace_dir(tmp_path)
        config = _make_config(tmp_path)

        original_write_text = Path.write_text

        def _failing_write(
            self: Path, data: str, *args: object, **kwargs: object
        ) -> None:
            if self.name == "summary.json":
                raise OSError("Simulated disk-full on summary write")
            return original_write_text(self, data, *args, **kwargs)  # type: ignore[arg-type]

        # Act & Assert — should NOT raise
        with patch.object(Path, "write_text", _failing_write):
            result = write_phase_rollup(
                config=config,
                issue_number=1,
                phase="plan",
                run_id=1,
            )

        assert result is None, (
            f"Expected None when summary.json write fails, got {type(result).__name__}"
        )

    def test_no_latest_tmp_left_when_latest_write_text_raises(
        self, tmp_path: Path
    ) -> None:
        """When ``latest_tmp.write_text`` raises ``OSError``,
        no ``latest.tmp`` orphan should remain.

        Currently FAILS (RED) because there is no cleanup logic.
        """
        # Arrange
        run_dir = _setup_trace_dir(tmp_path)
        config = _make_config(tmp_path)
        phase_dir = run_dir.parent

        original_write_text = Path.write_text

        def _failing_latest_write(
            self: Path, data: str, *args: object, **kwargs: object
        ) -> None:
            if self.name == "latest.tmp":
                # Simulate: file is created but write fails partway
                self.touch()
                raise OSError("Simulated disk-full on latest.tmp write")
            return original_write_text(self, data, *args, **kwargs)  # type: ignore[arg-type]

        # Act
        with patch.object(Path, "write_text", _failing_latest_write):
            try:
                write_phase_rollup(
                    config=config,
                    issue_number=1,
                    phase="plan",
                    run_id=1,
                )
            except OSError:
                pass  # Expected before fix

        # Assert
        latest_tmp = phase_dir / "latest.tmp"
        assert not latest_tmp.exists(), (
            f"latest.tmp was left orphaned at {latest_tmp} — "
            "write_phase_rollup must clean up on OSError"
        )
