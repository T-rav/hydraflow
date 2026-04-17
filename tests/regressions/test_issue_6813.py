"""Regression test for issue #6813.

Bug: In ``admin_tasks.run_compact()``, when iterating ``items.jsonl`` to
remove evicted memory items, a bare ``except Exception`` on line 679 catches
JSON parse failures and unconditionally appends the corrupt raw line to
``kept_lines``.  This means a malformed/corrupt JSONL line is **never
evictable** — it is silently preserved regardless of content, and no warning
is logged.  Over time, corrupt lines accumulate unboundedly while the
eviction log reports success.

The tests below exercise the eviction code path with corrupt JSONL lines
and verify:

1. Corrupt lines are NOT silently kept after eviction (they should be
   dropped or counted separately).
2. The eviction result log distinguishes corrupt lines from legitimately
   kept lines.

Both assertions are RED against the current buggy code and will turn GREEN
once the fix is applied.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))


def _make_item(item_id: str) -> dict:
    """Return a minimal valid memory item dict."""
    return {"id": item_id, "content": f"memory item {item_id}"}


def _item_int_id(item_id: str) -> int:
    """Mirror the hash used in admin_tasks.run_compact() line 676."""
    return abs(hash(str(item_id))) % (10**9)


# ---------------------------------------------------------------------------
# Core bug reproduction
# ---------------------------------------------------------------------------


class TestCorruptJsonlLinesEviction:
    """Corrupt JSONL lines must not be silently preserved during eviction."""

    @pytest.mark.asyncio
    async def test_corrupt_line_is_not_silently_preserved(self, tmp_path: Path) -> None:
        """A corrupt JSON line in items.jsonl must NOT survive eviction
        unconditionally.

        BUG (current): The ``except Exception`` on line 679 of
        ``admin_tasks.py`` catches the ``json.loads()`` failure and
        appends the raw corrupt line to ``kept_lines``, making it
        impossible to ever evict.

        Expected (fixed): Corrupt lines are either dropped during
        eviction or tracked separately — they must not be silently
        kept as if they were valid entries.
        """
        from admin_tasks import run_compact

        # Set up memory directory
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Create a valid item that should be evicted
        valid_item = _make_item("evict-me")
        valid_int_id = _item_int_id("evict-me")

        # Create items.jsonl with one valid line and one corrupt line
        corrupt_line = "{this is not valid json at all"
        items_path = memory_dir / "items.jsonl"
        items_path.write_text(
            json.dumps(valid_item) + "\n" + corrupt_line + "\n",
            encoding="utf-8",
        )

        # Build a minimal config mock pointing at our temp dir
        config = MagicMock()
        config.memory_dir = memory_dir

        # Mock MemoryScorer to trigger eviction of the valid item
        mock_scorer_instance = MagicMock()
        mock_scorer_instance.load_item_scores.return_value = {
            valid_int_id: {"score": 0.05, "appearances": 10},
        }
        mock_scorer_instance.eviction_candidates.return_value = [valid_int_id]
        mock_scorer_instance.classify_for_compaction.return_value = "auto_evict"
        mock_scorer_instance.evict_items.return_value = [valid_int_id]

        with patch("memory_scoring.MemoryScorer", return_value=mock_scorer_instance):
            result = await run_compact(config)

        assert result.success

        # Read back the file after eviction
        remaining = items_path.read_text(encoding="utf-8").strip()

        # The valid item was evicted — it should be gone
        remaining_lines = [ln for ln in remaining.splitlines() if ln.strip()]

        # BUG ASSERTION: The corrupt line should NOT be in the output.
        # Current buggy code keeps it unconditionally via the bare except.
        assert corrupt_line not in remaining_lines, (
            f"BUG #6813: Corrupt JSON line was silently preserved during "
            f"eviction. The bare 'except Exception' on line 679 of "
            f"admin_tasks.py catches json.loads() failures and "
            f"unconditionally appends the raw line to kept_lines. "
            f"Remaining lines: {remaining_lines}"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6813 — fix not yet landed", strict=False)
    async def test_eviction_log_reports_corrupt_lines(self, tmp_path: Path) -> None:
        """The eviction result log must distinguish corrupt lines from
        legitimately kept entries.

        BUG (current): The log message on line 686 says "removed N
        entries, M remain" but the "remain" count includes corrupt
        lines that couldn't even be parsed — operators have no way to
        tell how many lines are actually corrupt.
        """
        from admin_tasks import run_compact

        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Two valid items (one to keep, one to evict) + two corrupt lines
        keep_item = _make_item("keep-me")
        evict_item = _make_item("evict-me")
        evict_int_id = _item_int_id("evict-me")

        items_path = memory_dir / "items.jsonl"
        items_path.write_text(
            "\n".join(
                [
                    json.dumps(keep_item),
                    "{corrupt-line-1",
                    json.dumps(evict_item),
                    "not json either!!!",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        config = MagicMock()
        config.memory_dir = memory_dir

        mock_scorer = MagicMock()
        mock_scorer.load_item_scores.return_value = {
            evict_int_id: {"score": 0.05, "appearances": 10},
        }
        mock_scorer.eviction_candidates.return_value = [evict_int_id]
        mock_scorer.classify_for_compaction.return_value = "auto_evict"
        mock_scorer.evict_items.return_value = [evict_int_id]

        with patch("memory_scoring.MemoryScorer", return_value=mock_scorer):
            result = await run_compact(config)

        # Look for a log entry that mentions corrupt/skipped lines
        log_text = " ".join(result.log)

        assert "corrupt" in log_text.lower() or "skipped" in log_text.lower(), (
            f"BUG #6813: Eviction log does not report corrupt lines. "
            f"The log says 'removed N entries, M remain' but M includes "
            f"corrupt lines that were silently preserved. Operators "
            f"cannot tell which lines are unreadable. "
            f"Actual log: {result.log}"
        )
