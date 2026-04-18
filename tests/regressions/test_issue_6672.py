"""Regression test for issue #6672.

``compact_memory`` in ``admin_tasks.py`` has three robustness gaps:

1. ``items_path.read_text()`` (line 669) has no ``OSError`` guard — a
   permission error or I/O failure raises unhandled instead of returning
   ``TaskResult(success=False, ...)``.

2. The ``except Exception: kept_lines.append(stripped)`` block (lines
   679-680) silently retains malformed JSONL lines with **zero logging**,
   making corruption undetectable.

3. ``items_path.write_text()`` (line 681) has no ``OSError`` guard — a
   write failure after eviction from ``item_scores.json`` leaves state
   inconsistent.

These tests are RED until the fixes land.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from admin_tasks import TaskResult, run_compact

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path) -> MagicMock:
    """Return a minimal mock config whose memory_dir points at *tmp_path*."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    cfg = MagicMock()
    cfg.memory_dir = mem_dir
    return cfg


def _setup_scorer_mock(
    *,
    eviction_candidates: list[int] | None = None,
    evict_return: list[int] | None = None,
):
    """Return a mock MemoryScorer that classifies all candidates as auto_evict."""
    candidates = eviction_candidates or [42]
    scorer = MagicMock()
    scorer.load_item_scores.return_value = {c: {"score": 0.1} for c in candidates}
    scorer.eviction_candidates.return_value = candidates
    scorer.classify_for_compaction.return_value = "auto_evict"
    scorer.evict_items.return_value = (
        evict_return if evict_return is not None else candidates
    )
    return scorer


def _write_items_jsonl(memory_dir: Path, lines: list[str]) -> Path:
    """Write *lines* into ``items.jsonl`` under *memory_dir*."""
    items_path = memory_dir / "items.jsonl"
    items_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return items_path


# ---------------------------------------------------------------------------
# Test 1 — read_text() OSError propagates instead of TaskResult(success=False)
# ---------------------------------------------------------------------------


class TestReadTextOSError:
    """items_path.read_text() failure must be caught and surfaced in TaskResult."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6672 — fix not yet landed", strict=False)
    async def test_read_permission_error_returns_task_result(
        self, tmp_path: Path
    ) -> None:
        """If items.jsonl exists but is unreadable, run_compact should return
        ``TaskResult(success=False)`` (or at minimum not raise).

        Currently the bare ``read_text()`` raises ``PermissionError`` which
        propagates unhandled out of the admin task.
        """
        cfg = _make_config(tmp_path)
        memory_dir = cfg.memory_dir
        items_path = _write_items_jsonl(memory_dir, ['{"id": "a"}'])

        scorer = _setup_scorer_mock(eviction_candidates=[42], evict_return=[42])

        # Make read_text raise PermissionError

        def _raise_permission(*_args, **_kw):
            raise PermissionError(13, "Permission denied", str(items_path))

        with (
            patch("memory_scoring.MemoryScorer", return_value=scorer),
            patch.object(type(items_path), "read_text", _raise_permission),
        ):
            # BUG: This should return TaskResult(success=False) but instead raises
            result = await run_compact(cfg)

        # The function should handle the error gracefully
        assert isinstance(result, TaskResult)
        # And it should signal the failure somehow — either success=False or a warning
        has_failure_signal = not result.success or any(
            "error" in w.lower() or "permission" in w.lower() for w in result.warnings
        )
        assert has_failure_signal, (
            f"PermissionError on read_text() was swallowed with no signal. "
            f"success={result.success}, warnings={result.warnings}"
        )


# ---------------------------------------------------------------------------
# Test 2 — malformed JSONL lines are kept silently with no logging
# ---------------------------------------------------------------------------


class TestMalformedJsonlSilent:
    """Malformed JSONL lines must emit a logger.warning, not be silently kept."""

    @pytest.mark.asyncio
    async def test_malformed_jsonl_emits_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If items.jsonl contains a malformed line, compact_memory should log
        a warning so operators can detect corruption.

        Currently the ``except Exception`` block on lines 679-680 silently
        appends the broken line with zero logging.
        """
        cfg = _make_config(tmp_path)
        memory_dir = cfg.memory_dir

        # Mix of valid and malformed lines
        lines = [
            '{"id": "good-item-1", "content": "hello"}',
            "THIS IS NOT JSON AT ALL",
            '{"id": "good-item-2", "content": "world"}',
            '{malformed json "unclosed',
        ]
        _write_items_jsonl(memory_dir, lines)

        # Use a real item ID that won't collide with the eviction set so
        # lines are *kept* (the bug is about kept malformed lines, not evicted ones)
        scorer = _setup_scorer_mock(eviction_candidates=[99999], evict_return=[99999])

        with (
            patch("memory_scoring.MemoryScorer", return_value=scorer),
            caplog.at_level(logging.WARNING),
        ):
            result = await run_compact(cfg)

        assert result.success  # compaction itself should succeed

        # The malformed lines should have triggered at least one warning log
        all_log_text = caplog.text.lower()
        malformed_warned = (
            "malformed" in all_log_text
            or "skip" in all_log_text
            or "invalid" in all_log_text
            or "parse" in all_log_text
            or "json" in all_log_text
        )
        assert malformed_warned, (
            f"Malformed JSONL lines were silently retained with no logging. "
            f"Captured log: {caplog.text!r}"
        )


# ---------------------------------------------------------------------------
# Test 3 — write_text() OSError propagates instead of TaskResult
# ---------------------------------------------------------------------------


class TestWriteTextOSError:
    """items_path.write_text() failure must be caught and surfaced."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6672 — fix not yet landed", strict=False)
    async def test_write_permission_error_returns_task_result(
        self, tmp_path: Path
    ) -> None:
        """If writing back the filtered items.jsonl fails (e.g. disk full,
        permission denied), run_compact should catch it and return
        TaskResult with a warning — not raise.

        Currently the bare ``write_text()`` raises unhandled.
        """
        cfg = _make_config(tmp_path)
        memory_dir = cfg.memory_dir
        _write_items_jsonl(memory_dir, ['{"id": "a"}', '{"id": "b"}'])

        scorer = _setup_scorer_mock(eviction_candidates=[42], evict_return=[42])

        original_write = Path.write_text

        call_count = 0

        def _write_interceptor(self_path, *a, **kw):
            nonlocal call_count
            if self_path.name == "items.jsonl":
                call_count += 1
                # Only block the write-back, not the initial setup
                if call_count > 0:
                    raise OSError(28, "No space left on device")
            return original_write(self_path, *a, **kw)

        with (
            patch("memory_scoring.MemoryScorer", return_value=scorer),
            patch.object(Path, "write_text", _write_interceptor),
        ):
            # BUG: This should return TaskResult with a warning but instead raises
            result = await run_compact(cfg)

        assert isinstance(result, TaskResult)
        has_failure_signal = not result.success or any(
            "error" in w.lower() or "write" in w.lower() or "space" in w.lower()
            for w in result.warnings
        )
        assert has_failure_signal, (
            f"OSError on write_text() was swallowed with no signal. "
            f"success={result.success}, warnings={result.warnings}"
        )
