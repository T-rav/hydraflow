"""Regression test for issue #6920.

``MemoryScorer.load_item_scores`` calls ``json.loads(self._scores_file.read_text(...))``
with no ``OSError`` or ``json.JSONDecodeError`` guard.  A corrupt scores file
(truncated write, disk error) or a permission-denied file causes an uncaught
exception that propagates through the health monitor loop or memory sync cycle.

Similarly, ``_save_item_scores`` uses ``write_text`` with no ``OSError`` guard,
so a disk-full condition crashes every caller.

These tests will fail (RED) until both methods are wrapped in appropriate
try/except blocks that return ``{}`` (load) or silently log (save) instead
of propagating the exception.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from memory_scoring import MemoryScorer  # noqa: E402

# ---------------------------------------------------------------------------
# Test 1 — load_item_scores should return {} on corrupt JSON, not raise
# ---------------------------------------------------------------------------


class TestLoadItemScoresCorruptJSON:
    """load_item_scores must gracefully handle a corrupt scores file."""

    @pytest.mark.xfail(reason="Regression for issue #6920 — fix not yet landed", strict=False)
    def test_corrupt_json_returns_empty_dict(self, tmp_path: Path) -> None:
        """If item_scores.json contains invalid JSON (e.g. truncated write),
        load_item_scores should return {} instead of raising JSONDecodeError.

        Fails until load_item_scores catches json.JSONDecodeError.
        """
        mem_dir = tmp_path / "mem"
        mem_dir.mkdir(parents=True)
        scores_file = mem_dir / "item_scores.json"
        scores_file.write_text('{"1": {"score": 0.8, "appe', encoding="utf-8")

        scorer = MemoryScorer(mem_dir)

        # Current code raises json.JSONDecodeError here.
        # After fix, this should return {} gracefully.
        result = scorer.load_item_scores()
        assert result == {}, (
            "load_item_scores should return {} on corrupt JSON, "
            f"but returned {result!r} (issue #6920)"
        )

    @pytest.mark.xfail(reason="Regression for issue #6920 — fix not yet landed", strict=False)
    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """An empty scores file (e.g. from a truncated write that wrote 0 bytes)
        should also be handled gracefully.

        Fails until load_item_scores catches json.JSONDecodeError.
        """
        mem_dir = tmp_path / "mem"
        mem_dir.mkdir(parents=True)
        scores_file = mem_dir / "item_scores.json"
        scores_file.write_text("", encoding="utf-8")

        scorer = MemoryScorer(mem_dir)

        result = scorer.load_item_scores()
        assert result == {}, (
            "load_item_scores should return {} on empty file, "
            f"but returned {result!r} (issue #6920)"
        )


# ---------------------------------------------------------------------------
# Test 2 — load_item_scores should return {} on OSError, not raise
# ---------------------------------------------------------------------------


class TestLoadItemScoresOSError:
    """load_item_scores must gracefully handle an unreadable scores file."""

    @pytest.mark.xfail(reason="Regression for issue #6920 — fix not yet landed", strict=False)
    def test_permission_denied_returns_empty_dict(self, tmp_path: Path) -> None:
        """If item_scores.json exists but is unreadable (permission denied),
        load_item_scores should return {} instead of raising OSError.

        Fails until load_item_scores catches OSError.
        """
        mem_dir = tmp_path / "mem"
        mem_dir.mkdir(parents=True)
        scores_file = mem_dir / "item_scores.json"
        scores_file.write_text(
            json.dumps({"1": {"score": 0.5, "appearances": 1, "trail": []}}),
            encoding="utf-8",
        )
        # Remove read permission
        scores_file.chmod(0o000)

        scorer = MemoryScorer(mem_dir)

        try:
            result = scorer.load_item_scores()
        finally:
            # Restore permissions so tmp_path cleanup works
            scores_file.chmod(0o644)

        assert result == {}, (
            "load_item_scores should return {} on permission denied, "
            f"but returned {result!r} (issue #6920)"
        )


# ---------------------------------------------------------------------------
# Test 3 — _save_item_scores should not propagate OSError
# ---------------------------------------------------------------------------


class TestSaveItemScoresOSError:
    """_save_item_scores must not crash callers on write failure."""

    @pytest.mark.xfail(reason="Regression for issue #6920 — fix not yet landed", strict=False)
    def test_readonly_dir_does_not_raise(self, tmp_path: Path) -> None:
        """If the directory is read-only (disk full simulation),
        _save_item_scores should log a warning instead of raising OSError.

        Fails until _save_item_scores catches OSError.
        """
        mem_dir = tmp_path / "mem"
        mem_dir.mkdir(parents=True)

        scorer = MemoryScorer(mem_dir)
        scores = {
            1: {"score": 0.5, "appearances": 1, "trail": [], "condensed_summary": ""}
        }

        # Make directory read-only to prevent writes
        mem_dir.chmod(0o555)

        try:
            # Current code raises OSError (PermissionError) here.
            # After fix, this should log a warning and return silently.
            scorer._save_item_scores(scores)
        except OSError:
            pytest.fail(
                "_save_item_scores raised OSError on read-only directory "
                "instead of logging a warning (issue #6920)"
            )
        finally:
            # Restore permissions so tmp_path cleanup works
            mem_dir.chmod(0o755)
