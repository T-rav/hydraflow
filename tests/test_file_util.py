"""Tests for file_util helpers: atomic_write, append_jsonl, file_lock,
rotate_backups, compact_jsonl_latest_by_key, is_newer_timestamp."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from file_util import (
    append_jsonl,
    atomic_write,
    compact_jsonl_latest_by_key,
    file_lock,
    is_newer_timestamp,
)


class TestAtomicWrite:
    def test_writes_data_to_path(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        atomic_write(target, '{"key": "value"}')
        assert target.read_text() == '{"key": "value"}'

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c" / "out.txt"
        atomic_write(target, "hello")
        assert target.read_text() == "hello"

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        target.write_text("old data")
        atomic_write(target, "new data")
        assert target.read_text() == "new data"

    def test_atomic_replace_used(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        with patch("file_util.os.replace", wraps=os.replace) as mock_replace:
            atomic_write(target, "data")
            mock_replace.assert_called_once()
            args = mock_replace.call_args[0]
            assert str(args[1]) == str(target)

    def test_cleans_up_temp_on_write_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        with (
            patch("file_util.os.fdopen", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            atomic_write(target, "data")

        temps = list(tmp_path.glob(".out-*.tmp"))
        assert temps == []

    def test_cleans_up_temp_on_fsync_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        with (
            patch("file_util.os.fsync", side_effect=OSError("fsync failed")),
            pytest.raises(OSError, match="fsync failed"),
        ):
            atomic_write(target, "data")

        temps = list(tmp_path.glob(".out-*.tmp"))
        assert temps == []

    def test_original_file_intact_on_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        target.write_text("original")
        with (
            patch("file_util.os.fsync", side_effect=OSError("fail")),
            pytest.raises(OSError),
        ):
            atomic_write(target, "replacement")

        assert target.read_text() == "original"

    def test_no_temp_files_after_success(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        atomic_write(target, "data")
        temps = list(tmp_path.glob(".out-*.tmp"))
        assert temps == []

    def test_temp_file_in_same_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        with patch(
            "file_util.tempfile.mkstemp", wraps=__import__("tempfile").mkstemp
        ) as mock_mkstemp:
            atomic_write(target, "data")
            mock_mkstemp.assert_called_once()
            kwargs = mock_mkstemp.call_args[1]
            assert str(kwargs["dir"]) == str(tmp_path)

    def test_writes_empty_string(self, tmp_path: Path) -> None:
        """atomic_write("") should create an empty file without error.

        This is the code path triggered by events.py _rotate_sync when all
        event lines are expired during log rotation.
        """
        target = tmp_path / "out.txt"
        atomic_write(target, "")
        assert target.exists()
        assert target.read_text() == ""


class TestAppendJsonl:
    def test_appends_line_with_newline(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        append_jsonl(target, '{"a":1}')
        append_jsonl(target, '{"b":2}')
        lines = target.read_text().splitlines()
        assert lines == ['{"a":1}', '{"b":2}']

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested" / "log.jsonl"
        append_jsonl(target, '{"x":1}')
        assert target.read_text() == '{"x":1}\n'

    def test_calls_fsync(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        with patch("file_util.os.fsync", wraps=os.fsync) as mock_fsync:
            append_jsonl(target, '{"synced":true}')
            mock_fsync.assert_called_once()


class TestFileLock:
    def test_creates_parent_directory_and_lock_file(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "locks" / "hydra.lock"
        with file_lock(lock_path):
            assert lock_path.exists()

    def test_acquires_and_releases_exclusive_lock(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "hydra.lock"
        calls: list[tuple[int, int]] = []

        def _record(fd: int, op: int) -> None:
            calls.append((fd, op))

        with patch("file_util.fcntl.flock", side_effect=_record), file_lock(lock_path):
            pass

        assert len(calls) == 2
        assert calls[0][1] == fcntl.LOCK_EX
        assert calls[1][1] == fcntl.LOCK_UN


class TestRotateBackups:
    def test_creates_bak_from_source(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text("v1")
        from file_util import rotate_backups

        rotate_backups(target, count=3)
        assert Path(f"{target}.bak").read_text() == "v1"

    def test_shifts_existing_bak_to_bak_1(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text("v2")
        bak = Path(f"{target}.bak")
        bak.write_text("v1")
        from file_util import rotate_backups

        rotate_backups(target, count=3)
        assert bak.read_text() == "v2"
        assert Path(f"{target}.bak.1").read_text() == "v1"

    def test_rotates_full_chain(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text("v4")
        Path(f"{target}.bak").write_text("v3")
        Path(f"{target}.bak.1").write_text("v2")
        Path(f"{target}.bak.2").write_text("v1")
        from file_util import rotate_backups

        rotate_backups(target, count=3)
        assert Path(f"{target}.bak").read_text() == "v4"
        assert Path(f"{target}.bak.1").read_text() == "v3"
        assert Path(f"{target}.bak.2").read_text() == "v2"
        assert Path(f"{target}.bak.3").read_text() == "v1"

    def test_deletes_oldest_beyond_count(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text("v5")
        Path(f"{target}.bak").write_text("v4")
        Path(f"{target}.bak.1").write_text("v3")
        Path(f"{target}.bak.2").write_text("v2")
        Path(f"{target}.bak.3").write_text("v1")
        from file_util import rotate_backups

        rotate_backups(target, count=3)
        assert not Path(f"{target}.bak.4").exists()
        # .bak.3 should exist (was .bak.2 before rotation)
        assert Path(f"{target}.bak.3").exists()

    def test_noop_when_source_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "missing.json"
        from file_util import rotate_backups

        rotate_backups(target, count=3)  # should not raise

    def test_count_of_one(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text("v2")
        Path(f"{target}.bak").write_text("v1")
        from file_util import rotate_backups

        rotate_backups(target, count=1)
        assert Path(f"{target}.bak").read_text() == "v2"
        # With count=1, the old .bak (now .bak.1) is the oldest allowed
        assert Path(f"{target}.bak.1").read_text() == "v1"


class TestIsNewerTimestamp:
    def test_microsecond_row_is_newer_than_whole_second_row(self) -> None:
        """Regression: lexically '.' < 'Z', so a STRING comparison would sort
        '...56.000001Z' before '...56Z' — but it is one microsecond NEWER."""
        assert is_newer_timestamp("2026-06-30T12:00:56.000001Z", "2026-06-30T12:00:56Z")
        assert not is_newer_timestamp(
            "2026-06-30T12:00:56Z", "2026-06-30T12:00:56.000001Z"
        )

    def test_plainly_newer_and_older(self) -> None:
        assert is_newer_timestamp("2026-06-30T00:00:00Z", "2026-06-01T00:00:00Z")
        assert not is_newer_timestamp("2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")

    def test_equal_timestamps_are_not_newer(self) -> None:
        assert not is_newer_timestamp("2026-06-30T00:00:00Z", "2026-06-30T00:00:00Z")

    def test_unparseable_candidate_is_never_newer(self) -> None:
        assert not is_newer_timestamp("not-a-timestamp", "2026-06-30T00:00:00Z")
        assert not is_newer_timestamp(None, "2026-06-30T00:00:00Z")

    def test_parseable_candidate_beats_unparseable_existing(self) -> None:
        assert is_newer_timestamp("2026-06-30T00:00:00Z", "not-a-timestamp")
        assert is_newer_timestamp("2026-06-30T00:00:00Z", None)

    def test_both_unparseable_is_not_newer(self) -> None:
        assert not is_newer_timestamp("garbage", "also-garbage")

    def test_naive_datetime_assumed_utc(self) -> None:
        # Must not raise TypeError comparing naive vs aware.
        assert is_newer_timestamp("2026-06-30T00:00:01", "2026-06-30T00:00:00Z")


def _row(key: str, ts: str, marker: str) -> str:
    return json.dumps({"adr_id": key, "timestamp": ts, "marker": marker})


class TestCompactJsonlLatestByKey:
    def test_keeps_only_latest_row_per_key(self, tmp_path: Path) -> None:
        target = tmp_path / "metrics.jsonl"
        append_jsonl(target, _row("0100", "2026-06-01T00:00:00Z", "old"))
        append_jsonl(target, _row("0042", "2026-06-15T00:00:00Z", "only"))
        append_jsonl(target, _row("0100", "2026-06-30T00:00:00Z", "new"))

        compact_jsonl_latest_by_key(target, key="adr_id", ts_key="timestamp")

        rows = [json.loads(line) for line in target.read_text().splitlines()]
        by_key = {row["adr_id"]: row for row in rows}
        assert len(rows) == 2
        assert by_key["0100"]["marker"] == "new"
        assert by_key["0042"]["marker"] == "only"

    def test_microsecond_boundary_latter_is_newer(self, tmp_path: Path) -> None:
        """'...56Z' vs '...56.000001Z': the LATTER is newer despite lexically
        sorting first ('.' < 'Z') — compaction must compare parsed datetimes."""
        target = tmp_path / "metrics.jsonl"
        append_jsonl(target, _row("0100", "2026-06-30T12:00:56Z", "whole-second"))
        append_jsonl(target, _row("0100", "2026-06-30T12:00:56.000001Z", "microsecond"))

        compact_jsonl_latest_by_key(target, key="adr_id", ts_key="timestamp")

        rows = [json.loads(line) for line in target.read_text().splitlines()]
        assert len(rows) == 1
        assert rows[0]["marker"] == "microsecond"

    def test_corrupt_and_blank_lines_dropped_without_raising(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "metrics.jsonl"
        with open(target, "w", encoding="utf-8") as f:
            f.write("{not valid json\n")
            f.write("\n")
            f.write('["not", "an", "object"]\n')
            f.write(_row("0100", "2026-06-30T00:00:00Z", "good") + "\n")

        compact_jsonl_latest_by_key(target, key="adr_id", ts_key="timestamp")

        rows = [json.loads(line) for line in target.read_text().splitlines()]
        assert len(rows) == 1
        assert rows[0]["marker"] == "good"

    def test_rows_missing_key_dropped(self, tmp_path: Path) -> None:
        target = tmp_path / "metrics.jsonl"
        append_jsonl(target, json.dumps({"timestamp": "2026-06-30T00:00:00Z"}))
        append_jsonl(target, _row("0100", "2026-06-30T00:00:00Z", "keyed"))

        compact_jsonl_latest_by_key(target, key="adr_id", ts_key="timestamp")

        rows = [json.loads(line) for line in target.read_text().splitlines()]
        assert len(rows) == 1
        assert rows[0]["adr_id"] == "0100"

    def test_unparseable_timestamp_treated_as_oldest(self, tmp_path: Path) -> None:
        target = tmp_path / "metrics.jsonl"
        # Appended AFTER the valid row; a string comparison would rank
        # "not-a-timestamp" > "2026-..." and wrongly keep the garbage row.
        append_jsonl(target, _row("0100", "2026-06-30T00:00:00Z", "valid"))
        append_jsonl(target, _row("0100", "not-a-timestamp", "garbage"))
        # A key whose ONLY row has a garbage timestamp still survives.
        append_jsonl(target, _row("0042", "not-a-timestamp", "sole-garbage"))

        compact_jsonl_latest_by_key(target, key="adr_id", ts_key="timestamp")

        rows = [json.loads(line) for line in target.read_text().splitlines()]
        by_key = {row["adr_id"]: row for row in rows}
        assert by_key["0100"]["marker"] == "valid"
        assert by_key["0042"]["marker"] == "sole-garbage"

    def test_result_file_parses_fully(self, tmp_path: Path) -> None:
        target = tmp_path / "metrics.jsonl"
        for i in range(10):
            append_jsonl(
                target, _row(f"{i % 3:04d}", f"2026-06-{i + 1:02d}T00:00:00Z", str(i))
            )

        compact_jsonl_latest_by_key(target, key="adr_id", ts_key="timestamp")

        for line in target.read_text().splitlines():
            json.loads(line)  # every surviving line is complete, valid JSON

    def test_rewrites_atomically_via_os_replace(self, tmp_path: Path) -> None:
        target = tmp_path / "metrics.jsonl"
        append_jsonl(target, _row("0100", "2026-06-01T00:00:00Z", "old"))
        append_jsonl(target, _row("0100", "2026-06-30T00:00:00Z", "new"))

        with patch("file_util.os.replace", wraps=os.replace) as mock_replace:
            compact_jsonl_latest_by_key(target, key="adr_id", ts_key="timestamp")
            mock_replace.assert_called_once()
            args = mock_replace.call_args[0]
            assert str(args[1]) == str(target)

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        target = tmp_path / "missing.jsonl"
        compact_jsonl_latest_by_key(target, key="adr_id", ts_key="timestamp")
        assert not target.exists()
