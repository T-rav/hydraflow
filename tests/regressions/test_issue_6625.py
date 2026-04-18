"""Regression test for issue #6625.

Bug claim: HindsightWAL.load() catches (ValueError, KeyError) but not
pydantic.ValidationError, so a WAL entry with invalid schema crashes load().

Finding: In Pydantic 2.12.5, pydantic.ValidationError inherits from ValueError,
so the existing except clause already catches it. The bug as described does NOT
exist with the current Pydantic version.

These tests document the current (correct) behavior:
- load() gracefully skips WAL entries with missing required fields
- load() gracefully skips WAL entries with wrong field types
- load() gracefully skips WAL entries with completely wrong schema
"""

from __future__ import annotations

import json
from pathlib import Path

import pydantic

from hindsight_wal import HindsightWAL


class TestIssue6625ValidationErrorHandling:
    """WAL.load() should skip entries that fail pydantic validation."""

    def test_load_skips_entry_missing_required_bank_field(self, tmp_path: Path) -> None:
        """A WAL line with valid JSON but missing the required 'bank' field
        should be skipped, not crash load().

        This is the core scenario from issue #6625. With Pydantic 2.12.5,
        ValidationError inherits from ValueError so the current except clause
        catches it. If Pydantic ever removes that inheritance, this test will
        catch the regression.
        """
        wal_path = tmp_path / "wal.jsonl"
        good = json.dumps({"bank": "test", "content": "valid"})
        bad = json.dumps({"content": "missing bank field"})  # missing required 'bank'
        wal_path.write_text(f"{good}\n{bad}\n")

        wal = HindsightWAL(wal_path)
        entries = wal.load()

        assert len(entries) == 1
        assert entries[0].content == "valid"

    def test_load_skips_entry_with_wrong_field_types(self, tmp_path: Path) -> None:
        """A WAL line where 'bank' is a list (wrong type) should be skipped."""
        wal_path = tmp_path / "wal.jsonl"
        good = json.dumps({"bank": "ok", "content": "fine"})
        bad = json.dumps({"bank": ["not", "a", "string"], "content": "hello"})
        wal_path.write_text(f"{good}\n{bad}\n")

        wal = HindsightWAL(wal_path)
        entries = wal.load()

        assert len(entries) == 1
        assert entries[0].content == "fine"

    def test_load_skips_completely_wrong_schema(self, tmp_path: Path) -> None:
        """A WAL line with valid JSON but entirely wrong fields should be skipped."""
        wal_path = tmp_path / "wal.jsonl"
        good = json.dumps({"bank": "ok", "content": "fine"})
        bad = json.dumps({"foo": "bar", "baz": 42})  # no valid WALEntry fields
        wal_path.write_text(f"{good}\n{bad}\n")

        wal = HindsightWAL(wal_path)
        entries = wal.load()

        assert len(entries) == 1
        assert entries[0].content == "fine"

    def test_validation_error_is_subclass_of_value_error(self) -> None:
        """Document that pydantic.ValidationError inherits from ValueError.

        If this test fails, it means a Pydantic upgrade removed the ValueError
        inheritance and the except clause in HindsightWAL.load() at line 82
        needs to add pydantic.ValidationError explicitly — proving issue #6625.
        """
        assert issubclass(pydantic.ValidationError, ValueError), (
            "pydantic.ValidationError no longer inherits from ValueError — "
            "HindsightWAL.load() except clause needs updating (issue #6625)"
        )

    def test_load_does_not_crash_on_mixed_corrupt_entries(self, tmp_path: Path) -> None:
        """WAL with a mix of valid, invalid-JSON, and schema-invalid entries."""
        wal_path = tmp_path / "wal.jsonl"
        lines = [
            json.dumps({"bank": "a", "content": "first"}),
            "not json at all",
            json.dumps({"wrong": "schema"}),
            "",
            json.dumps({"bank": "b", "content": "second"}),
            json.dumps({"bank": "c", "content": "third", "retries": "not_int"}),
        ]
        wal_path.write_text("\n".join(lines) + "\n")

        wal = HindsightWAL(wal_path)
        entries = wal.load()

        assert len(entries) == 2
        assert entries[0].content == "first"
        assert entries[1].content == "second"
