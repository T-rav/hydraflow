"""Tests for Monocle trace file harvester."""

from __future__ import annotations

import json
from pathlib import Path

from trace_harvester import harvest_traces


class TestHarvestTraces:
    def _write_trace(self, monocle_dir: Path, name: str = "trace_01.json") -> Path:
        """Write a minimal trace file and return its path."""
        monocle_dir.mkdir(parents=True, exist_ok=True)
        path = monocle_dir / f"monocle_trace_claude-cli_{name}"
        path.write_text(
            json.dumps([{"name": "workflow", "context": {"trace_id": "0xabc"}}])
        )
        return path

    def test_harvests_trace_files(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        self._write_trace(worktree / ".monocle")
        dest = tmp_path / "data"

        count = harvest_traces(
            worktree, issue_number=42, phase="implement", data_path=dest
        )

        assert count == 1
        raw_dir = dest / "traces" / "42" / "implement" / "raw"
        assert raw_dir.exists()
        files = list(raw_dir.glob("*.json"))
        assert len(files) == 1

    def test_harvests_multiple_files(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        self._write_trace(worktree / ".monocle", "trace_01.json")
        self._write_trace(worktree / ".monocle", "trace_02.json")
        dest = tmp_path / "data"

        count = harvest_traces(
            worktree, issue_number=10, phase="review", data_path=dest
        )

        assert count == 2

    def test_no_monocle_dir_returns_zero(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        dest = tmp_path / "data"

        count = harvest_traces(worktree, issue_number=1, phase="plan", data_path=dest)

        assert count == 0

    def test_empty_monocle_dir_returns_zero(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        (worktree / ".monocle").mkdir(parents=True)
        dest = tmp_path / "data"

        count = harvest_traces(worktree, issue_number=1, phase="plan", data_path=dest)

        assert count == 0

    def test_preserves_original_filenames(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        self._write_trace(worktree / ".monocle", "session_abc123.json")
        dest = tmp_path / "data"

        harvest_traces(worktree, issue_number=7, phase="implement", data_path=dest)

        raw_dir = dest / "traces" / "7" / "implement" / "raw"
        names = [f.name for f in raw_dir.iterdir()]
        assert "monocle_trace_claude-cli_session_abc123.json" in names

    def test_file_content_preserved(self, tmp_path: Path) -> None:
        worktree = tmp_path / "worktree"
        trace_path = self._write_trace(worktree / ".monocle")
        original_content = trace_path.read_text()
        dest = tmp_path / "data"

        harvest_traces(worktree, issue_number=42, phase="implement", data_path=dest)

        raw_dir = dest / "traces" / "42" / "implement" / "raw"
        copied = next(raw_dir.iterdir())
        assert copied.read_text() == original_content
