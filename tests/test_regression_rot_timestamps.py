"""Unit tests for RegressionRotTimestamps (#9597).

Persisted first-seen bookkeeping for the "xfail sitting > M days" age check.
Deliberately file-backed rather than derived from `git log` — CI checkouts
are frequently shallow, which would make a file's first-commit date look
artificially recent (or unavailable) and break the age computation.
"""

from __future__ import annotations

from pathlib import Path

from regression_rot_timestamps import RegressionRotTimestamps


class TestRegressionRotTimestamps:
    def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        store = RegressionRotTimestamps(tmp_path / "ts.json")
        assert store.get(123) is None

    def test_set_if_absent_records_new_key(self, tmp_path: Path) -> None:
        store = RegressionRotTimestamps(tmp_path / "ts.json")
        recorded = store.set_if_absent(123, "2026-01-01T00:00:00+00:00")
        assert recorded == "2026-01-01T00:00:00+00:00"
        assert store.get(123) == "2026-01-01T00:00:00+00:00"

    def test_set_if_absent_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        store = RegressionRotTimestamps(tmp_path / "ts.json")
        store.set_if_absent(123, "2026-01-01T00:00:00+00:00")
        second = store.set_if_absent(123, "2026-06-01T00:00:00+00:00")
        assert second == "2026-01-01T00:00:00+00:00"
        assert store.get(123) == "2026-01-01T00:00:00+00:00"

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "ts.json"
        RegressionRotTimestamps(path).set_if_absent(9, "2026-01-01T00:00:00+00:00")
        reloaded = RegressionRotTimestamps(path)
        assert reloaded.get(9) == "2026-01-01T00:00:00+00:00"

    def test_discard_removes_key(self, tmp_path: Path) -> None:
        store = RegressionRotTimestamps(tmp_path / "ts.json")
        store.set_if_absent(5, "2026-01-01T00:00:00+00:00")
        store.discard(5)
        assert store.get(5) is None

    def test_discard_missing_key_is_a_noop(self, tmp_path: Path) -> None:
        store = RegressionRotTimestamps(tmp_path / "ts.json")
        store.discard(999)  # must not raise
        assert store.get(999) is None

    def test_keep_only_prunes_everything_else(self, tmp_path: Path) -> None:
        store = RegressionRotTimestamps(tmp_path / "ts.json")
        store.set_if_absent(1, "2026-01-01T00:00:00+00:00")
        store.set_if_absent(2, "2026-01-01T00:00:00+00:00")
        store.set_if_absent(3, "2026-01-01T00:00:00+00:00")
        store.keep_only({1, 3})
        assert store.get(1) is not None
        assert store.get(2) is None
        assert store.get(3) is not None

    def test_missing_file_never_raises(self, tmp_path: Path) -> None:
        store = RegressionRotTimestamps(tmp_path / "nested" / "ts.json")
        assert store.get(1) is None
        store.set_if_absent(1, "2026-01-01T00:00:00+00:00")
        assert store.get(1) == "2026-01-01T00:00:00+00:00"

    def test_corrupt_file_treated_as_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "ts.json"
        path.write_text("not json{", encoding="utf-8")
        store = RegressionRotTimestamps(path)
        assert store.get(1) is None
