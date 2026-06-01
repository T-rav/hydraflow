"""Regression test for issue #6907.

Bug: ``IssueCache.record()`` is documented as best-effort — "a broken cache
must never break the domain layer" — but it only catches ``OSError``.
``CacheRecord.model_dump_json()`` raises
``pydantic_core.PydanticSerializationError`` (a ``ValueError`` subclass, NOT
an ``OSError`` subclass) when the payload contains a non-serialisable value.
The exception escapes the handler and propagates uncaught into every phase
that calls ``record_plan_stored``, ``record_review_stored``, etc.

Expected behaviour after fix:
  - ``IssueCache.record()`` must never raise, regardless of the failure mode
    of ``model_dump_json()``.
  - Serialization failures are logged at warning level and silently swallowed,
    matching the existing ``OSError`` handling.

These tests intentionally assert the *correct* behaviour, so they are RED
against the current (buggy) code.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from issue_cache import CacheRecord, CacheRecordKind, IssueCache


class _NotSerializable:
    """Object that pydantic cannot JSON-serialize."""


class TestRecordBestEffortContract:
    """Issue #6907 — PydanticSerializationError escapes the OSError guard."""

    @pytest.mark.xfail(reason="Regression for issue #6907 — fix not yet landed", strict=False)
    def test_record_does_not_raise_on_serialization_error(self, tmp_path: Path) -> None:
        """``record()`` must swallow serialization failures, not just IO errors.

        Currently, a payload containing a non-serialisable value causes
        ``model_dump_json()`` to raise ``PydanticSerializationError``
        (a ``ValueError`` subclass).  The ``except OSError`` handler does
        not catch it, violating the best-effort contract and crashing the
        calling phase mid-run.
        """
        cache = IssueCache(tmp_path, enabled=True)
        bad_record = CacheRecord(
            issue_id=42,
            kind=CacheRecordKind.FETCH,
            payload={"bad_value": _NotSerializable()},
        )

        # The best-effort contract says this must never raise.
        # Bug: PydanticSerializationError propagates uncaught.
        try:
            cache.record(bad_record)
        except Exception as exc:
            pytest.fail(
                f"IssueCache.record() raised {type(exc).__name__}: {exc}. "
                f"Bug #6907: the except OSError handler does not catch "
                f"PydanticSerializationError from model_dump_json(). "
                f"A broken cache must never break the domain layer."
            )

    @pytest.mark.xfail(reason="Regression for issue #6907 — fix not yet landed", strict=False)
    def test_record_fetch_does_not_raise_on_serialization_error(
        self, tmp_path: Path
    ) -> None:
        """``record_fetch()`` — a convenience wrapper — must also be safe."""
        cache = IssueCache(tmp_path, enabled=True)

        try:
            cache.record_fetch(issue_id=99, payload={"obj": _NotSerializable()})
        except Exception as exc:
            pytest.fail(
                f"IssueCache.record_fetch() raised {type(exc).__name__}: {exc}. "
                f"Bug #6907: serialization error escapes best-effort guard."
            )

    @pytest.mark.xfail(reason="Regression for issue #6907 — fix not yet landed", strict=False)
    def test_record_plan_stored_does_not_raise_on_serialization_error(
        self, tmp_path: Path
    ) -> None:
        """``record_plan_stored()`` — versioned writer — must also be safe."""
        cache = IssueCache(tmp_path, enabled=True)

        try:
            cache.record_plan_stored(
                issue_id=7,
                plan_text="a plan",
                findings=[{"nested_bad": _NotSerializable()}],
            )
        except Exception as exc:
            pytest.fail(
                f"IssueCache.record_plan_stored() raised {type(exc).__name__}: "
                f"{exc}. Bug #6907: serialization error escapes best-effort guard."
            )

    def test_good_records_still_written_after_serialization_failure(
        self, tmp_path: Path
    ) -> None:
        """A serialization failure must not corrupt the cache for subsequent
        writes.  After swallowing the error, the next valid ``record()`` call
        must succeed normally.
        """
        cache = IssueCache(tmp_path, enabled=True)

        bad_record = CacheRecord(
            issue_id=42,
            kind=CacheRecordKind.FETCH,
            payload={"bad_value": _NotSerializable()},
        )

        # First call — should fail silently.
        try:
            cache.record(bad_record)
        except Exception:
            pass  # Even if the bug is present, continue to the second assertion.

        # Second call — a normal payload must succeed.
        good_record = CacheRecord(
            issue_id=42,
            kind=CacheRecordKind.FETCH,
            payload={"title": "a valid issue"},
        )
        cache.record(good_record)

        history = cache.read_history(42)
        assert len(history) == 1, (
            f"Expected exactly 1 record in history after a failed + successful "
            f"write, but got {len(history)}."
        )
        assert history[0].payload["title"] == "a valid issue"
